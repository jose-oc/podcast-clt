"""Interactive prompts and pre-flight confirmation dialogs for podcast-ctl."""

from __future__ import annotations

import sys

import questionary
from rich.panel import Panel
from rich.table import Table

from podcast_ctl.gatekeeper.inspector import PreFlightSummary
from podcast_ctl.models.transcript import EpisodeMetadata
from podcast_ctl.ui.console import UIConsole
from podcast_ctl.ui.console import console as default_console


def estimate_cloud_cost(duration_seconds: float | None, rate_per_minute: float = 0.006) -> float:
    """Estimate cloud transcription cost based on audio duration (default rate $0.006/min for Groq)."""
    if not duration_seconds or duration_seconds <= 0:
        return 0.0
    return round((duration_seconds / 60.0) * rate_per_minute, 4)


def prompt_batch_confirmation(
    summary: PreFlightSummary,
    auto_confirm: bool = False,
    console: UIConsole | None = None,
) -> bool:
    """Display batch summary table and prompt user for confirmation to proceed.

    Args:
        summary: Aggregated pre-flight inspection summary.
        auto_confirm: If True, bypass interactive prompt and return True.
        console: Optional UIConsole instance for rendering.

    Returns:
        True if user confirms or auto-confirmed, False if aborted.
    """
    c = console or default_console

    # Build rich summary table
    tbl = Table(
        title="[bold cyan]Pre-Flight Workload Inspection[/bold cyan]",
        border_style="dim blue",
        header_style="bold cyan",
        show_header=True,
    )
    tbl.add_column("Workload Metric", style="cyan", no_wrap=True)
    tbl.add_column("Value", style="bold white")

    tbl.add_row("Total Episodes", str(summary.total_episodes))
    tbl.add_row("Total Audio Duration", summary.formatted_duration)
    tbl.add_row("Estimated Audio Cache", summary.formatted_storage)

    # Breakdown section
    tier_desc = (
        f"[green]Cached in SQLite:[/green] {summary.tier_breakdown.get('cached', 0)}  |  "
        f"[cyan]RSS (Tier 1):[/cyan] {summary.tier_breakdown.get('rss', 0)}  |  "
        f"[blue]YouTube (Tier 2):[/blue] {summary.tier_breakdown.get('youtube', 0)}  |  "
        f"[yellow]Whisper (Tier 3):[/yellow] {summary.tier_breakdown.get('whisper', 0)}  |  "
        f"[magenta]Cloud (Tier 4):[/magenta] {summary.tier_breakdown.get('cloud', 0)}"
    )
    tbl.add_row("Tier Strategy Breakdown", tier_desc)

    c.print(tbl)

    # Bypass if non-interactive or auto_confirm
    if auto_confirm or not sys.stdin.isatty():
        c.info("Auto-confirming pre-flight inspection (non-interactive or --yes specified).")
        return True

    # Prompt user interactively
    try:
        response = questionary.confirm(
            "Proceed with transcription?",
            default=True,
        ).ask()
        if response is None:
            return False
        return bool(response)
    except Exception:
        return True


def prompt_youtube_mapping(
    show_title: str,
    episode_title: str,
    candidate_title: str,
    candidate_url: str,
    duration_str: str,
    channel_title: str,
    auto_confirm: bool = False,
    confidence: float | None = None,
    console: UIConsole | None = None,
) -> tuple[str, str | None]:
    """Prompt user to validate a candidate YouTube video match for an episode.

    Args:
        show_title: Name of the podcast show.
        episode_title: Title of the podcast episode.
        candidate_title: Title of candidate YouTube video found.
        candidate_url: URL of candidate YouTube video found.
        duration_str: Formatted duration of the YouTube video.
        channel_title: Channel or uploader name of candidate video.
        auto_confirm: If True, bypass interactive prompt and accept candidate.
        confidence: Optional match confidence score (0.0 - 1.0).
        console: Optional UIConsole instance for rendering.

    Returns:
        tuple[action, custom_url]:
            action: 'use' | 'skip_yt' | 'custom' | 'skip_episode'
            custom_url: Custom YouTube URL if action == 'custom', else None.
    """
    c = console or default_console

    conf_str = f" ({confidence * 100:.0f}% match)" if confidence is not None else ""
    body = (
        f"[bold]Show:[/bold] {show_title}\n"
        f"[bold]Episode:[/bold] {episode_title}\n\n"
        f"[bold cyan]Candidate YouTube Video{conf_str}:[/bold cyan]\n"
        f"  • Title: [bold white]{candidate_title}[/bold white]\n"
        f"  • Channel: [dim]{channel_title}[/dim]\n"
        f"  • Duration: [dim]{duration_str}[/dim]\n"
        f"  • URL: [link={candidate_url}]{candidate_url}[/link]"
    )
    p = Panel(
        body,
        title="[bold blue]YouTube Match Candidate[/bold blue]",
        border_style="cyan",
        expand=False,
    )
    c.print(p)

    if auto_confirm or not sys.stdin.isatty():
        c.info("Auto-accepting YouTube video candidate (non-interactive or --yes).")
        return ("use", None)

    try:
        choice = questionary.select(
            "Use this YouTube video for captions?",
            choices=[
                questionary.Choice("Yes, use this video", value="use"),
                questionary.Choice("No, skip YouTube search (try Whisper)", value="skip_yt"),
                questionary.Choice("Enter custom YouTube URL", value="custom"),
                questionary.Choice("Skip this episode entirely", value="skip_episode"),
            ],
            default="use",
        ).ask()

        if choice is None:
            return ("skip_yt", None)

        if choice == "custom":
            custom_url = questionary.text(
                "Enter custom YouTube video URL:",
                validate=lambda val: True if val and val.strip() else "Please enter a valid URL",
            ).ask()
            if custom_url and custom_url.strip():
                return ("custom", custom_url.strip())
            return ("skip_yt", None)

        return (choice, None)
    except Exception:
        return ("use", None)


def prompt_cloud_cost_approval(
    episode: EpisodeMetadata,
    estimated_cost_usd: float,
    auto_confirm: bool = False,
    console: UIConsole | None = None,
) -> tuple[bool, bool]:
    """Prompt user to approve cloud API expenditure for an episode.

    Args:
        episode: EpisodeMetadata for the target episode.
        estimated_cost_usd: Estimated cost in USD for cloud transcription.
        auto_confirm: If True, bypass prompt and approve for this episode.
        console: Optional UIConsole instance for rendering.

    Returns:
        tuple[approved, always_for_show]:
            approved: True if transcription should proceed via cloud.
            always_for_show: True if the user elected to remember this choice for all episodes of this show.
    """
    c = console or default_console

    msg = (
        f"Fallback to Cloud API for '[bold white]{episode.episode_title}[/bold white]'.\n"
        f"Transcribe via Groq/OpenAI Whisper API? ([bold yellow]Est. cost: ${estimated_cost_usd:.3f}[/bold yellow])"
    )
    p = Panel(
        msg,
        title="[bold yellow]Cloud Transcription Cost Guardrail[/bold yellow]",
        border_style="yellow",
        expand=False,
    )
    c.print(p)

    if auto_confirm:
        c.info("Auto-approving cloud transcription (--yes specified).")
        return (True, False)

    if not sys.stdin.isatty():
        c.warning("Non-interactive terminal: declining cloud transcription guardrail to prevent unexpected charges.")
        return (False, False)

    try:
        choice = questionary.select(
            f"Approve cloud transcription for '{episode.effective_show_id}'?",
            choices=[
                questionary.Choice("Approve for this episode", value="yes"),
                questionary.Choice("Always approve for this show", value="always"),
                questionary.Choice("Decline / Skip cloud", value="no"),
            ],
            default="yes",
        ).ask()

        if choice == "always":
            return (True, True)
        elif choice == "yes":
            return (True, False)
        else:
            return (False, False)
    except Exception:
        return (False, False)
