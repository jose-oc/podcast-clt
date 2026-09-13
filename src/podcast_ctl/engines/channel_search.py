"""YouTube channel search fallback for the Tier 2 engine.

When no explicit Episode -> YouTube Video mapping exists but the show has a
Show -> YouTube Channel mapping, the recent videos of that channel are listed
(flat yt-dlp extraction, no download) and matched against the episode title.

Matching heuristic: both titles are normalized (lowercased, punctuation
stripped, whitespace collapsed) and compared with difflib.SequenceMatcher. A
video is accepted when its similarity ratio is >= the threshold (default 0.75).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import yt_dlp

logger = logging.getLogger(__name__)

DEFAULT_MAX_VIDEOS = 60
DEFAULT_SIMILARITY_THRESHOLD = 0.75


@dataclass
class ChannelSearchResult:
    """Outcome of searching a YouTube channel for an episode's video."""

    video_url: str | None = None
    matched_title: str | None = None
    similarity: float = 0.0
    videos_searched: int = 0
    best_similarity: float = 0.0


def normalize_title(title: str) -> str:
    """Normalize a title for comparison: lowercase, punctuation stripped, whitespace collapsed."""
    normalized = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def title_similarity(title_a: str, title_b: str) -> float:
    """Similarity ratio (0.0-1.0) between two titles after normalization."""
    norm_a = normalize_title(title_a)
    norm_b = normalize_title(title_b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    return SequenceMatcher(None, norm_a, norm_b).ratio()


def _channel_videos_url(channel_url: str) -> str:
    """Build the /videos URL for a channel URL or handle."""
    base = channel_url.rstrip("/")
    if base.endswith("/videos"):
        return base
    return f"{base}/videos"


def search_channel_for_episode(
    channel_url: str,
    episode_title: str,
    max_videos: int = DEFAULT_MAX_VIDEOS,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> ChannelSearchResult:
    """Search a channel's recent videos for one whose title closely matches the episode title.

    Only the most recent ``max_videos`` videos are compared (flat extraction,
    no downloads). The best candidate is accepted only when its similarity
    ratio reaches ``threshold``.

    Args:
        channel_url: YouTube channel URL or handle (e.g. https://www.youtube.com/@hubermanlab).
        episode_title: Episode title from the RSS feed to match.
        max_videos: Maximum number of recent channel videos to compare.
        threshold: Minimum similarity ratio required to accept a match.

    Returns:
        ChannelSearchResult with the matched video URL (or None) and diagnostics.
    """
    ydl_opts = {
        "extract_flat": True,
        "playlistend": max_videos,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(_channel_videos_url(channel_url), download=False) or {}

    entries = info.get("entries") or []
    videos = [entry for entry in entries if entry and entry.get("id") and entry.get("title")]

    best_entry: dict | None = None
    best_score = 0.0
    for entry in videos:
        score = title_similarity(episode_title, str(entry["title"]))
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry is not None and best_score >= threshold:
        video_id = str(best_entry["id"])
        entry_url = str(best_entry.get("url") or "")
        video_url = entry_url if entry_url.startswith("http") else f"https://www.youtube.com/watch?v={video_id}"
        logger.info(
            "Channel search matched episode '%s' to '%s' (similarity %.2f)",
            episode_title,
            best_entry["title"],
            best_score,
        )
        return ChannelSearchResult(
            video_url=video_url,
            matched_title=str(best_entry["title"]),
            similarity=best_score,
            videos_searched=len(videos),
            best_similarity=best_score,
        )

    logger.info(
        "Channel search found no close match for '%s' (%d videos searched, best similarity %.2f)",
        episode_title,
        len(videos),
        best_score,
    )
    return ChannelSearchResult(
        videos_searched=len(videos),
        best_similarity=best_score,
    )
