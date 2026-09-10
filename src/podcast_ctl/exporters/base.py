"""Base exporter interface and common formatting utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Union

from podcast_ctl.models.transcript import TranscriptResult


def format_timestamp(
    seconds: float,
    always_include_hours: bool = True,
    decimal_separator: Optional[str] = None,
    decimal_places: int = 3,
) -> str:
    """Format a duration in seconds into a timestamp string.

    Examples:
        format_timestamp(3665.123) -> "01:01:05"
        format_timestamp(3665.123, decimal_separator=".") -> "01:01:05.123"
        format_timestamp(3665.123, decimal_separator=",") -> "01:01:05,123"
        format_timestamp(65.123, always_include_hours=False) -> "01:05"
    """
    if seconds < 0:
        seconds = 0.0

    total_seconds = int(seconds)
    fraction = seconds - total_seconds

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if decimal_separator is not None:
        factor = 10**decimal_places
        ms_val = int(round(fraction * factor))
        if ms_val >= factor:
            return format_timestamp(
                seconds=float(total_seconds + 1),
                always_include_hours=always_include_hours,
                decimal_separator=decimal_separator,
                decimal_places=decimal_places,
            )
        ms_str = f"{ms_val:0{decimal_places}d}"
        if always_include_hours or hours > 0:
            time_part = f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            time_part = f"{minutes:02d}:{secs:02d}"
        return f"{time_part}{decimal_separator}{ms_str}"

    if always_include_hours or hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_duration(duration_seconds: Optional[float]) -> str:
    """Format duration into standard 'HH:MM:SS' format."""
    if duration_seconds is None or duration_seconds < 0:
        return "00:00:00"
    return format_timestamp(duration_seconds, always_include_hours=True)


class BaseExporter(ABC):
    """Abstract base class for all transcript exporters."""

    format_name: str = ""
    extension: str = ""

    @abstractmethod
    def export(self, result: TranscriptResult) -> str:
        """Export TranscriptResult to a string representation."""
        raise NotImplementedError

    def save(self, result: TranscriptResult, output_path: Union[str, Path]) -> Path:
        """Export result and write content to destination path."""
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self.export(result)
        path.write_text(content, encoding="utf-8")
        return path
