"""Pre-flight workload inspector and resource estimator for podcast-cli."""

from __future__ import annotations

import logging
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from podcast_cli.discovery.youtube import is_youtube_url
from podcast_cli.models.transcript import EpisodeMetadata
from podcast_cli.storage.repository import StorageRepository

logger = logging.getLogger(__name__)

# Constants for resource estimation
AUDIO_CACHE_MB_PER_MINUTE: float = 1.0  # Approx. 1 MB per minute of 128-192kbps audio for local Whisper


class PreFlightSummary(BaseModel):
    """Aggregated summary of pre-flight analysis for a batch of podcast episodes."""

    model_config = ConfigDict(extra="ignore")

    total_episodes: int = Field(default=0, description="Total number of episodes in batch")
    total_duration_seconds: float = Field(default=0.0, description="Total duration of all episodes in seconds")
    estimated_storage_mb: float = Field(
        default=0.0,
        description="Estimated audio cache storage requirement in MB (~1MB per minute for local Whisper)",
    )
    tier_breakdown: dict[str, int] = Field(
        default_factory=lambda: {"cached": 0, "rss": 0, "youtube": 0, "whisper": 0, "cloud": 0},
        description="Episode counts categorized by transcription resolution tier",
    )
    episodes: list[EpisodeMetadata] = Field(
        default_factory=list,
        description="List of episode metadata objects in the batch",
    )
    episode_tiers: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping from episode_id to resolved target tier",
    )

    @property
    def formatted_duration(self) -> str:
        """Human-readable duration string (e.g. '2h 15m 30s', '45m 12s', '0s')."""
        total_secs = int(max(0.0, self.total_duration_seconds))
        hours = total_secs // 3600
        minutes = (total_secs % 3600) // 60
        seconds = total_secs % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    @property
    def formatted_storage(self) -> str:
        """Formatted storage string (e.g. '150.0 MB' or '1.4 GB')."""
        if self.estimated_storage_mb >= 1024:
            return f"{self.estimated_storage_mb / 1024:.2f} GB"
        return f"{self.estimated_storage_mb:.1f} MB"

    @property
    def cached_count(self) -> int:
        """Number of episodes already cached."""
        return self.tier_breakdown.get("cached", 0)

    @property
    def rss_count(self) -> int:
        """Number of episodes resolvable via RSS transcripts."""
        return self.tier_breakdown.get("rss", 0)

    @property
    def youtube_count(self) -> int:
        """Number of episodes resolvable via YouTube captions."""
        return self.tier_breakdown.get("youtube", 0)

    @property
    def whisper_count(self) -> int:
        """Number of episodes requiring local Whisper audio transcription."""
        return self.tier_breakdown.get("whisper", 0)

    @property
    def cloud_count(self) -> int:
        """Number of episodes requiring paid Cloud transcription."""
        return self.tier_breakdown.get("cloud", 0)

    @property
    def requires_transcription(self) -> bool:
        """True if any episode in the batch requires non-cached transcription."""
        return (self.total_episodes - self.cached_count) > 0


class PreFlightInspector:
    """Pre-flight analyzer that inspects workload, cache, and available tiers."""

    def __init__(self, repository: Optional[StorageRepository] = None) -> None:
        self.repository = repository

    def inspect_episodes_sync(
        self,
        episodes: list[EpisodeMetadata],
        repository: Optional[StorageRepository] = None,
        preferred_engine: str = "auto",
    ) -> PreFlightSummary:
        """Inspect a list of episodes synchronously and return pre-flight summary."""
        repo = repository or self.repository
        preferred = (preferred_engine or "auto").strip().lower()

        tier_counts = {
            "cached": 0,
            "rss": 0,
            "youtube": 0,
            "whisper": 0,
            "cloud": 0,
        }
        episode_tiers: dict[str, str] = {}
        total_duration = 0.0
        whisper_duration = 0.0

        for ep in episodes:
            show_id = ep.effective_show_id
            ep_id = ep.episode_id
            dur = ep.duration_seconds or 0.0
            total_duration += dur

            # 1. Check if cached in SQLite
            if repo is not None and repo.get_transcript(show_id, ep_id) is not None:
                chosen_tier = "cached"
            # 2. Check engine override if specific
            elif preferred in ("cloud", "groq", "openai"):
                chosen_tier = "cloud"
            elif preferred == "whisper":
                chosen_tier = "whisper"
            elif preferred == "rss":
                chosen_tier = "rss"
            elif preferred == "youtube":
                chosen_tier = "youtube"
            else:
                # 3. Auto tier fallback strategy: RSS -> YouTube -> Whisper -> Cloud
                # 3a. RSS transcript available?
                if ep.rss_transcripts and len(ep.rss_transcripts) > 0:
                    chosen_tier = "rss"
                # 3b. YouTube mapping or YouTube source available?
                elif repo is not None and repo.get_episode_mapping(show_id, ep_id) is not None:
                    chosen_tier = "youtube"
                elif ep.source_type == "youtube" or (ep.audio_url and is_youtube_url(ep.audio_url)):
                    chosen_tier = "youtube"
                elif repo is not None and repo.get_show_mapping(show_id) and repo.get_show_mapping(show_id).youtube_channel_url:
                    chosen_tier = "youtube"
                else:
                    # 3c. Default fallback in auto mode is Whisper (local)
                    chosen_tier = "whisper"

            tier_counts[chosen_tier] = tier_counts.get(chosen_tier, 0) + 1
            episode_tiers[ep_id] = chosen_tier

            if chosen_tier == "whisper":
                whisper_duration += dur

        # Storage calculation: ~1MB per minute for local whisper cache
        estimated_storage_mb = round((whisper_duration / 60.0) * AUDIO_CACHE_MB_PER_MINUTE, 2)

        return PreFlightSummary(
            total_episodes=len(episodes),
            total_duration_seconds=total_duration,
            estimated_storage_mb=estimated_storage_mb,
            tier_breakdown=tier_counts,
            episodes=list(episodes),
            episode_tiers=episode_tiers,
        )

    async def inspect_episodes(
        self,
        episodes: list[EpisodeMetadata],
        repository: Optional[StorageRepository] = None,
        preferred_engine: str = "auto",
    ) -> PreFlightSummary:
        """Inspect a list of episodes asynchronously and return pre-flight summary."""
        return self.inspect_episodes_sync(
            episodes=episodes,
            repository=repository,
            preferred_engine=preferred_engine,
        )
