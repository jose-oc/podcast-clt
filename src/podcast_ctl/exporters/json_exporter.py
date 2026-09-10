"""JSON transcript exporter for structured data dumping."""

from __future__ import annotations

from podcast_ctl.exporters.base import BaseExporter
from podcast_ctl.models.transcript import TranscriptResult


class JsonExporter(BaseExporter):
    """Exports full TranscriptResult domain model to formatted JSON."""

    format_name: str = "json"
    extension: str = "json"

    def __init__(self, indent: int = 2) -> None:
        self.indent = indent

    def export(self, result: TranscriptResult) -> str:
        """Serialize TranscriptResult to formatted JSON string."""
        json_str = result.model_dump_json(indent=self.indent)
        if not json_str.endswith("\n"):
            json_str += "\n"
        return json_str
