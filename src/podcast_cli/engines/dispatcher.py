"""Dispatcher and coordinator for 4-tier transcription hierarchy."""

from __future__ import annotations

import logging
from typing import Any, Optional

from podcast_cli.engines.base import (
    BaseTranscriptionEngine,
    EngineUnavailableError,
    TranscriptNotFoundError,
    TranscriptionEngineError,
)
from podcast_cli.engines.cloud_engine import CloudTranscriptionEngine
from podcast_cli.engines.rss_engine import RSSTranscriptionEngine
from podcast_cli.engines.whisper_engine import WhisperTranscriptionEngine
from podcast_cli.engines.youtube_engine import YouTubeTranscriptionEngine
from podcast_cli.models.transcript import EpisodeMetadata, TranscriptResult
from podcast_cli.storage.repository import StorageRepository

logger = logging.getLogger(__name__)

# Default 4-tier fallback order
DEFAULT_AUTO_TIERS = ["rss", "youtube", "whisper", "cloud"]


class TranscriptionDispatcher:
    """Coordinates transcription resolution across 4 tiers with cache lookup and auto-fallback."""

    def __init__(
        self,
        storage_repo: Optional[StorageRepository] = None,
        engines: Optional[dict[str, BaseTranscriptionEngine]] = None,
        default_engine: str = "auto",
    ) -> None:
        self.storage_repo = storage_repo or StorageRepository()
        self.default_engine = default_engine.lower()

        # Initialize default engines if not provided
        self.engines: dict[str, BaseTranscriptionEngine] = engines or {
            "rss": RSSTranscriptionEngine(),
            "youtube": YouTubeTranscriptionEngine(),
            "whisper": WhisperTranscriptionEngine(),
            "groq": CloudTranscriptionEngine(provider="groq"),
            "openai": CloudTranscriptionEngine(provider="openai"),
            "cloud": CloudTranscriptionEngine(provider="groq"),
        }

    def register_engine(self, name: str, engine: BaseTranscriptionEngine) -> None:
        """Register or replace a transcription engine by name."""
        self.engines[name.lower()] = engine

    def get_engine(self, name: str) -> BaseTranscriptionEngine:
        """Retrieve an engine instance by name."""
        name_lower = name.lower()
        if name_lower not in self.engines:
            raise EngineUnavailableError(
                f"Unknown transcription engine '{name}'. Available: {list(self.engines.keys())}"
            )
        return self.engines[name_lower]

    def resolve_execution_chain(self, requested_engine: str) -> list[str]:
        """Determine the ordered list of engine identifiers to attempt."""
        req = requested_engine.lower()
        if req == "auto":
            return list(DEFAULT_AUTO_TIERS)
        elif req in self.engines:
            return [req]
        else:
            raise EngineUnavailableError(
                f"Invalid engine '{requested_engine}'. Choose from 'auto', {', '.join(self.engines.keys())}."
            )

    async def transcribe(
        self,
        episode: EpisodeMetadata,
        engine: Optional[str] = None,
        force: bool = False,
        bypass_cache: bool = False,
        **kwargs: Any,
    ) -> TranscriptResult:
        """Transcribe an episode respecting cache, engine selection, and fallback hierarchy.

        Args:
            episode: Episode metadata to transcribe.
            engine: Engine name override ('auto', 'rss', 'youtube', 'whisper', 'groq', 'openai', 'cloud').
            force: If True, bypass cache and overwrite existing cache on completion.
            bypass_cache: If True, do not read from or write to the cache.
            **kwargs: Extra arguments passed to engines (e.g., model_size, device, api_key).
        """
        show_id = episode.effective_show_id
        episode_id = episode.episode_id
        engine_target = (engine or self.default_engine).lower()

        # 1. Check SQLite Cache
        if not force and not bypass_cache and self.storage_repo:
            cached = self.storage_repo.get_transcript(show_id, episode_id)
            if cached is not None:
                logger.info(f"Cache hit for episode '{episode.episode_title}' (tier: {cached.tier_used})")
                return cached

        # 2. Check for YouTube knowledge mapping if applicable
        mapped_youtube_url: Optional[str] = None
        if self.storage_repo:
            ep_mapping = self.storage_repo.get_episode_mapping(show_id, episode_id)
            if ep_mapping and ep_mapping.youtube_video_url:
                mapped_youtube_url = ep_mapping.youtube_video_url

        execution_chain = self.resolve_execution_chain(engine_target)
        attempt_errors: list[str] = []

        for eng_name in execution_chain:
            try:
                eng = self.get_engine(eng_name)
            except Exception as exc:
                attempt_errors.append(f"[{eng_name}] Unavailable: {exc}")
                continue

            if not eng.is_available():
                logger.debug(f"Skipping engine '{eng_name}' (not available in current environment)")
                attempt_errors.append(f"[{eng_name}] Not available (missing dependencies or API key)")
                continue

            # Pass mapped YouTube URL if engine is youtube
            call_kwargs = dict(kwargs)
            if eng_name == "youtube" and mapped_youtube_url and "youtube_url" not in call_kwargs:
                call_kwargs["youtube_url"] = mapped_youtube_url

            logger.info(f"Attempting transcription for '{episode.episode_title}' using engine '{eng_name}'...")
            try:
                result = await eng.transcribe(episode, **call_kwargs)

                # Save to cache if cache is enabled
                if not bypass_cache and self.storage_repo:
                    self.storage_repo.save_transcript(result)

                logger.info(f"Successfully transcribed '{episode.episode_title}' with tier '{result.tier_used}'.")
                return result

            except (TranscriptNotFoundError, EngineUnavailableError) as exc:
                logger.info(f"Engine '{eng_name}' skipped: {exc}")
                attempt_errors.append(f"[{eng_name}] {exc}")
            except Exception as exc:
                logger.warning(f"Engine '{eng_name}' failed with unexpected error: {exc}")
                attempt_errors.append(f"[{eng_name}] Unexpected error: {exc}")

        raise TranscriptionEngineError(
            f"All transcription engines failed for episode '{episode.episode_title}'.\n"
            + "\n".join(f"  - {err}" for err in attempt_errors)
        )
