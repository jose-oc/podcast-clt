"""Mapping command for managing learned Show and Episode YouTube mappings."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from podcast_ctl.discovery.resolver import resolve_input
from podcast_ctl.engines.channel_search import (
    DEFAULT_SIMILARITY_THRESHOLD,
    list_channel_videos,
    match_episode_to_videos,
)
from podcast_ctl.gatekeeper.learning import KnowledgeLearner
from podcast_ctl.models.knowledge import EpisodeMapping, ShowMapping
from podcast_ctl.storage.repository import StorageRepository
from podcast_ctl.ui.console import console

mapping_app = typer.Typer(
    help="Manage learned Show <-> YouTube Channel and Episode <-> YouTube Video mappings.",
    no_args_is_help=True,
)

mapping_add_app = typer.Typer(
    help="""Add a mapping. COMMAND picks what to map: 'show' or 'episode'.

\b
Examples:
  podcast-ctl mapping add show <feed_url> <channel_url>
  podcast-ctl mapping add episode "Huberman Lab" "<episode title or RSS GUID>" <video_url>

To match every episode of a show against its whole YouTube channel in one
pass, use 'podcast-ctl mapping sync <show>' instead of adding episodes one
by one.""",
    no_args_is_help=True,
)
mapping_remove_app = typer.Typer(
    help="""Remove a mapping. COMMAND picks what to unmap: 'show' or 'episode'.

\b
Examples:
  podcast-ctl mapping remove show <feed_url>
  podcast-ctl mapping remove episode "Huberman Lab" "<episode RSS GUID>"

Run 'podcast-ctl mapping list' first to see the exact identifiers stored.""",
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
    """List all stored Show and Episode YouTube mappings.

    \b
    Examples:
      podcast-ctl mapping list
      podcast-ctl mapping list --show "Huberman Lab"
    """
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
    """Add or update a Show <-> YouTube Channel mapping.

    \b
    Examples:
      podcast-ctl mapping add show <feed_url> <channel_url>
    """
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
    """Add or update an Episode <-> YouTube Video mapping.

    \b
    Examples:
      podcast-ctl mapping add episode "Huberman Lab" "<episode title or RSS GUID>" <video_url>
    """
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
    """Remove a Show <-> YouTube Channel mapping.

    \b
    Examples:
      podcast-ctl mapping remove show <feed_url>
    """
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
    """Remove an Episode <-> YouTube Video mapping.

    \b
    Examples:
      podcast-ctl mapping remove episode "Huberman Lab" "<episode RSS GUID>"
    """
    repo = StorageRepository()
    deleted = repo.delete_episode_mapping(show_id.strip(), episode_id.strip())
    if deleted:
        console.success(f"Removed episode mapping for '[bold white]{show_id}::{episode_id}[/bold white]'.")
    else:
        console.warning(f"No episode mapping found for '[bold white]{show_id}::{episode_id}[/bold white]'.")


@mapping_app.command("sync")
def sync_mappings(
    show: Annotated[str, typer.Argument(help="Show title (as in the RSS feed) or RSS feed URL")],
    channel: Annotated[
        str | None,
        typer.Option(
            "--channel",
            "-c",
            help="YouTube channel URL (default: the channel of the stored show mapping)",
        ),
    ] = None,
    threshold: Annotated[
        float,
        typer.Option(help="Minimum normalized title similarity (0-1) to accept a match"),
    ] = DEFAULT_SIMILARITY_THRESHOLD,
    max_videos: Annotated[
        int | None,
        typer.Option(
            "--max-videos",
            help="Search only the N most recent channel videos (default: the full channel catalog)",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report the matches found without saving anything"),
    ] = False,
) -> None:
    """Match every episode of a show against its YouTube channel in one pass.

    The feed and the channel catalog are each listed once and every episode
    title is compared locally, so large back catalogs do not cost one request
    per episode. Accepted matches are stored as auto-discovered (unconfirmed)
    episode mappings; episodes that already have a mapping are left untouched.

    Use this when the per-episode fallback during transcription cannot reach
    an episode: that fallback only searches the 60 most recent channel videos.

    \b
    Examples:
      podcast-ctl mapping sync "Huberman Lab"
      podcast-ctl mapping sync "Huberman Lab" --dry-run --threshold 0.9
    """
    if not 0.0 < threshold <= 1.0:
        console.error(f"--threshold must be in (0, 1], got {threshold}. For example: --threshold 0.8.")
        raise typer.Exit(code=2)

    # 1. Fetch the feed once (search term or feed URL)
    with console.status_spinner(f"Fetching feed for '[bold white]{show}[/bold white]'..."):
        try:
            resolved = resolve_input(show.strip())
            if resolved.source_type == "search":
                if not resolved.search_results or not resolved.search_results[0].feed_url:
                    raise ValueError("no RSS feed found for that show")
                resolved = resolve_input(resolved.search_results[0].feed_url)
            episodes = resolved.episodes
            if not episodes:
                raise ValueError("no episodes found in the feed")
        except Exception as exc:
            console.error(
                f"Could not fetch the feed for '[bold white]{show}[/bold white]': {exc}. "
                "Check the show name or feed URL and your network connection."
            )
            raise typer.Exit(code=1) from exc

    canonical_show_id = episodes[0].effective_show_id
    feed_url = resolved.show_metadata.feed_url if resolved.show_metadata else None

    # 2. Resolve the channel: --channel wins, otherwise the stored show mapping
    repo = StorageRepository()
    channel_url = channel.strip() if channel else None
    if channel_url is None:
        show_mapping = repo.find_show_mapping(canonical_show_id)
        if show_mapping is None and feed_url:
            show_mapping = repo.find_show_mapping(feed_url)
        if show_mapping and show_mapping.youtube_channel_url:
            channel_url = show_mapping.youtube_channel_url
        else:
            console.error(
                f"No YouTube channel known for '[bold white]{canonical_show_id}[/bold white]'. "
                "Pass --channel <url> or add one with 'podcast-ctl mapping add show'."
            )
            raise typer.Exit(code=1)

    # 3. List the channel catalog once
    scope = f"{max_videos} most recent videos" if max_videos else "full catalog"
    with console.status_spinner(f"Listing the {scope} of [dim underline]{channel_url}[/dim underline]..."):
        try:
            videos = list_channel_videos(channel_url, max_videos=max_videos)
        except Exception as exc:
            console.error(f"Could not list the videos of [dim underline]{channel_url}[/dim underline]: {exc}")
            raise typer.Exit(code=1) from exc
    if not videos:
        console.error(
                f"No videos found on [dim underline]{channel_url}[/dim underline]. "
                "Check the channel URL and that it has public videos."
            )
        raise typer.Exit(code=1)

    # 4. Match every episode locally
    matched: list[tuple[str, str, float]] = []
    unmatched: list[tuple[str, float]] = []
    already_mapped = 0
    for ep in episodes:
        if repo.get_episode_mapping(canonical_show_id, ep.episode_id) is not None:
            already_mapped += 1
            continue
        result = match_episode_to_videos(ep.episode_title, videos, threshold=threshold)
        if result.video_url:
            matched.append((ep.episode_title, result.video_url, result.similarity))
            if not dry_run:
                repo.save_episode_mapping(
                    EpisodeMapping(
                        show_id=canonical_show_id,
                        episode_id=ep.episode_id,
                        youtube_video_url=result.video_url,
                        confirmed_by_user=False,
                    )
                )
        else:
            unmatched.append((ep.episode_title, result.best_similarity))

    # 5. Report
    verb = "Would save" if dry_run else "Saved"
    console.success(
        f"{verb} {len(matched)} episode mapping(s) for '[bold white]{canonical_show_id}[/bold white]' "
        f"({len(videos)} channel videos searched, similarity >= {threshold:.2f}). "
        f"{already_mapped} episode(s) already had a mapping; {len(unmatched)} had no close match."
    )
    if matched:
        match_table = Table(
            title="[bold cyan]Matched episodes[/bold cyan]",
            border_style="dim blue",
            header_style="bold cyan",
            show_lines=False,
        )
        match_table.add_column("Episode title", style="bold white", min_width=30, overflow="ellipsis", no_wrap=True)
        match_table.add_column("YouTube video", style="dim underline", min_width=35)
        match_table.add_column("Similarity", justify="right", width=10)
        for title, url, score in matched[:20]:
            match_table.add_row(title, url, f"{score:.0%}")
        console.print(match_table)
        if len(matched) > 20:
            console.info(f"... and {len(matched) - 20} more matched episode(s).")
    if unmatched:
        unmatched.sort(key=lambda item: item[1], reverse=True)
        console.info("Closest unmatched episodes (need an explicit 'mapping add episode' or a lower --threshold):")
        for title, score in unmatched[:10]:
            console.print(f"  • [dim]{title}[/dim] (best similarity {score:.0%})")
        if len(unmatched) > 10:
            console.info(f"... and {len(unmatched) - 10} more unmatched episode(s).")
