"""Mapping command for managing learned Show and Episode YouTube mappings."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from podcast_ctl.discovery.resolver import resolve_input
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
        str | None,
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
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            "-t",
            help="Show title exactly as it appears in the feed (default: resolved from the feed)",
        ),
    ] = None,
) -> None:
    """Add or update a Show <-> YouTube Channel mapping."""
    repo = StorageRepository()
    show_title = title.strip() if title else None
    if show_title is None:
        try:
            resolved = resolve_input(feed_url.strip())
            if resolved.show_metadata and resolved.show_metadata.title:
                show_title = resolved.show_metadata.title
        except Exception:
            show_title = None
        if show_title:
            console.info(f"Resolved show title from the feed: '[bold white]{show_title}[/bold white]'.")
        else:
            console.warning(
                "Could not fetch the feed to learn the show title; storing the feed URL as title. "
                "The YouTube channel fallback matches mappings by the feed title, so pass --title "
                "with the exact title shown by 'podcast-ctl inspect <feed_url>'."
            )
            show_title = feed_url.strip()
    mapping = ShowMapping(
        feed_url=feed_url.strip(),
        show_title=show_title,
        youtube_channel_url=youtube_channel_url.strip(),
    )
    repo.save_show_mapping(mapping)
    console.success(
        f"Saved show mapping:\n"
        f"  • Feed URL: [bold white]{mapping.feed_url}[/bold white]\n"
        f"  • Channel:  [dim underline]{mapping.youtube_channel_url}[/dim underline]"
    )


def _resolve_episode_mapping_keys(show_id: str, episode_id_or_title: str) -> tuple[str, str, str | None]:
    """Resolve a show reference and an episode GUID-or-title to transcription-time keys.

    Transcription looks episode mappings up by "<feed title>::<RSS GUID>". This
    helper fetches the show's feed so the mapping can be added with the
    episode's exact title (resolved here to its GUID) and with the show given
    as a search term or feed URL (normalized to the feed title). If the feed
    cannot be fetched, the values are kept as provided so explicit GUID
    mappings still work offline.

    Returns:
        (show_key, episode_guid, resolved_title) - resolved_title is set when a
        title was resolved to a GUID.
    """
    try:
        resolved = resolve_input(show_id)
        if resolved.source_type == "search":
            if not resolved.search_results or not resolved.search_results[0].feed_url:
                raise ValueError("no RSS feed found for that show")
            resolved = resolve_input(resolved.search_results[0].feed_url)
        episodes = resolved.episodes
        if not episodes:
            raise ValueError("no episodes found in the feed")
    except Exception as exc:
        console.warning(
            f"Could not fetch the feed for '[bold white]{show_id}[/bold white]' ({exc}); "
            "saving the mapping exactly as provided. If you passed the episode title instead "
            "of its RSS GUID, it will not match at transcription time."
        )
        return show_id, episode_id_or_title, None

    canonical_show_id = episodes[0].effective_show_id

    for ep in episodes:
        if ep.episode_id == episode_id_or_title:
            return canonical_show_id, episode_id_or_title, None

    title_matches = [ep for ep in episodes if ep.episode_title.strip().lower() == episode_id_or_title.lower()]
    if len(title_matches) == 1:
        match = title_matches[0]
        console.info(f"Resolved episode title to GUID '[bold white]{match.episode_id}[/bold white]'.")
        return canonical_show_id, match.episode_id, match.episode_title

    if len(title_matches) > 1:
        guid_lines = "\n".join(f"  • {ep.episode_id} ({(ep.published_date or 'no date')[:10]})" for ep in title_matches)
        console.error(
            f"Several episodes share the title '[bold white]{episode_id_or_title}[/bold white]'. "
            f"Add the mapping with its RSS GUID instead:\n{guid_lines}"
        )
        raise typer.Exit(code=1)

    console.error(
        f"No episode with GUID or exact title '[bold white]{episode_id_or_title}[/bold white]' found "
        f"in the feed for '[bold white]{canonical_show_id}[/bold white]'. "
        "Run 'podcast-ctl inspect <show>' to list episodes with their RSS GUIDs."
    )
    raise typer.Exit(code=1)


@mapping_add_app.command("episode")
def add_episode_mapping(
    show_id: str = typer.Argument(..., help="Show title (as in the RSS feed) or RSS feed URL"),
    episode_id: str = typer.Argument(
        ...,
        help="Episode RSS GUID (see the 'Episode GUID' column of 'podcast-ctl inspect <show>') "
        "or the exact episode title",
    ),
    youtube_video_url: str = typer.Argument(..., help="Direct YouTube video URL"),
) -> None:
    """Add or update an Episode <-> YouTube Video mapping."""
    repo = StorageRepository()
    show_key, episode_guid, resolved_title = _resolve_episode_mapping_keys(show_id.strip(), episode_id.strip())
    mapping = KnowledgeLearner.learn_youtube_mapping(
        repository=repo,
        show_id=show_key,
        episode_id=episode_guid,
        youtube_url=youtube_video_url.strip(),
    )
    resolved_line = f"\n  • Title:      [dim]{resolved_title}[/dim]" if resolved_title else ""
    console.success(
        f"Saved episode mapping:\n"
        f"  • Show ID:    [bold white]{mapping.show_id}[/bold white]\n"
        f"  • Episode ID: [bold white]{mapping.episode_id}[/bold white]{resolved_line}\n"
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
    episode_id: str = typer.Argument(..., help="Episode RSS GUID (as used in 'mapping list')"),
) -> None:
    """Remove an Episode <-> YouTube Video mapping."""
    repo = StorageRepository()
    deleted = repo.delete_episode_mapping(show_id.strip(), episode_id.strip())
    if deleted:
        console.success(f"Removed episode mapping for '[bold white]{show_id}::{episode_id}[/bold white]'.")
    else:
        console.warning(f"No episode mapping found for '[bold white]{show_id}::{episode_id}[/bold white]'.")
