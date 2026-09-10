"""Unified input resolver detecting and dispatching sources (Local, YouTube, RSS, iTunes Search)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, Optional
import httpx
from pydantic import BaseModel, ConfigDict, Field

from podcast_ctl.discovery.itunes import PodcastSearchResult, search_itunes
from podcast_ctl.discovery.local_file import (
    inspect_local_file,
    is_supported_audio_file,
)
from podcast_ctl.discovery.rss import ShowMetadata, fetch_and_parse_feed
from podcast_ctl.discovery.youtube import (
    is_youtube_url,
    parse_youtube_url,
    youtube_video_to_metadata,
)
from podcast_ctl.models.transcript import EpisodeMetadata

logger = logging.getLogger(__name__)


class ResolvedSource(BaseModel):
    """Normalized result of resolving an arbitrary user input string."""

    model_config = ConfigDict(extra="ignore")

    source_type: Literal["local", "youtube", "rss", "search"] = Field(
        ...,
        description="Identified source type: 'local', 'youtube', 'rss', or 'search'",
    )
    query: str = Field(..., description="Original input query, URL, or file path")
    show_metadata: Optional[ShowMetadata] = Field(
        default=None,
        description="Show metadata if input resolved from an RSS feed",
    )
    episodes: list[EpisodeMetadata] = Field(
        default_factory=list,
        description="List of resolved episode metadata objects",
    )
    search_results: list[PodcastSearchResult] = Field(
        default_factory=list,
        description="iTunes search results if input was a text search query",
    )
    raw_data: Optional[dict[str, Any]] = Field(
        default=None,
        description="Source-specific raw metadata (e.g. YouTube playlist/channel info)",
    )

    @property
    def is_single_episode(self) -> bool:
        """True if exactly one episode is resolved."""
        return len(self.episodes) == 1

    @property
    def total_duration_seconds(self) -> float:
        """Sum of all known episode durations in seconds."""
        return sum(ep.duration_seconds or 0.0 for ep in self.episodes)


def resolve_input(
    input_source: str,
    search_limit: int = 10,
    client: Optional[httpx.Client] = None,
    timeout: float = 15.0,
) -> ResolvedSource:
    """Resolve any input string (local audio file, YouTube URL, RSS URL, or plain text query).

    Resolution Order:
        1. Local File: If file exists on disk and has supported extension.
        2. YouTube: If URL matches YouTube video, shorts, playlist, or channel.
        3. RSS Feed: If URL starts with http:// or https://.
        4. iTunes Search: If plain text, search Apple Podcasts catalog.

    Args:
        input_source: File path, URL, or plain text query.
        search_limit: Max search results if falling back to iTunes search.
        client: Optional httpx.Client for network calls.
        timeout: Network timeout in seconds.

    Returns:
        ResolvedSource with populated metadata and episode(s).
    """
    if not input_source or not input_source.strip():
        return ResolvedSource(source_type="search", query="", search_results=[])

    raw_input = input_source.strip()

    # 1. Check Local File
    clean_path_str = raw_input[7:] if raw_input.startswith("file://") else raw_input
    candidate_path = Path(clean_path_str).expanduser()
    if candidate_path.exists() and candidate_path.is_file() and is_supported_audio_file(candidate_path):
        try:
            ep_meta = inspect_local_file(candidate_path)
            return ResolvedSource(
                source_type="local",
                query=raw_input,
                episodes=[ep_meta],
            )
        except Exception as exc:
            logger.warning("Local file inspection failed for %r: %s", clean_path_str, exc)

    # 2. Check YouTube URL
    if is_youtube_url(raw_input):
        parsed_yt = parse_youtube_url(raw_input)
        yt_type = parsed_yt.get("type")

        if yt_type == "video":
            try:
                ep_meta = youtube_video_to_metadata(raw_input)
                return ResolvedSource(
                    source_type="youtube",
                    query=raw_input,
                    episodes=[ep_meta],
                    raw_data=parsed_yt,
                )
            except Exception as exc:
                logger.warning("Failed to extract YouTube video metadata for %r: %s", raw_input, exc)
                # Fallback to minimal episode metadata from URL / ID
                vid = parsed_yt.get("id") or "unknown_yt"
                fallback_ep = EpisodeMetadata(
                    show_title="YouTube",
                    episode_title=f"YouTube Video ({vid})",
                    episode_id=vid,
                    audio_url=f"https://www.youtube.com/watch?v={vid}",
                    source_type="youtube",
                )
                return ResolvedSource(
                    source_type="youtube",
                    query=raw_input,
                    episodes=[fallback_ep],
                    raw_data=parsed_yt,
                )

        # Playlist or channel
        return ResolvedSource(
            source_type="youtube",
            query=raw_input,
            episodes=[],
            raw_data=parsed_yt,
        )

    # 3. Check HTTP/HTTPS URL -> Parse as RSS feed
    if raw_input.startswith(("http://", "https://")):
        try:
            show_meta, episodes = fetch_and_parse_feed(raw_input, client=client, timeout=timeout)
            return ResolvedSource(
                source_type="rss",
                query=raw_input,
                show_metadata=show_meta,
                episodes=episodes,
            )
        except Exception as exc:
            logger.warning("RSS feed fetch/parse failed for %r: %s", raw_input, exc)
            return ResolvedSource(
                source_type="rss",
                query=raw_input,
                show_metadata=ShowMetadata(title="Failed Feed", feed_url=raw_input),
                episodes=[],
            )

    # 4. Plain text search query -> Search Apple Podcasts
    results = search_itunes(raw_input, limit=search_limit, client=client, timeout=timeout)
    return ResolvedSource(
        source_type="search",
        query=raw_input,
        search_results=results,
    )
