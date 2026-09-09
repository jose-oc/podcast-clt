"""Inspect command for pre-flight analysis of podcast feeds, videos, and audio files."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
import typer

from podcast_cli.discovery.resolver import resolve_input
from podcast_cli.gatekeeper.inspector import PreFlightInspector
from podcast_cli.storage.repository import StorageRepository
from podcast_cli.ui.console import console


def _format_seconds(seconds: float | None) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if not seconds or seconds <= 0:
        return "Unknown"
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def inspect_command(
    input_source: str = typer.Argument(
        ...,
        help="Input source: RSS URL, show title / search term, YouTube URL, or local audio file",
    ),
    engine: str = typer.Option(
        "auto",
        "--engine",
        help="Preferred transcription engine ('auto', 'rss', 'youtube', 'whisper', 'groq', 'openai')",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Maximum number of individual episodes to show in detailed table",
    ),
) -> None:
    """Inspect a podcast feed, show, YouTube link, or audio file and display pre-flight analysis."""
    with console.status_spinner(f"Resolving input source '[bold white]{input_source}[/bold white]'..."):
        resolved = resolve_input(input_source)

    # If it was a search result, try resolving the first search result feed
    if resolved.source_type == "search":
        if not resolved.search_results:
            console.warning(f"No podcast found matching '{input_source}'.")
            return
        top_result = resolved.search_results[0]
        if not top_result.feed_url:
            console.warning(f"Found podcast '{top_result.title}' but no RSS feed URL was available.")
            return
        console.info(f"Resolved search query to '[bold white]{top_result.title}[/bold white]'.")
        with console.status_spinner(f"Fetching RSS feed for '[bold white]{top_result.title}[/bold white]'..."):
            resolved = resolve_input(top_result.feed_url)

    if not resolved.episodes:
        console.warning(f"No episodes found for '{input_source}'.")
        return

    repo = StorageRepository()
    inspector = PreFlightInspector(repository=repo)
    summary = inspector.inspect_episodes_sync(resolved.episodes, preferred_engine=engine)

    # Render Show Header Panel
    show_title = (
        resolved.show_metadata.title
        if resolved.show_metadata
        else (resolved.episodes[0].show_title if resolved.episodes else "Source Inspection")
    )
    header_info = [f"[bold cyan]Show Title:[/bold cyan] {show_title}"]
    header_info.append(f"[bold cyan]Source Type:[/bold cyan] {resolved.source_type.upper()}")
    header_info.append(f"[bold cyan]Total Episodes Found:[/bold cyan] {len(resolved.episodes)}")

    if resolved.show_metadata and resolved.show_metadata.feed_url:
        header_info.append(f"[bold cyan]Feed URL:[/bold cyan] [dim]{resolved.show_metadata.feed_url}[/dim]")
    if resolved.show_metadata and resolved.show_metadata.description:
        desc_snippet = resolved.show_metadata.description[:180] + ("..." if len(resolved.show_metadata.description) > 180 else "")
        header_info.append(f"[bold cyan]Description:[/bold cyan] [dim]{desc_snippet}[/dim]")

    console.panel("\n".join(header_info), title="[bold blue]Show Overview[/bold blue]", border_style="cyan")

    # Render Pre-Flight Workload Table
    workload_table = Table(
        title="[bold cyan]Pre-Flight Workload & Tier Breakdown[/bold cyan]",
        border_style="dim blue",
        header_style="bold cyan",
        show_header=True,
    )
    workload_table.add_column("Metric", style="cyan", no_wrap=True)
    workload_table.add_column("Value", style="bold white")

    workload_table.add_row("Total Episodes", str(summary.total_episodes))
    workload_table.add_row("Total Audio Duration", summary.formatted_duration)
    workload_table.add_row("Estimated Audio Cache", summary.formatted_storage)

    tier_desc = (
        f"[green]Cached:[/green] {summary.tier_breakdown.get('cached', 0)}  |  "
        f"[cyan]RSS (Tier 1):[/cyan] {summary.tier_breakdown.get('rss', 0)}  |  "
        f"[blue]YouTube (Tier 2):[/blue] {summary.tier_breakdown.get('youtube', 0)}  |  "
        f"[yellow]Whisper (Tier 3):[/yellow] {summary.tier_breakdown.get('whisper', 0)}  |  "
        f"[magenta]Cloud (Tier 4):[/magenta] {summary.tier_breakdown.get('cloud', 0)}"
    )
    workload_table.add_row("Tier Strategy Breakdown", tier_desc)
    console.print(workload_table)

    # Render Episodes List Table
    ep_table = Table(
        title=f"[bold cyan]Episodes Preview (Showing {min(len(resolved.episodes), limit)} of {len(resolved.episodes)})[/bold cyan]",
        border_style="dim blue",
        header_style="bold cyan",
        show_lines=True,
    )
    ep_table.add_column("#", style="bold cyan", justify="right", width=4)
    ep_table.add_column("Episode Title", style="bold white", min_width=30)
    ep_table.add_column("Duration", style="dim", justify="center", width=12)
    ep_table.add_column("Target Tier", justify="center", width=16)
    ep_table.add_column("Published Date", style="dim", width=18)

    tier_styles = {
        "cached": "[bold green]CACHED[/bold green]",
        "rss": "[bold cyan]RSS (Tier 1)[/bold cyan]",
        "youtube": "[bold blue]YouTube (Tier 2)[/bold blue]",
        "whisper": "[bold yellow]Whisper (Tier 3)[/bold yellow]",
        "cloud": "[bold magenta]Cloud (Tier 4)[/bold magenta]",
    }

    for idx, ep in enumerate(resolved.episodes[:limit], start=1):
        target_tier = summary.episode_tiers.get(ep.episode_id, "whisper")
        styled_tier = tier_styles.get(target_tier, target_tier.upper())
        dur_str = _format_seconds(ep.duration_seconds)
        pub_date = ep.published_date[:10] if ep.published_date else "-"
        ep_table.add_row(str(idx), ep.episode_title, dur_str, styled_tier, pub_date)

    console.print(ep_table)
