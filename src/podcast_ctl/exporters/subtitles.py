"""Subtitle exporters for standard SubRip (SRT) and WebVTT formats."""

from __future__ import annotations

from podcast_ctl.exporters.base import BaseExporter, format_timestamp
from podcast_ctl.models.transcript import TranscriptResult, TranscriptSegment


class SrtExporter(BaseExporter):
    """Exports transcripts to standard SubRip (.srt) subtitle format."""

    format_name: str = "srt"
    extension: str = "srt"

    def __init__(self, include_speakers: bool = True) -> None:
        self.include_speakers = include_speakers

    def export(self, result: TranscriptResult) -> str:
        """Export transcript to SRT formatted string."""
        segments = [s for s in result.segments if s.text.strip()]
        if not segments:
            if result.raw_text.strip():
                # Fallback single block
                duration = result.metadata.duration_seconds or 0.0
                ts_start = format_timestamp(0.0, always_include_hours=True, decimal_separator=",")
                ts_end = format_timestamp(duration, always_include_hours=True, decimal_separator=",")
                return f"1\n{ts_start} --> {ts_end}\n{result.raw_text.strip()}\n\n"
            return ""

        blocks: list[str] = []
        for index, seg in enumerate(segments, start=1):
            ts_start = format_timestamp(seg.start, always_include_hours=True, decimal_separator=",")
            ts_end = format_timestamp(seg.end, always_include_hours=True, decimal_separator=",")
            text = self._format_text(seg)
            blocks.append(f"{index}\n{ts_start} --> {ts_end}\n{text}")

        return "\n\n".join(blocks) + "\n\n"

    def _format_text(self, seg: TranscriptSegment) -> str:
        text = seg.text.strip()
        if self.include_speakers and seg.speaker and seg.speaker.strip():
            return f"{seg.speaker.strip()}: {text}"
        return text


class VttExporter(BaseExporter):
    """Exports transcripts to standard WebVTT (.vtt) subtitle format."""

    format_name: str = "vtt"
    extension: str = "vtt"

    def __init__(self, include_speakers: bool = True) -> None:
        self.include_speakers = include_speakers

    def export(self, result: TranscriptResult) -> str:
        """Export transcript to WebVTT formatted string."""
        segments = [s for s in result.segments if s.text.strip()]
        if not segments:
            if result.raw_text.strip():
                duration = result.metadata.duration_seconds or 0.0
                ts_start = format_timestamp(0.0, always_include_hours=True, decimal_separator=".")
                ts_end = format_timestamp(duration, always_include_hours=True, decimal_separator=".")
                return f"WEBVTT\n\n{ts_start} --> {ts_end}\n{result.raw_text.strip()}\n\n"
            return "WEBVTT\n\n"

        blocks: list[str] = ["WEBVTT"]
        for seg in segments:
            ts_start = format_timestamp(seg.start, always_include_hours=True, decimal_separator=".")
            ts_end = format_timestamp(seg.end, always_include_hours=True, decimal_separator=".")
            text = self._format_text(seg)
            blocks.append(f"{ts_start} --> {ts_end}\n{text}")

        return "\n\n".join(blocks) + "\n\n"

    def _format_text(self, seg: TranscriptSegment) -> str:
        text = seg.text.strip()
        if self.include_speakers and seg.speaker and seg.speaker.strip():
            return f"{seg.speaker.strip()}: {text}"
        return text
