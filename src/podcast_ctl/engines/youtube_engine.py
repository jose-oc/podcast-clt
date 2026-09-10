"""Tier 2: YouTube Subtitle Engine.

Extracts native and auto-generated timed captions from YouTube using
`youtube-transcript-api` and/or `yt-dlp`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from podcast_ctl.engines.base import (
    BaseTranscriptionEngine,
    EngineUnavailableError,
    TranscriptNotFoundError,
)
from podcast_ctl.engines.rss_engine import clean_vtt_text, parse_json_transcript, parse_vtt_content
from podcast_ctl.models.transcript import (
    EpisodeMetadata,
    TranscriptResult,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

YOUTUBE_ID_PATTERNS = [
    re.compile(r"(?:v=|\/embed\/|\/shorts\/|\/v\/|^youtu\.be\/|youtu\.be\/)([0-9A-Za-z_-]{11})(?:\?|&|\/|$)"),
    re.compile(r"^([0-9A-Za-z_-]{11})$"),
]


def extract_youtube_video_id(url_or_id: str | None) -> str | None:
    """Extract an 11-character YouTube video ID from a URL or raw ID string."""
    if not url_or_id:
        return None
    url_or_id = url_or_id.strip()

    for pattern in YOUTUBE_ID_PATTERNS:
        match = pattern.search(url_or_id)
        if match:
            return match.group(1)
    return None


class YouTubeTranscriptionEngine(BaseTranscriptionEngine):
    """Tier 2: Subtitle extractor for YouTube videos."""

    name: str = "youtube"
    tier: str = "youtube"

    def __init__(self, preferred_languages: list[str] | None = None) -> None:
        self.preferred_languages = preferred_languages or ["en", "en-US", "en-GB"]

    def is_available(self) -> bool:
        """Checks if either youtube_transcript_api or yt_dlp is installed."""
        try:
            import youtube_transcript_api  # noqa: F401
            return True
        except ImportError:
            pass

        try:
            import yt_dlp  # noqa: F401
            return True
        except ImportError:
            return False

    def resolve_video_id(self, episode: EpisodeMetadata, kwargs: dict[str, Any]) -> str | None:
        """Find the YouTube video ID from kwargs or episode metadata."""
        # 1. Explicit in kwargs
        if kwargs.get("video_id"):
            vid = extract_youtube_video_id(str(kwargs["video_id"]))
            if vid:
                return vid

        if kwargs.get("youtube_url"):
            vid = extract_youtube_video_id(str(kwargs["youtube_url"]))
            if vid:
                return vid

        # 2. Episode audio_url or episode_id
        if episode.audio_url:
            vid = extract_youtube_video_id(episode.audio_url)
            if vid:
                return vid

        if episode.episode_id:
            vid = extract_youtube_video_id(episode.episode_id)
            if vid:
                return vid

        return None

    def _fetch_via_youtube_transcript_api(
        self, video_id: str, languages: list[str]
    ) -> list[TranscriptSegment]:
        """Extract captions using the youtube_transcript_api library.

        Supports youtube-transcript-api >= 1.0 (instance-based client whose
        fetched snippets expose ``start``/``duration``/``text`` attributes).
        """
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as exc:
            raise EngineUnavailableError("youtube-transcript-api is not installed.") from exc

        transcript_list = YouTubeTranscriptApi().list(video_id)

        transcript = None
        # 1. Try manual subtitles in preferred languages
        try:
            transcript = transcript_list.find_manually_created_transcript(languages)
        except Exception:
            pass

        # 2. Fall back to auto-generated subtitles in preferred languages
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(languages)
            except Exception:
                pass

        # 3. Fall back to any available transcript
        if transcript is None:
            try:
                transcript = next(iter(transcript_list))
            except StopIteration:
                raise TranscriptNotFoundError(
                    f"No transcripts found for YouTube video {video_id}."
                ) from None

        raw_items = transcript.fetch()
        segments: list[TranscriptSegment] = []

        for item in raw_items:
            start = round(float(item.start), 3)
            duration = float(item.duration)
            end = round(start + duration, 3)
            text, speaker = clean_vtt_text(str(item.text))
            if text:
                segments.append(
                    TranscriptSegment(
                        start=start,
                        end=max(start, end),
                        text=text,
                        speaker=speaker,
                    )
                )

        return segments

    async def _fetch_via_ytdlp(
        self, video_id: str, languages: list[str]
    ) -> list[TranscriptSegment]:
        """Extract captions using yt-dlp metadata extraction."""
        try:
            import yt_dlp
        except ImportError as exc:
            raise EngineUnavailableError("yt-dlp is not installed.") from exc

        url = f"https://www.youtube.com/watch?v={video_id}"

        def _extract() -> dict[str, Any]:
            ydl_opts = {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False) or {}

        info = await asyncio.to_thread(_extract)
        subtitles = info.get("subtitles") or {}
        auto_captions = info.get("automatic_captions") or {}

        # Look for subtitle URL
        target_sub_url: str | None = None
        target_ext: str = "json3"

        for lang in languages:
            # Check manual first
            if lang in subtitles:
                for sub in subtitles[lang]:
                    ext = sub.get("ext", "")
                    if ext in ("json3", "vtt", "srv1", "ttml"):
                        target_sub_url = sub.get("url")
                        target_ext = ext
                        break
            if target_sub_url:
                break

            # Check auto next
            if lang in auto_captions:
                for sub in auto_captions[lang]:
                    ext = sub.get("ext", "")
                    if ext in ("json3", "vtt", "srv1", "ttml"):
                        target_sub_url = sub.get("url")
                        target_ext = ext
                        break
            if target_sub_url:
                break

        if not target_sub_url:
            # Check any available subtitle
            all_subs = {**subtitles, **auto_captions}
            for _lang, sub_list in all_subs.items():
                for sub in sub_list:
                    if sub.get("url"):
                        target_sub_url = sub.get("url")
                        target_ext = sub.get("ext", "vtt")
                        break
                if target_sub_url:
                    break

        if not target_sub_url:
            raise TranscriptNotFoundError(f"yt-dlp found no subtitles for YouTube video {video_id}.")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(target_sub_url)
            resp.raise_for_status()
            sub_content = resp.text

        if target_ext == "vtt" or sub_content.lstrip().startswith("WEBVTT"):
            return parse_vtt_content(sub_content)
        elif target_ext == "json3" or sub_content.lstrip().startswith("{"):
            # yt-dlp json3 format: {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "..."}]}]}
            import json
            try:
                j_data = json.loads(sub_content)
                segments: list[TranscriptSegment] = []
                for event in j_data.get("events", []):
                    start_ms = event.get("tStartMs", 0)
                    dur_ms = event.get("dDurationMs", 0)
                    start = round(start_ms / 1000.0, 3)
                    end = round((start_ms + dur_ms) / 1000.0, 3)
                    text_parts = [seg.get("utf8", "") for seg in event.get("segs", []) if seg.get("utf8")]
                    text = "".join(text_parts).strip()
                    cleaned_text, speaker = clean_vtt_text(text)
                    if cleaned_text and cleaned_text != "\n":
                        segments.append(
                            TranscriptSegment(
                                start=start,
                                end=max(start, end),
                                text=cleaned_text,
                                speaker=speaker,
                            )
                        )
                if segments:
                    return segments
            except Exception:
                pass
            return parse_json_transcript(sub_content)

        return parse_vtt_content(sub_content)

    async def transcribe(
        self,
        episode: EpisodeMetadata,
        **kwargs: Any,
    ) -> TranscriptResult:
        """Extract YouTube subtitles for the episode."""
        video_id = self.resolve_video_id(episode, kwargs)
        if not video_id:
            raise TranscriptNotFoundError(
                f"No YouTube video ID could be resolved for episode '{episode.episode_title}'."
            )

        languages = kwargs.get("languages") or self.preferred_languages
        errors: list[str] = []

        # 1. Try youtube_transcript_api
        try:
            segments = await asyncio.to_thread(
                self._fetch_via_youtube_transcript_api, video_id, languages
            )
            if segments:
                return TranscriptResult(
                    metadata=episode,
                    segments=segments,
                    tier_used="youtube",
                )
        except Exception as exc:
            logger.debug(f"youtube_transcript_api failed for {video_id}: {exc}")
            errors.append(f"youtube-transcript-api: {exc}")

        # 2. Try yt-dlp fallback
        try:
            segments = await self._fetch_via_ytdlp(video_id, languages)
            if segments:
                return TranscriptResult(
                    metadata=episode,
                    segments=segments,
                    tier_used="youtube",
                )
        except Exception as exc:
            logger.debug(f"yt-dlp caption extraction failed for {video_id}: {exc}")
            errors.append(f"yt-dlp: {exc}")

        raise TranscriptNotFoundError(
            f"Failed to fetch YouTube subtitles for video ID '{video_id}'. Errors: {'; '.join(errors)}"
        )
