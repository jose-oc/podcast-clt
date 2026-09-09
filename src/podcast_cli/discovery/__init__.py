"""Discovery and Ingestion package for podcast-cli.

Provides unified resolution for RSS feeds, iTunes search, YouTube URLs, and local media.
"""

from __future__ import annotations

from podcast_cli.discovery.itunes import (
    ITUNES_LOOKUP_URL,
    ITUNES_SEARCH_URL,
    ItunesPodcast,
    PodcastSearchResult,
    lookup_itunes,
    lookup_podcast,
    search_itunes,
    search_podcast,
)
from podcast_cli.discovery.local_file import (
    SUPPORTED_AUDIO_EXTENSIONS,
    inspect_local_file,
    is_supported_audio_file,
    probe_media_file,
)
from podcast_cli.discovery.resolver import (
    ResolvedSource,
    resolve_input,
)
from podcast_cli.discovery.rss import (
    ShowMetadata,
    fetch_and_parse_feed,
    fetch_feed,
    parse_duration,
    parse_feed_content,
)
from podcast_cli.discovery.youtube import (
    extract_youtube_video_id,
    get_youtube_subtitles_metadata,
    get_youtube_video_info,
    is_youtube_url,
    parse_youtube_url,
    search_youtube_candidates,
    youtube_video_to_metadata,
)

__all__ = [
    # iTunes
    "ITUNES_SEARCH_URL",
    "ITUNES_LOOKUP_URL",
    "PodcastSearchResult",
    "ItunesPodcast",
    "search_itunes",
    "lookup_itunes",
    "search_podcast",
    "lookup_podcast",
    # RSS & Podcasting 2.0
    "ShowMetadata",
    "parse_duration",
    "parse_feed_content",
    "fetch_feed",
    "fetch_and_parse_feed",
    # YouTube
    "extract_youtube_video_id",
    "is_youtube_url",
    "parse_youtube_url",
    "search_youtube_candidates",
    "get_youtube_video_info",
    "get_youtube_subtitles_metadata",
    "youtube_video_to_metadata",
    # Local Files
    "SUPPORTED_AUDIO_EXTENSIONS",
    "is_supported_audio_file",
    "probe_media_file",
    "inspect_local_file",
    # Unified Resolver
    "ResolvedSource",
    "resolve_input",
]
