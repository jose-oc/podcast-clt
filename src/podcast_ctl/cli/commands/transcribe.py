"""Transcribe command for podcast episodes, YouTube videos, and local audio files."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

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
        # 1. 1-based numeric index
        if query.isdigit():
            idx = int(query)
            if 1 <= idx <= len(all_episodes):
                return [all_episodes[idx - 1]]

        # 2. Exact episode_id match
        exact_id_matches = [ep for ep in all_episodes if ep.episode_id == query]
        if exact_id_matches:
            return exact_id_matches

        # 3. Case-insensitive title substring match
        title_matches = [ep for ep in all_episodes if query.lower() in ep.episode_title.lower()]
        if title_matches:
            return title_matches

        return []

    if all_flag:
        return list(all_episodes)

    # Default to latest N episodes
    count = max(1, latest)
    return list(all_episodes[:count])


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
            help="Specific episode to transcribe by 1-based index, episode ID/GUID, or title substring",
        ),
    ] = None,
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
            help="Transcribe the latest N episodes (default: 1)",
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
    selected_episodes = _select_episodes(
        all_episodes=resolved.episodes,
        episode_filter=episode,
        all_flag=all_episodes,
        latest=latest,
    )

    if not selected_episodes:
        if episode:
            console.error(f"No episode found matching filter: '{episode}'")
        else:
            console.error("No episodes selected.")
        raise typer.Exit(code=1)

    # 3. Pre-Flight Gatekeeper Analysis
    repo = StorageRepository()
    inspector = PreFlightInspector(repository=repo)
    summary = inspector.inspect_episodes_sync(selected_episodes, preferred_engine=engine)

    # 4. Batch Confirmation Prompt
    confirmed = prompt_batch_confirmation(summary, auto_confirm=yes, console=console)
    if not confirmed:
        console.warning("Transcription aborted by user.")
        raise typer.Exit(code=0)

    # 5. Transcription & Export Loop
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
                console.print(f"  [bold green]✔[/bold green] [cyan]{fmt_name.upper()}:[/cyan] [dim underline]{path}[/dim underline]")

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
