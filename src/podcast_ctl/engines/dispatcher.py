"""Dispatcher and coordinator for 4-tier transcription hierarchy."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from podcast_ctl.engines.base import (
    BaseTranscriptionEngine,
    EngineUnavailableError,
    TranscriptionEngineError,
    TranscriptNotFoundError,
)
from podcast_ctl.engines.channel_search import search_channel_for_episode
from podcast_ctl.engines.cloud_engine import CloudTranscriptionEngine
from podcast_ctl.engines.rss_engine import RSSTranscriptionEngine
from podcast_ctl.engines.whisper_engine import WhisperTranscriptionEngine
from podcast_ctl.engines.youtube_engine import YouTubeTranscriptionEngine, extract_youtube_video_id
from podcast_ctl.models.knowledge import EpisodeMapping
from podcast_ctl.models.transcript import EpisodeMetadata, TranscriptResult
from podcast_ctl.storage.repository import StorageRepository

logger = logging.getLogger(__name__)

# Default 4-tier fallback order
DEFAULT_AUTO_TIERS = ["rss", "youtube", "whisper", "cloud"]


class TranscriptionDispatcher:
    """Coordinates transcription resolution across 4 tiers with cache lookup and auto-fallback."""

    def __init__(
        self,
        storage_repo: StorageRepository | None = None,
        engines: dict[str, BaseTranscriptionEngine] | None = None,
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
        engine: str | None = None,
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
        mapped_youtube_url: str | None = None
        if self.storage_repo:
            ep_mapping = self.storage_repo.get_episode_mapping(show_id, episode_id)
            if ep_mapping and ep_mapping.youtube_video_url:
                mapped_youtube_url = ep_mapping.youtube_video_url

        execution_chain = self.resolve_execution_chain(engine_target)

        # 2b. Fallback: Show -> YouTube Channel mapping. Search the channel's
        # recent videos for a title that closely matches the episode title.
        channel_search_note: str | None = None
        if (
            mapped_youtube_url is None
            and "youtube" in execution_chain
            and self.storage_repo
            and not extract_youtube_video_id(episode.episode_id)
            and not extract_youtube_video_id(episode.audio_url)
        ):
            show_mapping = self.storage_repo.find_show_mapping(show_id)
            if show_mapping and show_mapping.youtube_channel_url:
                channel_url = show_mapping.youtube_channel_url
                try:
                    search = await asyncio.to_thread(
                        search_channel_for_episode,
                        channel_url,
                        episode.episode_title,
                    )
                except Exception as exc:
                    logger.info(f"YouTube channel search failed for '{channel_url}': {exc}")
                    channel_search_note = (
                        f"[youtube] Show mapping points to channel {channel_url} but searching it failed: {exc}"
                    )
                else:
                    if search.video_url:
                        mapped_youtube_url = search.video_url
                        logger.info(
                            f"Resolved '{episode.episode_title}' via channel search: "
                            f"'{search.matched_title}' (similarity {search.similarity:.2f})"
                        )
                        # Auto-learn the discovered mapping (unconfirmed)
                        self.storage_repo.save_episode_mapping(
                            EpisodeMapping(
                                show_id=show_id,
                                episode_id=episode_id,
                                youtube_video_url=search.video_url,
                                confirmed_by_user=False,
                            )
                        )
                    else:
                        channel_search_note = (
                            f"[youtube] Show mapping points to channel {channel_url}, but none of its "
                            f"{search.videos_searched} recent videos closely matches "
                            f"'{episode.episode_title}' (best similarity {search.best_similarity:.0%}). "
                            "Add an explicit mapping with 'podcast-ctl mapping add episode'."
                        )
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
                if eng_name == "youtube" and channel_search_note:
                    attempt_errors.append(channel_search_note)
            except Exception as exc:
                logger.warning(f"Engine '{eng_name}' failed with unexpected error: {exc}")
                attempt_errors.append(f"[{eng_name}] Unexpected error: {exc}")

        raise TranscriptionEngineError(
            f"All transcription engines failed for episode '{episode.episode_title}'.\n"
            + "\n".join(f"  - {err}" for err in attempt_errors)
        )
