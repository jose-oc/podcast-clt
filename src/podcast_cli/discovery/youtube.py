"""YouTube metadata resolver, URL detector, candidate search, and subtitle inspector."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional, Union
from urllib.parse import parse_qs, urlparse
import yt_dlp

from podcast_cli.models.transcript import EpisodeMetadata

logger = logging.getLogger(__name__)

# Regular expressions for identifying YouTube URLs
YOUTUBE_VIDEO_ID_REGEX = re.compile(r"^[\w-]{11}$")
YOUTUBE_DOMAINS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "gaming.youtube.com",
    "youtu.be",
}

# Video patterns: watch?v=..., youtu.be/..., embed/..., v/..., shorts/..., live/...
YOUTUBE_VIDEO_PATH_REGEX = re.compile(
    r"^(?:/embed/|/v/|/shorts/|/live/)([\w-]{11})",
    re.IGNORECASE,
)
# Playlist pattern
YOUTUBE_PLAYLIST_REGEX = re.compile(
    r"[?&]list=([\w-]+)",
    re.IGNORECASE,
)
# Channel pattern
YOUTUBE_CHANNEL_PATH_REGEX = re.compile(
    r"^/(?:channel/(UC[\w-]+)|c/([\w-]+)|user/([\w-]+)|(@[\w.-]+))",
    re.IGNORECASE,
)


def extract_youtube_video_id(url_or_id: str) -> Optional[str]:
    """Extract an 11-character YouTube video ID from a URL or raw ID string.

    Args:
        url_or_id: YouTube URL (watch, youtu.be, shorts, embed) or raw video ID.

    Returns:
        11-character video ID if found, otherwise None.
    """
    if not url_or_id or not isinstance(url_or_id, str):
        return None

    raw = url_or_id.strip()

    # Raw 11-character ID
    if YOUTUBE_VIDEO_ID_REGEX.match(raw):
        return raw

    try:
        # Prepend scheme if missing
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw

        parsed = urlparse(raw)
        netloc = parsed.netloc.lower()

        # Check domain
        if not any(netloc == domain or netloc.endswith("." + domain) for domain in YOUTUBE_DOMAINS):
            return None

        # youtu.be/VIDEO_ID
        if "youtu.be" in netloc:
            path_part = parsed.path.strip("/")
            if path_part:
                vid = path_part.split("/")[0].split("?")[0]
                if YOUTUBE_VIDEO_ID_REGEX.match(vid):
                    return vid
            return None

        # youtube.com/watch?v=VIDEO_ID
        if parsed.path.startswith("/watch"):
            qs = parse_qs(parsed.query)
            v_list = qs.get("v")
            if v_list and YOUTUBE_VIDEO_ID_REGEX.match(v_list[0]):
                return v_list[0]

        # youtube.com/embed/VIDEO_ID, /v/VIDEO_ID, /shorts/VIDEO_ID, /live/VIDEO_ID
        match = YOUTUBE_VIDEO_PATH_REGEX.match(parsed.path)
        if match:
            vid = match.group(1)
            if YOUTUBE_VIDEO_ID_REGEX.match(vid):
                return vid

        return None
    except Exception:
        return None


def is_youtube_url(url_or_string: str) -> bool:
    """Check if an input string is a valid YouTube video, playlist, or channel URL.

    Args:
        url_or_string: URL or string to evaluate.

    Returns:
        True if it is a recognized YouTube URL, False otherwise.
    """
    if not url_or_string or not isinstance(url_or_string, str):
        return False

    raw = url_or_string.strip()

    # Check if raw ID or full URL
    if extract_youtube_video_id(raw):
        return True

    try:
        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw

        parsed = urlparse(raw)
        netloc = parsed.netloc.lower()

        if not any(netloc == domain or netloc.endswith("." + domain) for domain in YOUTUBE_DOMAINS):
            return False

        # Check for playlist or channel patterns
        if "list=" in parsed.query:
            return True
        if YOUTUBE_CHANNEL_PATH_REGEX.match(parsed.path):
            return True

        return True
    except Exception:
        return False


def parse_youtube_url(url: str) -> dict[str, Any]:
    """Parse a YouTube URL into structured component dictionary.

    Returns:
        Dictionary with:
            - 'type': 'video' | 'playlist' | 'channel' | 'unknown'
            - 'id': extracted identifier (video ID, playlist ID, channel handle/ID)
            - 'url': original URL
            - 'normalized_url': normalized canonical URL
    """
    raw = url.strip()
    video_id = extract_youtube_video_id(raw)
    if video_id:
        return {
            "type": "video",
            "id": video_id,
            "url": raw,
            "normalized_url": f"https://www.youtube.com/watch?v={video_id}",
        }

    try:
        test_url = raw if raw.startswith(("http://", "https://")) else f"https://{raw}"
        parsed = urlparse(test_url)

        # Check playlist
        qs = parse_qs(parsed.query)
        list_ids = qs.get("list")
        if list_ids:
            playlist_id = list_ids[0]
            return {
                "type": "playlist",
                "id": playlist_id,
                "url": raw,
                "normalized_url": f"https://www.youtube.com/playlist?list={playlist_id}",
            }

        # Check channel / handle
        channel_match = YOUTUBE_CHANNEL_PATH_REGEX.match(parsed.path)
        if channel_match:
            channel_id = next(g for g in channel_match.groups() if g is not None)
            return {
                "type": "channel",
                "id": channel_id,
                "url": raw,
                "normalized_url": f"https://www.youtube.com/{parsed.path.strip('/')}",
            }

        return {
            "type": "unknown",
            "id": None,
            "url": raw,
            "normalized_url": raw,
        }
    except Exception:
        return {
            "type": "unknown",
            "id": None,
            "url": raw,
            "normalized_url": raw,
        }


def search_youtube_candidates(
    query: str,
    max_results: int = 5,
    custom_ydl_opts: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Search YouTube for candidate videos matching a query (e.g. show title + episode title).

    Uses yt-dlp flat extraction to fetch search results without downloading media or heavy page assets.

    Args:
        query: Search keywords.
        max_results: Maximum number of candidate results (default: 5).
        custom_ydl_opts: Optional override for yt-dlp options.

    Returns:
        List of candidate dictionaries:
            - 'id': YouTube video ID
            - 'title': Video title
            - 'url': Full watch URL
            - 'duration': Video duration in seconds (float or int)
            - 'channel': Channel / uploader name
            - 'channel_id': Channel identifier
            - 'channel_url': Channel URL
            - 'upload_date': Upload date string (YYYYMMDD or ISO)
            - 'view_count': View count
    """
    if not query or not query.strip():
        return []

    ydl_opts: dict[str, Any] = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
    }
    if custom_ydl_opts:
        ydl_opts.update(custom_ydl_opts)

    search_term = f"ytsearch{max(1, max_results)}:{query.strip()}"
    candidates: list[dict[str, Any]] = []

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_term, download=False)
            if not info:
                return []

            entries = info.get("entries", [])
            for entry in entries:
                if not entry or not isinstance(entry, dict):
                    continue

                vid = entry.get("id") or extract_youtube_video_id(entry.get("url", ""))
                if not vid:
                    continue

                title = entry.get("title") or "Untitled Video"
                duration = entry.get("duration")
                channel = entry.get("channel") or entry.get("uploader") or ""
                channel_id = entry.get("channel_id") or entry.get("uploader_id")
                channel_url = entry.get("channel_url") or entry.get("uploader_url")

                candidates.append({
                    "id": vid,
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "duration": float(duration) if duration is not None else None,
                    "channel": channel,
                    "channel_id": channel_id,
                    "channel_url": channel_url,
                    "upload_date": entry.get("upload_date"),
                    "view_count": entry.get("view_count"),
                })

        return candidates
    except Exception as exc:
        logger.warning("YouTube search failed for query %r: %s", query, exc)
        return []


def get_youtube_video_info(
    url_or_id: str,
    custom_ydl_opts: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Extract YouTube video metadata and available subtitle tracks without downloading media.

    Args:
        url_or_id: YouTube watch URL, youtu.be URL, or raw video ID.
        custom_ydl_opts: Optional yt-dlp configuration dictionary.

    Returns:
        Dictionary of extracted video metadata.
    """
    video_id = extract_youtube_video_id(url_or_id)
    target_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url_or_id

    ydl_opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
    }
    if custom_ydl_opts:
        ydl_opts.update(custom_ydl_opts)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(target_url, download=False)
        return info or {}


def get_youtube_subtitles_metadata(
    url_or_id: str,
    custom_ydl_opts: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Inspect and extract available subtitle / closed-caption tracks for a YouTube video.

    Args:
        url_or_id: YouTube watch URL or raw video ID.
        custom_ydl_opts: Optional yt-dlp configuration dictionary.

    Returns:
        Dictionary with:
            - 'subtitles': Manual subtitle tracks dict {lang: [track_info]}
            - 'automatic_captions': Auto-generated caption tracks dict {lang: [track_info]}
            - 'manual_languages': List of manual subtitle language codes
            - 'auto_languages': List of auto-generated caption language codes
            - 'languages': Combined unique sorted list of all available languages
            - 'has_subtitles': Boolean True if any subtitles/captions exist
    """
    try:
        info = get_youtube_video_info(url_or_id, custom_ydl_opts=custom_ydl_opts)
        subtitles = info.get("subtitles") or {}
        automatic_captions = info.get("automatic_captions") or {}

        manual_langs = sorted(list(subtitles.keys()))
        auto_langs = sorted(list(automatic_captions.keys()))
        all_langs = sorted(list(set(manual_langs + auto_langs)))

        return {
            "subtitles": subtitles,
            "automatic_captions": automatic_captions,
            "manual_languages": manual_langs,
            "auto_languages": auto_langs,
            "languages": all_langs,
            "has_subtitles": bool(manual_langs or auto_langs),
        }
    except Exception as exc:
        logger.warning("Failed to extract subtitles metadata for %r: %s", url_or_id, exc)
        return {
            "subtitles": {},
            "automatic_captions": {},
            "manual_languages": [],
            "auto_languages": [],
            "languages": [],
            "has_subtitles": False,
        }


def youtube_video_to_metadata(
    url_or_info: Union[str, dict[str, Any]],
) -> EpisodeMetadata:
    """Convert a YouTube URL or yt-dlp extracted info dictionary into an EpisodeMetadata object.

    Args:
        url_or_info: YouTube URL string or pre-extracted info dictionary.

    Returns:
        EpisodeMetadata object with source_type='youtube'.
    """
    if isinstance(url_or_info, str):
        info = get_youtube_video_info(url_or_info)
    else:
        info = url_or_info

    vid = info.get("id") or extract_youtube_video_id(info.get("webpage_url", "")) or "unknown_yt"
    title = info.get("title") or "YouTube Video"
    channel = info.get("channel") or info.get("uploader") or "YouTube"
    channel_id = info.get("channel_id") or info.get("uploader_id")
    webpage_url = info.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
    duration = info.get("duration")
    duration_sec = float(duration) if duration is not None else None
    upload_date = info.get("upload_date")

    return EpisodeMetadata(
        show_title=channel,
        episode_title=title,
        episode_id=vid,
        show_id=channel_id or channel,
        audio_url=webpage_url,
        duration_seconds=duration_sec,
        published_date=upload_date,
        rss_transcripts=[],
        source_type="youtube",
    )
