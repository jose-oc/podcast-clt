"""Knowledge base commands: build the index, embed chunks, search it, inspect status."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from podcast_ctl.kb.builder import KbBuilder
from podcast_ctl.kb.config import get_default_kb_dir, kb_db_path, kb_index_path
from podcast_ctl.kb.embed import DEFAULT_BATCH_SIZE, embed_kb
from podcast_ctl.kb.embeddings import (
    PROVIDER_LOCAL,
    PROVIDER_OPENAI_COMPATIBLE,
    EmbeddingBackendUnavailable,
    EmbeddingIdentityMismatch,
    EmbeddingProvider,
    get_embedding_provider,
)
from podcast_ctl.kb.search import (
    MODE_HYBRID,
    MODE_LEXICAL,
    MODE_VECTOR,
    format_citation,
    format_context_block,
    hybrid_search_kb,
    search_kb,
    vector_search_kb,
)
from podcast_ctl.kb.store import KbStore
from podcast_ctl.ui.console import console

kb_app = typer.Typer(
    help="Build and query the knowledge base derived from cached transcripts.",
    no_args_is_help=True,
)


def _format_size(size_bytes: int) -> str:
    """Format bytes into KB or MB."""
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def _open_store(kb_dir: Path | None) -> KbStore:
    root = kb_dir or get_default_kb_dir()
    return KbStore(kb_db_path(root))


def _load_provider(provider: str, model: str | None) -> EmbeddingProvider:
    """Build the embedding provider or exit with the setup hint."""
    try:
        return get_embedding_provider(provider, model)
    except EmbeddingBackendUnavailable as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


@kb_app.command("build")
def kb_build(
    show: Annotated[
        str | None,
        typer.Option("--show", "-s", help="Only build episodes of this show ID/title."),
    ] = None,
    kb_dir: Annotated[
        Path | None,
        typer.Option("--kb-dir", help="Override the knowledge base directory."),
    ] = None,
) -> None:
    """Build (or incrementally update) the knowledge base from cached transcripts.

    Derives per-episode Markdown, the INDEX.md catalog, and the FTS5 chunk
    index. Unchanged episodes are skipped, so it is safe to run repeatedly.
    """
    builder = KbBuilder(kb_dir=kb_dir)
    report = builder.build(show_id=show)

    console.print(f"[bold cyan]Knowledge base:[/bold cyan] {report.kb_dir}")
    if report.built:
        console.print(f"[green]✓ Built/updated {len(report.built)} episode(s)[/green]")
        for label in report.built:
            console.print(f"  [dim]+[/dim] {label}")
    if report.skipped:
        console.print(f"[dim]↷ Skipped {len(report.skipped)} unchanged episode(s)[/dim]")
    if report.pruned:
        console.print(f"[yellow]✗ Pruned {len(report.pruned)} episode(s) no longer cached[/yellow]")
        for label in report.pruned:
            console.print(f"  [dim]-[/dim] {label}")
    if not report.built and not report.skipped and not report.pruned:
        console.print("[yellow]No cached transcripts found.[/yellow] Run [bold]podcast-ctl transcribe[/bold] first.")

    console.print(f"[bold cyan]Index catalog:[/bold cyan] {report.index_path}")


@kb_app.command("embed")
def kb_embed(
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            "-p",
            help=f"Embedding backend: '{PROVIDER_LOCAL}' (default, sentence-transformers on your machine) "
            f"or '{PROVIDER_OPENAI_COMPATIBLE}' (optional cloud adapter, configured via env vars).",
        ),
    ] = PROVIDER_LOCAL,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Embedding model name (defaults per provider)."),
    ] = None,
    show: Annotated[
        str | None,
        typer.Option("--show", "-s", help="Only embed chunks of this show ID/title."),
    ] = None,
    reindex: Annotated[
        bool,
        typer.Option("--reindex", help="Drop all stored embeddings and rebuild them with the selected provider."),
    ] = False,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", help="Texts per embedding call."),
    ] = DEFAULT_BATCH_SIZE,
    kb_dir: Annotated[
        Path | None,
        typer.Option("--kb-dir", help="Override the knowledge base directory."),
    ] = None,
) -> None:
    """Embed indexed chunks for vector and hybrid search (local by default).

    Incremental and idempotent: only chunks without an embedding are
    processed. Every vector records the provider identity (backend, model,
    version, dimensions); switching providers requires --reindex so vectors
    from incompatible models never mix.
    """
    store = _open_store(kb_dir)
    if store.count_chunks(show_id=show) == 0:
        console.print("[yellow]No indexed chunks found.[/yellow] Run [bold]podcast-ctl kb build[/bold] first.")
        raise typer.Exit(code=1)

    backend = _load_provider(provider, model)
    console.print(f"[bold cyan]Embedding provider:[/bold cyan] {backend.identity()}")

    with console.status_spinner("Embedding chunks..."):
        try:
            report = embed_kb(store, backend, show_id=show, reindex=reindex, batch_size=batch_size)
        except EmbeddingIdentityMismatch as exc:
            console.error(str(exc))
            raise typer.Exit(code=1) from exc

    if report.reindexed:
        console.print(f"[yellow]✗ Removed {report.removed} existing embedding(s) for reindex[/yellow]")
    if report.embedded:
        console.print(f"[green]✓ Embedded {report.embedded} chunk(s)[/green]")
    if report.already_indexed:
        console.print(f"[dim]↷ {report.already_indexed} chunk(s) already had embeddings[/dim]")
    if not report.embedded and not report.already_indexed:
        console.print("[yellow]Nothing to embed.[/yellow]")


def _resolve_search(
    store: KbStore,
    query: str,
    mode: str,
    limit: int,
    show: str | None,
    provider_name: str,
    model: str | None,
) -> tuple[list[dict[str, object]], str]:
    """Run the search, resolving 'auto' mode and degrading gracefully.

    Returns (hits, effective_mode). Auto mode picks hybrid when embeddings
    exist and the provider is usable, and falls back to lexical otherwise.
    """
    has_embeddings = store.stats()["embeddings"] > 0
    requested = mode
    if mode == "auto":
        mode = MODE_HYBRID if has_embeddings else MODE_LEXICAL

    if mode == MODE_LEXICAL:
        return search_kb(store, query, limit=limit, show_id=show), MODE_LEXICAL

    try:
        backend = get_embedding_provider(provider_name, model)
    except EmbeddingBackendUnavailable as exc:
        if requested == "auto":
            console.warning(f"Vector search unavailable ({exc}); falling back to lexical search.")
            return search_kb(store, query, limit=limit, show_id=show), MODE_LEXICAL
        console.error(str(exc))
        raise typer.Exit(code=1) from exc

    stored_identity = store.embedding_identity()
    if stored_identity and stored_identity != backend.identity():
        message = (
            f"Indexed embeddings come from '{stored_identity}', but the selected provider is "
            f"'{backend.identity()}'. Run [bold]podcast-ctl kb embed --reindex[/bold] with the new provider, "
            "or search with the provider that built the index."
        )
        if requested == "auto":
            console.warning(message + " Falling back to lexical search.")
            return search_kb(store, query, limit=limit, show_id=show), MODE_LEXICAL
        console.error(message)
        raise typer.Exit(code=1)

    if mode == MODE_VECTOR:
        return vector_search_kb(store, backend, query, limit=limit, show_id=show), MODE_VECTOR
    return hybrid_search_kb(store, backend, query, limit=limit, show_id=show), MODE_HYBRID


@kb_app.command("search")
def kb_search(
    query: Annotated[str, typer.Argument(help="Free-text search over the knowledge base.")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum number of chunks to return.")] = 10,
    show: Annotated[
        str | None,
        typer.Option("--show", "-s", help="Restrict results to this show ID/title."),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Retrieval mode: auto (default), lexical (FTS5 BM25), vector (cosine over embeddings), "
            "or hybrid (RRF fusion of both). Auto uses hybrid when embeddings exist, lexical otherwise.",
        ),
    ] = "auto",
    provider: Annotated[
        str,
        typer.Option("--provider", "-p", help="Embedding backend for vector/hybrid modes."),
    ] = PROVIDER_LOCAL,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Embedding model name (defaults per provider)."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON (one object per chunk) for piping into other tools."),
    ] = False,
    context: Annotated[
        bool,
        typer.Option("--context", "-c", help="Emit full chunk text as Markdown blocks, ready to paste into an LLM."),
    ] = False,
    kb_dir: Annotated[
        Path | None,
        typer.Option("--kb-dir", help="Override the knowledge base directory."),
    ] = None,
) -> None:
    """Search the knowledge base and print chunks with [Episode @ mm:ss] citations."""
    if mode not in ("auto", MODE_LEXICAL, MODE_VECTOR, MODE_HYBRID):
        console.error(f"Unknown mode '{mode}'. Available: auto, {MODE_LEXICAL}, {MODE_VECTOR}, {MODE_HYBRID}.")
        raise typer.Exit(code=1)

    store = _open_store(kb_dir)
    hits, effective_mode = _resolve_search(store, query, mode, limit, show, provider, model)

    if json_output:
        payload = []
        for hit in hits:
            item: dict[str, object] = {
                "citation": format_citation(hit),
                "show": hit["show_title"],
                "episode": hit["episode_title"],
                "chapter": hit["chapter"],
                "start_s": hit["start_s"],
                "end_s": hit["end_s"],
                "score": hit["rank"],
                "text": hit["text"],
            }
            if effective_mode != MODE_LEXICAL:
                item["mode"] = effective_mode
                item["sources"] = hit.get("sources", [effective_mode])
                item["bm25"] = hit.get("bm25")
                item["cosine"] = hit.get("cosine")
            payload.append(item)
        # Plain stdout print: parseable JSON without Rich markup.
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if not hits:
        console.print(f"[yellow]No results for[/yellow] [bold]{query}[/bold]")
        return

    if context:
        console.print("\n\n".join(format_context_block(hit) for hit in hits))
        return

    table = Table(
        title=f"[bold cyan]KB results for “{query}” ({effective_mode})[/bold cyan]",
        border_style="dim blue",
        header_style="bold cyan",
        show_header=True,
    )
    table.add_column("Citation", style="bold white", no_wrap=True)
    table.add_column("Chapter", style="cyan")
    if effective_mode == MODE_HYBRID:
        table.add_column("Sources", style="magenta")
    table.add_column("Snippet", style="white", overflow="fold")

    for hit in hits:
        row = [format_citation(hit), str(hit["chapter"])]
        if effective_mode == MODE_HYBRID:
            sources = hit.get("sources", [])
            row.append("+".join(str(s) for s in sources) if isinstance(sources, list) else str(sources))
        row.append(str(hit["snippet"]))
        table.add_row(*row)

    console.print(table)


@kb_app.command("status")
def kb_status(
    kb_dir: Annotated[
        Path | None,
        typer.Option("--kb-dir", help="Override the knowledge base directory."),
    ] = None,
) -> None:
    """Show knowledge base location, size, and index statistics."""
    root = kb_dir or get_default_kb_dir()
    db_path = kb_db_path(root)

    if not db_path.exists():
        console.print(f"[yellow]No knowledge base at[/yellow] {root}")
        console.print("Run [bold]podcast-ctl kb build[/bold] after transcribing episodes.")
        return

    store = KbStore(db_path)
    stats = store.stats()

    table = Table(
        title="[bold cyan]Knowledge Base Status[/bold cyan]",
        border_style="dim blue",
        header_style="bold cyan",
        show_header=True,
    )
    table.add_column("Item", style="cyan", no_wrap=True)
    table.add_column("Value", style="bold white")

    table.add_row("KB directory", str(root))
    table.add_row("Index database", f"{db_path} ({_format_size(db_path.stat().st_size)})")
    table.add_row("Catalog (INDEX.md)", str(kb_index_path(root)))
    table.add_row("Indexed episodes", str(stats["episodes"]))
    table.add_row("Indexed chunks", str(stats["chunks"]))
    table.add_row("Embedded chunks", str(stats["embeddings"]))
    table.add_row("Embedding provider", store.embedding_identity() or "[dim]none — run podcast-ctl kb embed[/dim]")

    console.print(table)
