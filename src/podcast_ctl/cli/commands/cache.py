"""Cache command for inspecting, listing, and cleaning the SQLite transcript cache."""

from __future__ import annotations

import sys
from typing import Annotated, Optional
import questionary
from rich.table import Table
import typer

from podcast_ctl.storage.repository import StorageRepository
from podcast_ctl.ui.console import console

cache_app = typer.Typer(
    help="Inspect, list, and manage SQLite cached transcripts and storage.",
    no_args_is_help=True,
)


def _format_size(size_bytes: int) -> str:
    """Format bytes into KB, MB, or GB."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


@cache_app.command("stats")
def cache_stats() -> None:
    """Display SQLite database statistics, entity counts, and disk usage."""
    repo = StorageRepository()
    stats = repo.get_cache_stats()

    table = Table(
        title="[bold cyan]Database & Cache Statistics[/bold cyan]",
        border_style="dim blue",
        header_style="bold cyan",
        show_header=True,
    )
    table.add_column("Category / Entity", style="cyan", no_wrap=True)
    table.add_column("Value / Count", style="bold white")

    table.add_row("Database Path", stats["database_path"])
    table.add_row("Database Size on Disk", _format_size(stats["size_bytes"]))
    table.add_row("Cached Transcripts", str(stats["transcripts_count"]))
    table.add_row("Indexed Shows", str(stats["shows_count"]))
    table.add_row("Indexed Episodes", str(stats["episodes_count"]))
    table.add_row("Learned YouTube Mappings", str(stats["mappings_count"]))
    table.add_row("User Preferences", str(stats["preferences_count"]))

    console.print(table)


@cache_app.command("list")
def cache_list(
    show: Annotated[
        Optional[str],
        typer.Option(
            "--show",
            "-s",
            help="Filter cached transcripts by show ID or title",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-n",
            help="Maximum number of cached transcripts to list",
        ),
    ] = 25,
) -> None:
    """List transcripts currently stored in the local SQLite cache."""
    repo = StorageRepository()
    transcripts = repo.list_transcripts(show_id=show)

    if not transcripts:
        if show:
            console.info(f"No cached transcripts found for show '{show}'.")
        else:
            console.info("No transcripts found in the local cache.")
        return

    table = Table(
        title=f"[bold cyan]Cached Transcripts (Showing {min(len(transcripts), limit)} of {len(transcripts)})[/bold cyan]",
        border_style="dim blue",
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("#", style="bold cyan", justify="right", width=4)
    table.add_column("Show Title", style="cyan", min_width=20)
    table.add_column("Episode Title", style="bold white", min_width=25)
    table.add_column("Tier", justify="center", width=12)
    table.add_column("Segments", style="dim", justify="right", width=10)
    table.add_column("Created At", style="dim", width=20)

    tier_colors = {
        "rss": "[cyan]RSS[/cyan]",
        "youtube": "[blue]YouTube[/blue]",
        "whisper": "[yellow]Whisper[/yellow]",
        "cloud": "[magenta]Cloud[/magenta]",
    }

    for idx, tr in enumerate(transcripts[:limit], start=1):
        tier_styled = tier_colors.get(tr.tier_used.lower(), tr.tier_used.upper())
        created_short = tr.created_at[:19].replace("T", " ") if tr.created_at else "-"
        table.add_row(
            str(idx),
            tr.metadata.show_title,
            tr.metadata.episode_title,
            tier_styled,
            str(len(tr.segments)),
            created_short,
        )

    console.print(table)


@cache_app.command("clean")
def cache_clean(
    show: Annotated[
        Optional[str],
        typer.Option(
            "--show",
            "-s",
            help="Clear cache only for a specific show ID",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip interactive confirmation prompt",
        ),
    ] = False,
) -> None:
    """Clear cached transcripts from the local SQLite database."""
    target_desc = f"all cached transcripts for show '{show}'" if show else "ALL cached transcripts"

    if not yes and sys.stdin.isatty():
        confirmed = questionary.confirm(
            f"Are you sure you want to delete {target_desc}?",
            default=False,
        ).ask()
        if not confirmed:
            console.info("Cache cleaning cancelled.")
            return

    repo = StorageRepository()
    deleted_count = repo.clear_cache(show_id=show)
    console.success(f"Cleared {deleted_count} cached transcript(s).")
