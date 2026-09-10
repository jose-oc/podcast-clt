"""Markdown transcript exporter with YAML frontmatter and formatted timestamps."""

from __future__ import annotations

from typing import Optional
import yaml

from podcast_ctl.exporters.base import BaseExporter, format_duration, format_timestamp
from podcast_ctl.models.transcript import TranscriptResult


class MarkdownExporter(BaseExporter):
    """Exports transcripts to Markdown with YAML frontmatter and timestamped blocks."""

    format_name: str = "markdown"
    extension: str = "md"

    def __init__(
        self,
        group_by_speaker: bool = True,
        max_pause_seconds: float = 3.0,
    ) -> None:
        self.group_by_speaker = group_by_speaker
        self.max_pause_seconds = max_pause_seconds

    def export(self, result: TranscriptResult) -> str:
        """Generate Markdown document with YAML frontmatter and timestamped segments."""
        duration_val = result.metadata.duration_seconds
        if duration_val is None and result.segments:
            duration_val = max((seg.end for seg in result.segments), default=0.0)

        frontmatter_data = {
            "title": result.metadata.episode_title,
            "show": result.metadata.show_title,
            "duration": format_duration(duration_val),
            "published": result.metadata.published_date or "",
            "tier": str(result.tier_used),
        }

        yaml_str = yaml.safe_dump(frontmatter_data, sort_keys=False, allow_unicode=True)

        body = self._build_body(result)
        if body:
            return f"---\n{yaml_str}---\n\n# {result.metadata.episode_title}\n\n{body}\n"
        return f"---\n{yaml_str}---\n\n# {result.metadata.episode_title}\n"

    def _build_body(self, result: TranscriptResult) -> str:
        if not result.segments:
            return result.raw_text.strip()

        blocks: list[str] = []
        current_group: list[str] = []
        current_speaker: Optional[str] = None
        group_start: float = 0.0
        prev_end: float = 0.0

        for seg in result.segments:
            text = seg.text.strip()
            if not text:
                continue

            if not current_group:
                current_group = [text]
                current_speaker = seg.speaker
                group_start = seg.start
                prev_end = seg.end
            else:
                speaker_changed = (seg.speaker != current_speaker) if self.group_by_speaker else True
                pause_exceeded = (seg.start - prev_end) > self.max_pause_seconds

                if speaker_changed or pause_exceeded:
                    blocks.append(self._format_block(group_start, current_speaker, current_group))
                    current_group = [text]
                    current_speaker = seg.speaker
                    group_start = seg.start
                    prev_end = seg.end
                else:
                    current_group.append(text)
                    prev_end = seg.end

        if current_group:
            blocks.append(self._format_block(group_start, current_speaker, current_group))

        return "\n\n".join(blocks)

    def _format_block(self, start_seconds: float, speaker: Optional[str], text_parts: list[str]) -> str:
        ts = format_timestamp(start_seconds, always_include_hours=True)
        merged_text = " ".join(text_parts)
        if speaker and speaker.strip():
            return f"**[{ts}]** {speaker.strip()}: {merged_text}"
        return f"**[{ts}]** {merged_text}"
