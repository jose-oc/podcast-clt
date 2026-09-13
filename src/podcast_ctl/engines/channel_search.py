"""YouTube channel search fallback for the Tier 2 engine.

When no explicit Episode -> YouTube Video mapping exists but the show has a
Show -> YouTube Channel mapping, the videos of that channel are listed (flat
yt-dlp extraction, no download) and matched against the episode title.

Matching heuristic: both titles are normalized (lowercased, punctuation
stripped, whitespace collapsed) and compared with difflib.SequenceMatcher. A
video is accepted when its similarity ratio is >= the threshold (default 0.75).

For whole-catalog matching (e.g. 'podcast-ctl mapping sync'), list the channel
once with :func:`list_channel_videos` and match every episode locally with
:func:`match_episode_to_videos`, so each episode does not cost a new request.
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
class ChannelVideo:
    """One video of a YouTube channel listing (flat extraction)."""

    video_id: str
    title: str

    @property
    def url(self) -> str:
        """Canonical watch URL for the video."""
        return f"https://www.youtube.com/watch?v={self.video_id}"


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


def list_channel_videos(channel_url: str, max_videos: int | None = None) -> list[ChannelVideo]:
    """List a channel's videos with flat yt-dlp extraction (no downloads).

    Args:
        channel_url: YouTube channel URL or handle (e.g. https://www.youtube.com/@hubermanlab).
        max_videos: Maximum number of recent videos to list, or None for the
            full catalog. Full catalogs of large channels can take a while.

    Returns:
        List of ChannelVideo (id + title), most recent first.
    """
    ydl_opts: dict = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }
    if max_videos is not None:
        ydl_opts["playlistend"] = max_videos
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(_channel_videos_url(channel_url), download=False) or {}

    entries = info.get("entries") or []
    return [
        ChannelVideo(video_id=str(entry["id"]), title=str(entry["title"]))
        for entry in entries
        if entry and entry.get("id") and entry.get("title")
    ]


def match_episode_to_videos(
    episode_title: str,
    videos: list[ChannelVideo],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> ChannelSearchResult:
    """Match one episode title against an already-listed channel catalog.

    The best candidate is accepted only when its similarity ratio reaches
    ``threshold``.
    """
    best_video: ChannelVideo | None = None
    best_score = 0.0
    for video in videos:
        score = title_similarity(episode_title, video.title)
        if score > best_score:
            best_score = score
            best_video = video

    if best_video is not None and best_score >= threshold:
        logger.info(
            "Channel search matched episode '%s' to '%s' (similarity %.2f)",
            episode_title,
            best_video.title,
            best_score,
        )
        return ChannelSearchResult(
            video_url=best_video.url,
            matched_title=best_video.title,
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
    videos = list_channel_videos(channel_url, max_videos=max_videos)
    return match_episode_to_videos(episode_title, videos, threshold=threshold)
