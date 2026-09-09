"""Domain models for transcript segments, episode metadata, and transcript results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class TranscriptSegment(BaseModel):
    """Represents a single timed segment of transcribed speech."""

    model_config = ConfigDict(extra="ignore")

    start: float = Field(..., description="Start timestamp in seconds")
    end: float = Field(..., description="End timestamp in seconds")
    text: str = Field(..., description="Transcribed text content")
    speaker: Optional[str] = Field(default=None, description="Speaker identifier if available")
    confidence: Optional[float] = Field(default=None, description="Confidence score between 0.0 and 1.0")

    @property
    def duration(self) -> float:
        """Calculate segment duration in seconds."""
        return max(0.0, self.end - self.start)


class EpisodeMetadata(BaseModel):
    """Metadata describing a podcast or media episode."""

    model_config = ConfigDict(extra="ignore")

    show_title: str = Field(..., description="Title of the podcast / series / channel")
    episode_title: str = Field(..., description="Title of the specific episode")
    episode_id: str = Field(..., description="Unique episode identifier or enclosure hash/guid")
    show_id: Optional[str] = Field(default=None, description="Optional show identifier or slug")
    audio_url: Optional[str] = Field(default=None, description="Direct audio enclosure URL")
    duration_seconds: Optional[float] = Field(default=None, description="Duration in seconds")
    published_date: Optional[str] = Field(default=None, description="ISO or RFC publication date string")
    rss_transcripts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of Podcasting 2.0 transcript tag dictionaries (url, type, language, rel)",
    )
    source_type: Literal["rss", "youtube", "local", "direct"] | str = Field(
        default="rss",
        description="Source type of the episode ('rss', 'youtube', 'local', 'direct')",
    )

    @property
    def effective_show_id(self) -> str:
        """Returns show_id if set, otherwise falls back to show_title."""
        return self.show_id or self.show_title


class TranscriptResult(BaseModel):
    """Normalized output produced by any transcription engine."""

    model_config = ConfigDict(extra="ignore")

    metadata: EpisodeMetadata = Field(..., description="Episode metadata associated with transcript")
    segments: list[TranscriptSegment] = Field(
        default_factory=list,
        description="Ordered list of timed transcript segments",
    )
    tier_used: Literal["rss", "youtube", "whisper", "cloud"] | str = Field(
        ...,
        description="The transcription engine tier that produced this result ('rss', 'youtube', 'whisper', 'cloud')",
    )
    raw_text: str = Field(
        default="",
        description="Full concatenated plain text transcript",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp of when the transcript was generated",
    )

    def model_post_init(self, __context: Any) -> None:
        """Auto-populate raw_text from segments if raw_text is empty and segments exist."""
        if not self.raw_text and self.segments:
            self.raw_text = " ".join(seg.text.strip() for seg in self.segments if seg.text.strip())
