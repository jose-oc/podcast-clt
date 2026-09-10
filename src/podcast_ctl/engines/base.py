"""Abstract base class and exceptions for podcast-ctl transcription engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from podcast_ctl.models.transcript import EpisodeMetadata, TranscriptResult


class TranscriptionEngineError(Exception):
    """Base exception for all transcription engine errors."""


class EngineUnavailableError(TranscriptionEngineError):
    """Raised when an engine cannot run due to missing tools, dependencies, or keys."""


class TranscriptNotFoundError(TranscriptionEngineError):
    """Raised when transcripts or subtitles are not found or cannot be parsed."""


class BaseTranscriptionEngine(ABC):
    """Abstract base class for all transcription engine implementations."""

    name: str = "base"
    tier: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether the engine is available in the current runtime environment."""
        pass

    @abstractmethod
    async def transcribe(
        self,
        episode: EpisodeMetadata,
        **kwargs: Any,
    ) -> TranscriptResult:
        """Transcribe an episode and return a normalized TranscriptResult."""
        pass
