"""Export manager coordinating multi-format exports and filesystem path generation."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Optional, Union
import unicodedata

from podcast_ctl.exporters.base import BaseExporter
from podcast_ctl.exporters.json_exporter import JsonExporter
from podcast_ctl.exporters.markdown import MarkdownExporter
from podcast_ctl.exporters.prose import ProseExporter
from podcast_ctl.exporters.subtitles import SrtExporter, VttExporter
from podcast_ctl.models.transcript import TranscriptResult

FORMAT_ALIASES: dict[str, list[str]] = {
    "both": ["markdown", "prose"],
    "all": ["markdown", "prose", "srt", "vtt", "json"],
    "md": ["markdown"],
    "txt": ["prose"],
}


def slugify(value: str, fallback: str = "untitled") -> str:
    """Convert a string into a clean, filesystem-safe slug."""
    if not value:
        return fallback
    normalized = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    lowered = normalized.lower()
    slug = re.sub(r"[^\w\s-]", "", lowered)
    slug = re.sub(r"[-\s]+", "-", slug).strip("-_")
    return slug if slug else fallback


class ExportManager:
    """Manages transcript exporters, format aliases, and templated file saving."""

    def __init__(self) -> None:
        self._exporters: dict[str, BaseExporter] = {
            "markdown": MarkdownExporter(),
            "prose": ProseExporter(),
            "srt": SrtExporter(),
            "vtt": VttExporter(),
            "json": JsonExporter(),
        }

    @property
    def available_formats(self) -> list[str]:
        """List of supported format identifiers."""
        return sorted(self._exporters.keys())

    def register_exporter(self, format_name: str, exporter: BaseExporter) -> None:
        """Register or override an exporter for a given format name."""
        self._exporters[format_name.lower().strip()] = exporter

    def get_exporter(self, format_name: str) -> BaseExporter:
        """Retrieve exporter instance by format name."""
        norm = format_name.lower().strip()
        if norm in FORMAT_ALIASES and len(FORMAT_ALIASES[norm]) == 1:
            norm = FORMAT_ALIASES[norm][0]

        if norm in self._exporters:
            return self._exporters[norm]

        raise ValueError(
            f"Unsupported export format: '{format_name}'. "
            f"Available formats: {', '.join(sorted(self._exporters.keys()))}"
        )

    def resolve_formats(self, formats: Union[list[str], str]) -> list[str]:
        """Expand format aliases and list into unique normalized format names."""
        if isinstance(formats, str):
            raw_items = [f.strip() for f in formats.split(",") if f.strip()]
        else:
            raw_items = [f.strip() for f in formats if f.strip()]

        resolved: list[str] = []
        for item in raw_items:
            key = item.lower()
            if key in FORMAT_ALIASES:
                for sub_fmt in FORMAT_ALIASES[key]:
                    if sub_fmt not in resolved:
                        resolved.append(sub_fmt)
            else:
                if key not in resolved:
                    resolved.append(key)

        for fmt in resolved:
            self.get_exporter(fmt)

        return resolved

    def get_output_path(
        self,
        result: TranscriptResult,
        output_dir: Union[str, Path],
        format_name: str,
        template: Optional[str] = None,
    ) -> Path:
        """Generate output path based on metadata and output template."""
        exporter = self.get_exporter(format_name)
        out_base = Path(output_dir).expanduser().resolve()

        show_slug = slugify(result.metadata.show_title, fallback="show")
        episode_slug = slugify(result.metadata.episode_title, fallback="episode")
        ext = exporter.extension

        if template:
            formatted_rel = template.format(
                show_slug=show_slug,
                episode_slug=episode_slug,
                show_title=result.metadata.show_title,
                episode_title=result.metadata.episode_title,
                episode_id=result.metadata.episode_id,
                ext=ext,
                format=format_name,
                output_dir=str(out_base),
            )
            p = Path(formatted_rel)
            if p.is_absolute():
                return p
            return out_base / p

        return out_base / show_slug / f"{episode_slug}.{ext}"

    def export_all(
        self,
        result: TranscriptResult,
        output_dir: Union[str, Path],
        formats: Union[list[str], str] = "both",
        filename_template: Optional[str] = None,
    ) -> dict[str, Path]:
        """Export result into one or more formats and save to disk."""
        target_formats = self.resolve_formats(formats)
        saved_paths: dict[str, Path] = {}

        for fmt in target_formats:
            exporter = self.get_exporter(fmt)
            out_path = self.get_output_path(
                result,
                output_dir=output_dir,
                format_name=fmt,
                template=filename_template,
            )
            saved_paths[fmt] = exporter.save(result, out_path)

        return saved_paths
