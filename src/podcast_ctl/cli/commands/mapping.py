"""Mapping command for managing learned Show and Episode YouTube mappings."""

from __future__ import annotations

from typing import Annotated, Optional
from rich.table import Table
import typer

from podcast_ctl.gatekeeper.learning import KnowledgeLearner
from podcast_ctl.models.knowledge import ShowMapping
from podcast_ctl.storage.repository import StorageRepository
from podcast_ctl.ui.console import console

mapping_app = typer.Typer(
    help="Manage learned Show <-> YouTube Channel and Episode <-> YouTube Video mappings.",
    no_args_is_help=True,
)

mapping_add_app = typer.Typer(
    help="Add a new YouTube channel or video mapping.",
    no_args_is_help=True,
)
mapping_remove_app = typer.Typer(
    help="Remove an existing YouTube mapping.",
    no_args_is_help=True,
)

mapping_app.add_typer(mapping_add_app, name="add")
mapping_app.add_typer(mapping_remove_app, name="remove")


@mapping_app.command("list")
def list_mappings(
    show: Annotated[
        Optional[str],
        typer.Option(
            "--show",
            "-s",
            help="Filter mappings by specific show ID or feed URL",
        ),
    ] = None,
) -> None:
    """List all stored Show and Episode YouTube mappings."""
    repo = StorageRepository()
    show_mappings = repo.list_show_mappings()
    episode_mappings = repo.list_episode_mappings(show_id=show)

    if show is not None:
        show_mappings = [m for m in show_mappings if m.feed_url == show or m.show_title == show]

    if not show_mappings and not episode_mappings:
        console.info("No YouTube mappings found in the knowledge database.")
        return

    # Show Mappings Table
    if show_mappings:
        show_table = Table(
            title="[bold cyan]Show <-> YouTube Channel Mappings[/bold cyan]",
            border_style="dim blue",
            header_style="bold cyan",
            show_lines=True,
        )
        show_table.add_column("Feed URL / Show ID", style="bold white", min_width=30)
        show_table.add_column("Show Title", style="cyan", min_width=20)
        show_table.add_column("YouTube Channel URL", style="dim underline", min_width=35)

        for sm in show_mappings:
            show_table.add_row(sm.feed_url, sm.show_title or "-", sm.youtube_channel_url or "-")
        console.print(show_table)

    # Episode Mappings Table
    if episode_mappings:
        ep_table = Table(
            title="[bold cyan]Episode <-> YouTube Video Mappings[/bold cyan]",
            border_style="dim blue",
            header_style="bold cyan",
            show_lines=True,
        )
        ep_table.add_column("Show ID", style="cyan", min_width=20)
        ep_table.add_column("Episode ID", style="bold white", min_width=25)
        ep_table.add_column("YouTube Video URL", style="dim underline", min_width=35)
        ep_table.add_column("Confirmed", justify="center", width=12)

        for em in episode_mappings:
            conf_str = "[green]Yes[/green]" if em.confirmed_by_user else "[yellow]Auto[/yellow]"
            ep_table.add_row(em.show_id, em.episode_id, em.youtube_video_url, conf_str)
        console.print(ep_table)


@mapping_add_app.command("show")
def add_show_mapping(
    feed_url: Annotated[str, typer.Argument(help="Podcast RSS feed URL")],
    youtube_channel_url: Annotated[str, typer.Argument(help="Associated YouTube channel URL")],
    title: Annotated[Optional[str], typer.Option("--title", "-t", help="Optional show title")] = None,
) -> None:
    """Add or update a Show <-> YouTube Channel mapping."""
    repo = StorageRepository()
    mapping = ShowMapping(
        feed_url=feed_url.strip(),
        show_title=title.strip() if title else feed_url.strip(),
        youtube_channel_url=youtube_channel_url.strip(),
    )
    repo.save_show_mapping(mapping)
    console.success(
        f"Saved show mapping:\n"
        f"  • Feed URL: [bold white]{mapping.feed_url}[/bold white]\n"
        f"  • Channel:  [dim underline]{mapping.youtube_channel_url}[/dim underline]"
    )


@mapping_add_app.command("episode")
def add_episode_mapping(
    show_id: str = typer.Argument(..., help="Show identifier or title"),
    episode_id: str = typer.Argument(..., help="Episode identifier or GUID"),
    youtube_video_url: str = typer.Argument(..., help="Direct YouTube video URL"),
) -> None:
    """Add or update an Episode <-> YouTube Video mapping."""
    repo = StorageRepository()
    mapping = KnowledgeLearner.learn_youtube_mapping(
        repository=repo,
        show_id=show_id.strip(),
        episode_id=episode_id.strip(),
        youtube_url=youtube_video_url.strip(),
    )
    console.success(
        f"Saved episode mapping:\n"
        f"  • Show ID:    [bold white]{mapping.show_id}[/bold white]\n"
        f"  • Episode ID: [bold white]{mapping.episode_id}[/bold white]\n"
        f"  • Video URL:  [dim underline]{mapping.youtube_video_url}[/dim underline]"
    )


@mapping_remove_app.command("show")
def remove_show_mapping(
    feed_url: str = typer.Argument(..., help="Podcast RSS feed URL to remove"),
) -> None:
    """Remove a Show <-> YouTube Channel mapping."""
    repo = StorageRepository()
    deleted = repo.delete_show_mapping(feed_url.strip())
    if deleted:
        console.success(f"Removed show mapping for '[bold white]{feed_url}[/bold white]'.")
    else:
        console.warning(f"No show mapping found for '[bold white]{feed_url}[/bold white]'.")


@mapping_remove_app.command("episode")
def remove_episode_mapping(
    show_id: str = typer.Argument(..., help="Show identifier or title"),
    episode_id: str = typer.Argument(..., help="Episode identifier or GUID"),
) -> None:
    """Remove an Episode <-> YouTube Video mapping."""
    repo = StorageRepository()
    deleted = repo.delete_episode_mapping(show_id.strip(), episode_id.strip())
    if deleted:
        console.success(f"Removed episode mapping for '[bold white]{show_id}::{episode_id}[/bold white]'.")
    else:
        console.warning(f"No episode mapping found for '[bold white]{show_id}::{episode_id}[/bold white]'.")
