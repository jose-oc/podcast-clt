"""Persistent knowledge learner for storing user mappings and execution preferences."""

from __future__ import annotations

import logging
from typing import Optional

from podcast_cli.models.knowledge import EpisodeMapping, ShowMapping
from podcast_cli.storage.repository import StorageRepository

logger = logging.getLogger(__name__)


class KnowledgeLearner:
    """Manages persistent knowledge updates for YouTube mappings and user cloud preferences."""

    def __init__(self, repository: Optional[StorageRepository] = None) -> None:
        self.repository = repository

    @classmethod
    def learn_youtube_mapping(
        cls,
        repository: StorageRepository,
        show_id: str,
        episode_id: str,
        youtube_url: str,
        show_title: Optional[str] = None,
        channel_url: Optional[str] = None,
    ) -> EpisodeMapping:
        """Persist a confirmed YouTube video mapping for an episode and optionally update show mapping.

        Args:
            repository: Storage repository instance.
            show_id: Identifier or title of the show.
            episode_id: Identifier or GUID of the episode.
            youtube_url: Confirmed YouTube video URL.
            show_title: Optional show title string.
            channel_url: Optional YouTube channel URL.

        Returns:
            Saved EpisodeMapping object.
        """
        mapping = EpisodeMapping(
            show_id=show_id,
            episode_id=episode_id,
            youtube_video_url=youtube_url,
            confirmed_by_user=True,
        )
        repository.save_episode_mapping(mapping)
        logger.info(f"Saved episode YouTube mapping: {show_id}::{episode_id} -> {youtube_url}")

        if channel_url:
            show_mapping = ShowMapping(
                feed_url=show_id,
                show_title=show_title or show_id,
                youtube_channel_url=channel_url,
            )
            repository.save_show_mapping(show_mapping)
            logger.info(f"Saved show YouTube channel mapping: {show_id} -> {channel_url}")

        return mapping

    @classmethod
    def learn_cloud_preference(
        cls,
        repository: StorageRepository,
        show_id: str,
        always_allow_cloud: bool = True,
    ) -> None:
        """Persist a user's cloud transcription approval preference for a show.

        Args:
            repository: Storage repository instance.
            show_id: Identifier or title of the show.
            always_allow_cloud: Boolean whether cloud transcription is approved for this show.
        """
        pref_key = f"cloud_allowed:{show_id}"
        repository.set_preference(pref_key, always_allow_cloud)
        logger.info(f"Saved cloud preference '{pref_key}' = {always_allow_cloud}")

    @classmethod
    def is_cloud_allowed(
        cls,
        repository: StorageRepository,
        show_id: str,
    ) -> bool:
        """Check if cloud transcription has been permanently approved for a show.

        Args:
            repository: Storage repository instance.
            show_id: Identifier or title of the show.

        Returns:
            True if cloud is approved for the show, False otherwise.
        """
        pref_key = f"cloud_allowed:{show_id}"
        val = repository.get_preference(pref_key, default=False)
        return bool(val)

    @classmethod
    def get_known_youtube_mapping(
        cls,
        repository: StorageRepository,
        show_id: str,
        episode_id: str,
    ) -> Optional[str]:
        """Retrieve confirmed YouTube video URL mapping if previously stored."""
        mapping = repository.get_episode_mapping(show_id, episode_id)
        if mapping and mapping.youtube_video_url:
            return mapping.youtube_video_url
        return None

    @classmethod
    def get_known_show_channel(
        cls,
        repository: StorageRepository,
        show_id: str,
    ) -> Optional[str]:
        """Retrieve confirmed YouTube channel URL if previously stored."""
        mapping = repository.get_show_mapping(show_id)
        if mapping and mapping.youtube_channel_url:
            return mapping.youtube_channel_url
        return None

    @classmethod
    def forget_youtube_mapping(
        cls,
        repository: StorageRepository,
        show_id: str,
        episode_id: str,
    ) -> bool:
        """Remove a stored episode YouTube mapping."""
        return repository.delete_episode_mapping(show_id, episode_id)

    @classmethod
    def forget_cloud_preference(
        cls,
        repository: StorageRepository,
        show_id: str,
    ) -> bool:
        """Remove a stored cloud preference for a show."""
        pref_key = f"cloud_allowed:{show_id}"
        return repository.delete_preference(pref_key)

    # -------------------------------------------------------------------------
    # Instance method conveniences
    # -------------------------------------------------------------------------

    def record_youtube_mapping(
        self,
        show_id: str,
        episode_id: str,
        youtube_url: str,
        show_title: Optional[str] = None,
        channel_url: Optional[str] = None,
    ) -> EpisodeMapping:
        """Instance method convenience for learn_youtube_mapping."""
        if self.repository is None:
            raise ValueError("Storage repository is required for KnowledgeLearner instance operations.")
        return self.learn_youtube_mapping(
            repository=self.repository,
            show_id=show_id,
            episode_id=episode_id,
            youtube_url=youtube_url,
            show_title=show_title,
            channel_url=channel_url,
        )

    def record_cloud_preference(
        self,
        show_id: str,
        always_allow_cloud: bool = True,
    ) -> None:
        """Instance method convenience for learn_cloud_preference."""
        if self.repository is None:
            raise ValueError("Storage repository is required for KnowledgeLearner instance operations.")
        self.learn_cloud_preference(
            repository=self.repository,
            show_id=show_id,
            always_allow_cloud=always_allow_cloud,
        )

    def check_cloud_allowed(self, show_id: str) -> bool:
        """Instance method convenience for is_cloud_allowed."""
        if self.repository is None:
            raise ValueError("Storage repository is required for KnowledgeLearner instance operations.")
        return self.is_cloud_allowed(
            repository=self.repository,
            show_id=show_id,
        )
