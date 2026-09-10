"""Knowledge base commands: build the index, search it, inspect status."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from podcast_ctl.kb.builder import KbBuilder
from podcast_ctl.kb.config import get_default_kb_dir, kb_db_path, kb_index_path
from podcast_ctl.kb.search import format_citation, format_context_block, search_kb
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


@kb_app.command("search")
def kb_search(
    query: Annotated[str, typer.Argument(help="Free-text search over the knowledge base.")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum number of chunks to return.")] = 10,
    show: Annotated[
        str | None,
        typer.Option("--show", "-s", help="Restrict results to this show ID/title."),
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
    store = _open_store(kb_dir)
    hits = search_kb(store, query, limit=limit, show_id=show)

    if json_output:
        payload = [
            {
                "citation": format_citation(hit),
                "show": hit["show_title"],
                "episode": hit["episode_title"],
                "chapter": hit["chapter"],
                "start_s": hit["start_s"],
                "end_s": hit["end_s"],
                "score": hit["rank"],
                "text": hit["text"],
            }
            for hit in hits
        ]
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
        title=f"[bold cyan]KB results for “{query}”[/bold cyan]",
        border_style="dim blue",
        header_style="bold cyan",
        show_header=True,
    )
    table.add_column("Citation", style="bold white", no_wrap=True)
    table.add_column("Chapter", style="cyan")
    table.add_column("Snippet", style="white", overflow="fold")

    for hit in hits:
        table.add_row(format_citation(hit), str(hit["chapter"]), str(hit["snippet"]))

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
    table.add_row("Embeddings (phase 2c)", str(stats["embeddings"]))

    console.print(table)
