"""Tier 1: RSS Transcript Engine.

Downloads and parses Podcasting 2.0 transcript tags from RSS feeds (JSON, VTT, SRT, TXT).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
import httpx

from podcast_ctl.engines.base import (
    BaseTranscriptionEngine,
    TranscriptNotFoundError,
    TranscriptionEngineError,
)
from podcast_ctl.models.transcript import (
    EpisodeMetadata,
    TranscriptResult,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)


def parse_timestamp_seconds(ts_str: str) -> float:
    """Convert timestamp string (hh:mm:ss.mmm, mm:ss.mmm, or float string) to seconds.

    Supports both comma (SRT) and period (VTT) decimal separators.
    """
    ts_str = ts_str.strip().replace(",", ".")
    try:
        return float(ts_str)
    except ValueError:
        pass

    parts = ts_str.split(":")
    if len(parts) == 3:
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        return round(hours * 3600 + minutes * 60 + seconds, 3)
    elif len(parts) == 2:
        minutes = float(parts[0])
        seconds = float(parts[1])
        return round(minutes * 60 + seconds, 3)
    elif len(parts) == 1:
        return round(float(parts[0]), 3)
    else:
        raise ValueError(f"Unrecognized timestamp format: '{ts_str}'")


def clean_vtt_text(text: str, is_plain_text: bool = False) -> tuple[str, Optional[str]]:
    """Clean WebVTT cue text, extracting speaker tags if present.

    Handles:
    - `<v Speaker Name>Text` or `<v.class Speaker Name>Text`
    - `[Speaker] Text` or `[Speaker]: Text`
    - `(Speaker): Text`
    - `Speaker: Text`
    - Strips remaining HTML/VTT tags like `<b>`, `<i>`, `<c.color>`, `</v>`, etc.
    """
    speaker: Optional[str] = None

    # Check for <v ...> speaker tag
    v_match = re.match(r"<\s*v(?:\.[^>]+)?\s+([^>]+)>(.*)$", text, re.DOTALL | re.IGNORECASE)
    if v_match:
        speaker = v_match.group(1).strip()
        text = v_match.group(2)
    elif not is_plain_text:
        # Check for [Speaker] or [Speaker]:
        bracket_match = re.match(r"^\[([A-Za-z0-9_\- ]{1,30})\]\s*:?\s*(.*)$", text, re.DOTALL)
        if bracket_match:
            cand = bracket_match.group(1).strip()
            if not cand.isdigit() and len(cand) > 1:
                speaker = cand
                text = bracket_match.group(2)

        if not speaker:
            # Check for (Speaker): or (Speaker)
            paren_match = re.match(r"^\(([A-Za-z0-9_\- ]{1,30})\)\s*:\s*(.*)$", text, re.DOTALL)
            if paren_match:
                cand = paren_match.group(1).strip()
                if not cand.isdigit() and len(cand) > 1:
                    speaker = cand
                    text = paren_match.group(2)

        if not speaker:
            # Check for Speaker: at the start
            colon_match = re.match(r"^([A-Za-z][A-Za-z0-9_\- ]{1,25})\s*:\s*(.*)$", text, re.DOTALL)
            if colon_match:
                cand = colon_match.group(1).strip()
                cand_lower = cand.lower()
                ignored_prefixes = ("http", "https", "note", "chapter", "paragraph", "part", "section", "scene", "time")
                if not cand.isdigit() and not cand_lower.startswith(ignored_prefixes):
                    speaker = cand
                    text = colon_match.group(2)

    # Strip remaining HTML/VTT tags
    cleaned = re.sub(r"<[^>]+>", "", text).strip()
    return cleaned, speaker


def parse_vtt_content(content: str) -> list[TranscriptSegment]:
    """Parse WebVTT content into a list of TranscriptSegments."""
    lines = content.splitlines()
    segments: list[TranscriptSegment] = []

    # Regex for timestamp line: 00:00:00.000 --> 00:00:05.000 [positioning info]
    ts_pattern = re.compile(
        r"^((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3}|\d{2}[\.,]\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3}|\d{2}[\.,]\d{3})"
    )

    i = 0
    num_lines = len(lines)

    while i < num_lines:
        line = lines[i].strip()

        # Skip headers, notes, styles, regions, and blank lines
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("STYLE") or line.startswith("REGION"):
            i += 1
            continue

        ts_match = ts_pattern.search(line)
        if ts_match:
            start_str = ts_match.group(1)
            end_str = ts_match.group(2)
            try:
                start_sec = parse_timestamp_seconds(start_str)
                end_sec = parse_timestamp_seconds(end_str)
            except ValueError:
                i += 1
                continue

            # Collect following text lines until empty line or next timestamp
            text_lines: list[str] = []
            i += 1
            while i < num_lines:
                curr_line = lines[i].strip()
                if not curr_line or ts_pattern.search(curr_line):
                    break
                text_lines.append(curr_line)
                i += 1

            raw_text_block = " ".join(text_lines)
            cleaned_text, speaker = clean_vtt_text(raw_text_block)
            if cleaned_text:
                segments.append(
                    TranscriptSegment(
                        start=start_sec,
                        end=end_sec,
                        text=cleaned_text,
                        speaker=speaker,
                    )
                )
        else:
            i += 1

    return segments


def parse_srt_content(content: str) -> list[TranscriptSegment]:
    """Parse SubRip (.srt) subtitle content into a list of TranscriptSegments."""
    # Split by double newlines or cue blocks
    blocks = re.split(r"\n\s*\n", content.strip())
    segments: list[TranscriptSegment] = []

    ts_pattern = re.compile(
        r"((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})"
    )

    for block in blocks:
        block_lines = [b.strip() for b in block.splitlines() if b.strip()]
        if not block_lines:
            continue

        # Find timestamp line in block
        ts_index = -1
        ts_match = None
        for idx, bline in enumerate(block_lines):
            match = ts_pattern.search(bline)
            if match:
                ts_index = idx
                ts_match = match
                break

        if ts_match and ts_index != -1:
            try:
                start_sec = parse_timestamp_seconds(ts_match.group(1))
                end_sec = parse_timestamp_seconds(ts_match.group(2))
            except ValueError:
                continue

            text_lines = block_lines[ts_index + 1:]
            raw_text_block = " ".join(text_lines)
            cleaned_text, speaker = clean_vtt_text(raw_text_block)
            if cleaned_text:
                segments.append(
                    TranscriptSegment(
                        start=start_sec,
                        end=end_sec,
                        text=cleaned_text,
                        speaker=speaker,
                    )
                )

    return segments


def parse_json_transcript(content: str | dict[str, Any] | list[Any]) -> list[TranscriptSegment]:
    """Parse Podcasting 2.0 / standard JSON transcript into a list of TranscriptSegments."""
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise TranscriptionEngineError(f"Invalid JSON transcript: {exc}") from exc
    else:
        data = content

    raw_segments: list[dict[str, Any]] = []

    if isinstance(data, list):
        raw_segments = data
    elif isinstance(data, dict):
        if "segments" in data and isinstance(data["segments"], list):
            raw_segments = data["segments"]
        elif "words" in data and isinstance(data["words"], list):
            raw_segments = data["words"]
        elif "transcript" in data and isinstance(data["transcript"], list):
            raw_segments = data["transcript"]
        else:
            # Fallback: maybe single text property
            text = data.get("text") or data.get("body") or data.get("transcript")
            if text and isinstance(text, str):
                return [TranscriptSegment(start=0.0, end=0.0, text=text.strip())]
            return []

    segments: list[TranscriptSegment] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue

        # Start time resolution
        start_val = item.get("startTime") or item.get("start") or item.get("start_time") or 0.0
        if isinstance(start_val, str):
            try:
                start_sec = parse_timestamp_seconds(start_val)
            except ValueError:
                start_sec = 0.0
        else:
            start_sec = float(start_val)

        # End time resolution
        end_val = item.get("endTime") or item.get("end") or item.get("end_time")
        if end_val is not None:
            if isinstance(end_val, str):
                try:
                    end_sec = parse_timestamp_seconds(end_val)
                except ValueError:
                    end_sec = start_sec
            else:
                end_sec = float(end_val)
        else:
            duration = item.get("duration") or item.get("duration_seconds") or 0.0
            end_sec = start_sec + float(duration)

        text_val = (
            item.get("body")
            or item.get("text")
            or item.get("word")
            or item.get("content")
            or ""
        )
        speaker_val = item.get("speaker") or item.get("speaker_name") or item.get("speakerId")
        confidence_val = item.get("confidence") or item.get("score")

        cleaned_text, cue_speaker = clean_vtt_text(str(text_val))
        effective_speaker = str(speaker_val).strip() if speaker_val else cue_speaker

        if cleaned_text:
            segments.append(
                TranscriptSegment(
                    start=round(start_sec, 3),
                    end=round(max(start_sec, end_sec), 3),
                    text=cleaned_text,
                    speaker=effective_speaker,
                    confidence=float(confidence_val) if confidence_val is not None else None,
                )
            )

    return segments


def parse_plain_text(content: str, default_duration: Optional[float] = None) -> list[TranscriptSegment]:
    """Parse plain text into segments by splitting paragraphs."""
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not paragraphs:
        if content.strip():
            paragraphs = [content.strip()]
        else:
            return []

    duration = default_duration or 0.0
    seg_duration = duration / len(paragraphs) if duration > 0 else 0.0

    segments: list[TranscriptSegment] = []
    for i, para in enumerate(paragraphs):
        start = round(i * seg_duration, 3)
        end = round((i + 1) * seg_duration, 3)
        cleaned_text, speaker = clean_vtt_text(para, is_plain_text=True)
        segments.append(
            TranscriptSegment(
                start=start,
                end=end,
                text=cleaned_text,
                speaker=speaker,
            )
        )

    return segments


def transcript_type_priority(item: dict[str, Any]) -> int:
    """Determine sorting rank for RSS transcript candidates.

    Lower integer = higher priority.
    Order: JSON (1) > VTT (2) > SRT (3) > Plain text (4) > Other (5).
    """
    mime_type = str(item.get("type", "")).lower()
    url = str(item.get("url", "")).lower()

    if "json" in mime_type or url.endswith(".json"):
        return 1
    elif "vtt" in mime_type or url.endswith(".vtt"):
        return 2
    elif "srt" in mime_type or "subrip" in mime_type or url.endswith(".srt"):
        return 3
    elif "plain" in mime_type or "text" in mime_type or url.endswith(".txt"):
        return 4
    return 5


class RSSTranscriptionEngine(BaseTranscriptionEngine):
    """Tier 1: Downloads and parses transcripts provided directly in RSS feeds."""

    name: str = "rss"
    tier: str = "rss"

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def is_available(self) -> bool:
        """RSS engine is always available as it only requires standard HTTP networking."""
        return True

    def parse_content_by_type(
        self, content: str, mime_type: str, url: str, default_duration: Optional[float] = None
    ) -> list[TranscriptSegment]:
        """Route content to appropriate parser based on MIME type or URL extension."""
        mime = mime_type.lower()
        url_lower = url.lower()

        if "json" in mime or url_lower.endswith(".json"):
            return parse_json_transcript(content)
        elif "vtt" in mime or url_lower.endswith(".vtt") or content.lstrip().startswith("WEBVTT"):
            return parse_vtt_content(content)
        elif "srt" in mime or "subrip" in mime or url_lower.endswith(".srt"):
            return parse_srt_content(content)
        elif "plain" in mime or url_lower.endswith(".txt"):
            return parse_plain_text(content, default_duration=default_duration)

        # Heuristic fallback: check content signature
        if content.lstrip().startswith("WEBVTT"):
            return parse_vtt_content(content)
        elif "-->" in content:
            return parse_srt_content(content)
        elif content.lstrip().startswith("{") or content.lstrip().startswith("["):
            try:
                return parse_json_transcript(content)
            except Exception:
                pass

        return parse_plain_text(content, default_duration=default_duration)

    async def transcribe(
        self,
        episode: EpisodeMetadata,
        client: Optional[httpx.AsyncClient] = None,
        **kwargs: Any,
    ) -> TranscriptResult:
        """Download and parse RSS transcript for given episode."""
        if not episode.rss_transcripts:
            raise TranscriptNotFoundError(
                f"No RSS transcripts available in episode metadata for '{episode.episode_title}'."
            )

        # Sort available transcripts by priority
        sorted_candidates = sorted(episode.rss_transcripts, key=transcript_type_priority)

        errors: list[str] = []

        async def _download_and_parse(http_client: httpx.AsyncClient) -> TranscriptResult:
            for item in sorted_candidates:
                url = item.get("url")
                if not url:
                    continue
                mime_type = item.get("type", "")

                try:
                    logger.debug(f"Fetching RSS transcript from {url} (type: {mime_type})")
                    resp = await http_client.get(url)
                    resp.raise_for_status()
                    content = resp.text

                    segments = self.parse_content_by_type(
                        content=content,
                        mime_type=mime_type,
                        url=url,
                        default_duration=episode.duration_seconds,
                    )

                    if segments:
                        return TranscriptResult(
                            metadata=episode,
                            segments=segments,
                            tier_used="rss",
                        )
                    else:
                        errors.append(f"Parsed 0 segments from transcript URL: {url}")
                except Exception as exc:
                    logger.warning(f"Failed to fetch/parse RSS transcript from {url}: {exc}")
                    errors.append(f"{url}: {exc}")

            raise TranscriptNotFoundError(
                f"Could not retrieve valid RSS transcript for '{episode.episode_title}'. Errors: {'; '.join(errors)}"
            )

        if client is not None:
            return await _download_and_parse(client)
        else:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as http_client:
                return await _download_and_parse(http_client)
