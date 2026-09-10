"""Continuous prose transcript exporter with sentence smoothing and paragraph grouping."""

from __future__ import annotations

import re
from typing import Optional

from podcast_ctl.exporters.base import BaseExporter
from podcast_ctl.models.transcript import TranscriptResult


def normalize_sentence_text(text: str) -> str:
    """Normalize whitespace, punctuation spacing, and sentence capitalization."""
    if not text:
        return ""

    # Replace multiple whitespaces with single space
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""

    # Fix space before punctuation: "word , " -> "word, "
    cleaned = re.sub(r"\s+([,.:;?!])", r"\1", cleaned)

    # Fix missing space after punctuation if directly followed by a word character
    cleaned = re.sub(r"([,;:!?])([A-Za-z])", r"\1 \2", cleaned)
    cleaned = re.sub(r"(\.)([A-Za-z])", r"\1 \2", cleaned)

    # Capitalize start of text
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]

    # Capitalize after sentence endings (. ! ?)
    def capitalize_sentence(match: re.Match) -> str:
        punct = match.group(1)
        space = match.group(2)
        char = match.group(3)
        return f"{punct}{space}{char.upper()}"

    cleaned = re.sub(r"([.!?])(\s+)([a-z])", capitalize_sentence, cleaned)

    return cleaned


def _join_segment_texts(parts: list[str]) -> str:
    raw = " ".join(p.strip() for p in parts if p.strip())
    return normalize_sentence_text(raw)


class ProseExporter(BaseExporter):
    """Exports transcripts into continuous, readable paragraphs without timestamps."""

    format_name: str = "prose"
    extension: str = "txt"

    def __init__(
        self,
        include_speakers: bool = True,
        max_pause_seconds: float = 3.0,
    ) -> None:
        self.include_speakers = include_speakers
        self.max_pause_seconds = max_pause_seconds

    def export(self, result: TranscriptResult) -> str:
        """Export transcript to continuous prose text."""
        if not result.segments:
            if not result.raw_text:
                return ""
            paragraphs = [
                normalize_sentence_text(p)
                for p in result.raw_text.split("\n\n")
                if p.strip()
            ]
            return "\n\n".join(paragraphs) + "\n" if paragraphs else ""

        paragraphs: list[str] = []
        current_group: list[str] = []
        current_speaker: Optional[str] = None
        prev_end: float = 0.0

        for seg in result.segments:
            text = seg.text.strip()
            if not text:
                continue

            if not current_group:
                current_group = [text]
                current_speaker = seg.speaker
                prev_end = seg.end
            else:
                speaker_changed = seg.speaker != current_speaker
                pause_exceeded = (seg.start - prev_end) > self.max_pause_seconds

                if speaker_changed or pause_exceeded:
                    p_text = self._format_paragraph(current_speaker, current_group)
                    if p_text:
                        paragraphs.append(p_text)
                    current_group = [text]
                    current_speaker = seg.speaker
                    prev_end = seg.end
                else:
                    current_group.append(text)
                    prev_end = seg.end

        if current_group:
            p_text = self._format_paragraph(current_speaker, current_group)
            if p_text:
                paragraphs.append(p_text)

        if not paragraphs:
            return ""
        return "\n\n".join(paragraphs) + "\n"

    def _format_paragraph(self, speaker: Optional[str], text_parts: list[str]) -> str:
        smoothed = _join_segment_texts(text_parts)
        if not smoothed:
            return ""
        if self.include_speakers and speaker and speaker.strip():
            return f"{speaker.strip()}: {smoothed}"
        return smoothed
