"""Transcribe command for podcast episodes, YouTube videos, and local audio files."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from podcast_ctl.cli import selection
from podcast_ctl.discovery.resolver import resolve_input
from podcast_ctl.engines.base import TranscriptionEngineError
from podcast_ctl.engines.dispatcher import TranscriptionDispatcher
from podcast_ctl.exporters.manager import ExportManager
from podcast_ctl.gatekeeper.inspector import PreFlightInspector
from podcast_ctl.gatekeeper.learning import KnowledgeLearner
from podcast_ctl.gatekeeper.prompts import (
    estimate_cloud_cost,
    prompt_batch_confirmation,
    prompt_cloud_cost_approval,
)
from podcast_ctl.models.transcript import EpisodeMetadata
from podcast_ctl.storage.repository import StorageRepository
from podcast_ctl.ui.console import console

# Aliases kept so the pre-0.4 helper names (and their tests) keep working;
# the implementations now live in podcast_ctl.cli.selection.
_LEADING_TITLE_NUMBER_REGEX = selection.LEADING_TITLE_NUMBER_REGEX
_match_episode_number = selection.match_episode_number
_episode_number_label = selection.episode_number_label


def _select_episodes(
    all_episodes: list[EpisodeMetadata],
    episode_filter: str | None = None,
    all_flag: bool = False,
    latest: int = 1,
) -> list[EpisodeMetadata]:
    """Filter episode list based on CLI arguments."""
    if not all_episodes:
        return []

    if episode_filter is not None:
        query = episode_filter.strip()
        if query.isdigit():
            # 1. Numeric filters match the episode's own number first
            #    (feed-declared itunes:episode, then a leading number in the title).
            number_matches = _match_episode_number(all_episodes, int(query))
            if number_matches:
                return number_matches
            # 2. Fall back to 1-based positional index in feed order (newest first).
            idx = int(query)
            if 1 <= idx <= len(all_episodes):
                return [all_episodes[idx - 1]]

        # 3. Exact episode_id match
        exact_id_matches = [ep for ep in all_episodes if ep.episode_id == query]
        if exact_id_matches:
            return exact_id_matches

        # 4. Case-insensitive title substring match
        title_matches = [ep for ep in all_episodes if query.lower() in ep.episode_title.lower()]
        if title_matches:
            return title_matches

        return []

    if all_flag:
        return list(all_episodes)

    # Default to latest N episodes
    count = max(1, latest)
    return list(all_episodes[:count])


def _select_episodes_multi(
    all_episodes: list[EpisodeMetadata],
    *,
    episode_filter: str | None,
    all_flag: bool,
    latest: int,
    episodes_spec: str | None,
    match_pattern: str | None,
    since: date | None,
    until: date | None,
    pick: bool,
) -> list[EpisodeMetadata]:
    """Resolve the final episode selection from all CLI selection options.

    ``--episode``/``--all``/``--latest`` keep their single-exact semantics; the
    multi-select options (``--episodes``, ``--match``, ``--since``/``--until``)
    compose as a logical AND, and ``--pick`` narrows the result interactively.
    """
    multi_selection = any([episodes_spec, match_pattern, since is not None, until is not None, pick])
    if episode_filter is not None or not multi_selection:
        return _select_episodes(
            all_episodes,
            episode_filter=episode_filter,
            all_flag=all_flag,
            latest=latest,
        )

    if episodes_spec:
        spec = selection.parse_episode_number_spec(episodes_spec)
        selected, missing = selection.select_by_number_spec(all_episodes, spec)
        if missing:
            console.warning(f"No episode found with number(s): {', '.join(str(n) for n in missing)}")
    else:
        selected = list(all_episodes)

    if match_pattern:
        selected = selection.filter_by_title_pattern(selected, match_pattern)

    if since is not None or until is not None:
        selected, unknown_dates = selection.filter_by_publication_date(selected, since, until)
        if unknown_dates:
            console.info(f"Excluded {unknown_dates} episode(s) without a parseable publication date.")

    if pick and selected:
        picked = selection.pick_episodes_interactively(selected)
        if picked is None:
            console.warning("Selection cancelled.")
            raise typer.Exit(code=0)
        return picked

    return selected


def _display_selected_episodes(selected_episodes: list[EpisodeMetadata]) -> None:
    """Show exactly which episode(s) will be transcribed before any confirmation prompt."""
    if len(selected_episodes) == 1:
        ep = selected_episodes[0]
        lines = [
            f"[bold white]Episode number:[/bold white] {_episode_number_label(ep)}",
            f"[bold white]Title:[/bold white] {ep.episode_title}",
            f"[bold white]Episode ID:[/bold white] [dim]{ep.episode_id}[/dim]",
        ]
        if ep.published_date:
            lines.append(f"[bold white]Published:[/bold white] {ep.published_date}")
        lines.append(f"[bold white]Duration:[/bold white] {selection.format_duration(ep.duration_seconds)}")
        console.print(
            Panel(
                "\n".join(lines),
                title="[bold cyan]Selected episode[/bold cyan]",
                border_style="cyan",
            )
        )
        return

    table = Table(title="Selected episodes", title_style="bold cyan", header_style="bold cyan")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Episode No.", justify="right")
    table.add_column("Title", overflow="fold")
    table.add_column("Published", style="dim")
    table.add_column("Duration", style="dim")
    preview_limit = 20
    for position, ep in enumerate(selected_episodes[:preview_limit], start=1):
        published = selection.episode_publication_date(ep)
        table.add_row(
            str(position),
            _episode_number_label(ep),
            ep.episode_title,
            published.isoformat() if published else (ep.published_date or "-"),
            selection.format_duration(ep.duration_seconds),
        )
    console.print(table)
    if len(selected_episodes) > preview_limit:
        console.info(f"... and {len(selected_episodes) - preview_limit} more episode(s).")


def transcribe_command(
    input_source: Annotated[
        str,
        typer.Argument(
            help="Podcast RSS feed URL, Apple Podcasts search term, YouTube URL, or local audio file",
        ),
    ],
    episode: Annotated[
        str | None,
        typer.Option(
            "--episode",
            "-e",
            help=(
                "Specific episode to transcribe by episode number (e.g. 2894), "
                "1-based index in feed order, episode ID/GUID, or title substring"
            ),
        ),
    ] = None,
    episodes: Annotated[
        str | None,
        typer.Option(
            "--episodes",
            help=(
                "Multiple episodes by number: comma-separated list and/or inclusive ranges, "
                "e.g. '2890,2894,2901' or '2890..2900'"
            ),
        ),
    ] = None,
    match: Annotated[
        str | None,
        typer.Option(
            "--match",
            help="Select episodes whose title matches a case-insensitive regular expression",
        ),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Select episodes published on or after this date (YYYY-MM-DD)",
        ),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option(
            "--until",
            help="Select episodes published on or before this date (YYYY-MM-DD)",
        ),
    ] = None,
    pick: Annotated[
        bool,
        typer.Option(
            "--pick",
            help="Interactively pick episodes from a multi-select list (combines with the other filters)",
        ),
    ] = False,
    all_episodes: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="Transcribe all available episodes in the feed",
        ),
    ] = False,
    latest: Annotated[
        int,
        typer.Option(
            "--latest",
            "-l",
            help="Transcribe the latest N episodes (default: 1; ignored when any selection option is given)",
        ),
    ] = 1,
    engine: Annotated[
        str,
        typer.Option(
            "--engine",
            help="Transcription engine tier: 'auto', 'rss', 'youtube', 'whisper', 'groq', 'openai'",
        ),
    ] = "auto",
    model_size: Annotated[
        str,
        typer.Option(
            "--model-size",
            help="Whisper model size: 'tiny', 'base', 'small', 'medium', 'large-v3'",
        ),
    ] = "base",
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Export format(s): 'both', 'markdown', 'prose', 'srt', 'vtt', 'json', 'all'",
        ),
    ] = "both",
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            help="Output directory path for transcript files",
        ),
    ] = Path("./transcripts"),
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Auto-confirm pre-flight inspection and interactive prompts",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Force re-transcription even if cached transcript exists",
        ),
    ] = False,
    keep_audio: Annotated[
        bool,
        typer.Option(
            "--keep-audio",
            help="Retain downloaded audio files in cache directory after transcription",
        ),
    ] = False,
) -> None:
    """Transcribe podcast episodes, YouTube videos, or local audio files with multi-tier fallback."""
    # 1. Resolve input source
    with console.status_spinner(f"Resolving input source '[bold white]{input_source}[/bold white]'..."):
        resolved = resolve_input(input_source)

    if resolved.source_type == "search":
        if not resolved.search_results:
            console.error(f"No podcast found matching query: '{input_source}'")
            raise typer.Exit(code=1)
        top_match = resolved.search_results[0]
        if not top_match.feed_url:
            console.error(f"Podcast '{top_match.title}' does not have an RSS feed URL.")
            raise typer.Exit(code=1)
        console.info(f"Resolved search query to '[bold white]{top_match.title}[/bold white]'.")
        with console.status_spinner(f"Fetching RSS feed for '{top_match.title}'..."):
            resolved = resolve_input(top_match.feed_url)

    if not resolved.episodes:
        console.error(f"No episodes found for source: '{input_source}'")
        raise typer.Exit(code=1)

    # 2. Select / filter episodes
    multi_flags = any([episodes, match, since, until, pick])
    if episode and multi_flags:
        console.error(
            "--episode cannot be combined with --episodes, --match, --since, --until or --pick. "
            "Use --episode for one exact episode, or the multi-select options without it."
        )
        raise typer.Exit(code=2)
    if all_episodes and multi_flags:
        console.error(
            "--all cannot be combined with --episodes, --match, --since, --until or --pick; "
            "filters already scan the whole feed."
        )
        raise typer.Exit(code=2)

    try:
        since_date = selection.parse_cli_date(since) if since else None
        until_date = selection.parse_cli_date(until) if until else None
        if since_date and until_date and since_date > until_date:
            raise selection.EpisodeSpecError(
                f"--since ({since_date.isoformat()}) must be on or before --until ({until_date.isoformat()})."
            )
        selected_episodes = _select_episodes_multi(
            resolved.episodes,
            episode_filter=episode,
            all_flag=all_episodes,
            latest=latest,
            episodes_spec=episodes,
            match_pattern=match,
            since=since_date,
            until=until_date,
            pick=pick,
        )
    except selection.EpisodeSpecError as exc:
        console.error(str(exc))
        raise typer.Exit(code=2) from exc

    if not selected_episodes:
        if episode:
            console.error(f"No episode found matching filter: '{episode}'")
        elif multi_flags:
            console.error("No episodes matched the given selection filters.")
        else:
            console.error("No episodes selected.")
        raise typer.Exit(code=1)

    # 3. Show exactly which episode(s) will be transcribed
    _display_selected_episodes(selected_episodes)

    # 4. Pre-Flight Gatekeeper Analysis
    repo = StorageRepository()
    inspector = PreFlightInspector(repository=repo)
    summary = inspector.inspect_episodes_sync(selected_episodes, preferred_engine=engine)

    # 5. Batch Confirmation Prompt
    confirmed = prompt_batch_confirmation(summary, auto_confirm=yes, console=console)
    if not confirmed:
        console.warning("Transcription aborted by user.")
        raise typer.Exit(code=0)

    # 6. Transcription & Export Loop
    dispatcher = TranscriptionDispatcher(storage_repo=repo)
    export_mgr = ExportManager()

    success_count = 0
    failure_count = 0

    for ep_idx, ep in enumerate(selected_episodes, start=1):
        console.rule(f"Episode {ep_idx}/{len(selected_episodes)}: {ep.episode_title}", style="dim cyan")

        # Check Cloud cost guardrail if explicitly requesting cloud or if pre-flight resolved to cloud
        resolved_tier = summary.episode_tiers.get(ep.episode_id, engine)
        if (engine in ("cloud", "groq", "openai") or resolved_tier == "cloud") and not force:
            cached_item = repo.get_transcript(ep.effective_show_id, ep.episode_id)
            if cached_item is None:
                is_allowed = KnowledgeLearner.is_cloud_allowed(repo, ep.effective_show_id)
                if not is_allowed and not yes:
                    cost_est = estimate_cloud_cost(ep.duration_seconds)
                    approved, always = prompt_cloud_cost_approval(ep, cost_est, auto_confirm=yes, console=console)
                    if not approved:
                        console.warning(f"Skipping cloud transcription for '{ep.episode_title}'.")
                        failure_count += 1
                        continue
                    if always:
                        KnowledgeLearner.learn_cloud_preference(repo, ep.effective_show_id, True)

        try:
            with console.status_spinner(f"Transcribing '{ep.episode_title}'..."):
                result = asyncio.run(
                    dispatcher.transcribe(
                        episode=ep,
                        engine=engine,
                        force=force,
                        model_size=model_size,
                        keep_audio=keep_audio,
                    )
                )

            saved_paths = export_mgr.export_all(
                result=result,
                output_dir=output_dir,
                formats=format,
            )

            console.success(
                f"Successfully transcribed '{ep.episode_title}' [bold cyan]({result.tier_used.upper()})[/bold cyan]"
            )
            for fmt_name, path in saved_paths.items():
                console.print(
                    f"  [bold green]✔[/bold green] [cyan]{fmt_name.upper()}:[/cyan] [dim underline]{path}[/dim underline]"
                )

            success_count += 1

        except TranscriptionEngineError as exc:
            console.error(f"Transcription failed for '{ep.episode_title}'", exception=exc)
            failure_count += 1
        except Exception as exc:
            console.error(f"Unexpected error processing '{ep.episode_title}'", exception=exc)
            failure_count += 1

    console.rule("Batch Summary", style="dim cyan")
    if failure_count == 0:
        console.success(f"Completed {success_count} of {len(selected_episodes)} episode(s) successfully.")
    else:
        console.warning(
            f"Completed {success_count} episode(s) with {failure_count} failure(s) out of {len(selected_episodes)} total."
        )
        if success_count == 0:
            raise typer.Exit(code=1)
