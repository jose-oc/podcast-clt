"""Discovery and Ingestion package for podcast-ctl.

Provides unified resolution for RSS feeds, iTunes search, YouTube URLs, and local media.
"""

from __future__ import annotations

from podcast_ctl.discovery.itunes import (
    ITUNES_LOOKUP_URL,
    ITUNES_SEARCH_URL,
    ItunesPodcast,
    PodcastSearchResult,
    lookup_itunes,
    lookup_podcast,
    search_itunes,
    search_podcast,
)
from podcast_ctl.discovery.local_file import (
    SUPPORTED_AUDIO_EXTENSIONS,
    inspect_local_file,
    is_supported_audio_file,
    probe_media_file,
)
from podcast_ctl.discovery.resolver import (
    ResolvedSource,
    resolve_input,
)
from podcast_ctl.discovery.rss import (
    ShowMetadata,
    fetch_and_parse_feed,
    fetch_feed,
    parse_duration,
    parse_feed_content,
)
from podcast_ctl.discovery.youtube import (
    extract_youtube_video_id,
    get_youtube_subtitles_metadata,
    get_youtube_video_info,
    is_youtube_url,
    parse_youtube_url,
    search_youtube_candidates,
    youtube_video_to_metadata,
)

__all__ = [
    "ITUNES_LOOKUP_URL",
    "ITUNES_SEARCH_URL",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "ItunesPodcast",
    "PodcastSearchResult",
    "ResolvedSource",
    "ShowMetadata",
    "extract_youtube_video_id",
    "fetch_and_parse_feed",
    "fetch_feed",
    "get_youtube_subtitles_metadata",
    "get_youtube_video_info",
    "inspect_local_file",
    "is_supported_audio_file",
    "is_youtube_url",
    "lookup_itunes",
    "lookup_podcast",
    "parse_duration",
    "parse_feed_content",
    "parse_youtube_url",
    "probe_media_file",
    "resolve_input",
    "search_itunes",
    "search_podcast",
    "search_youtube_candidates",
    "youtube_video_to_metadata",
]
