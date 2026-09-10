"""Domain models for knowledge mappings and user preferences."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ShowMapping(BaseModel):
    """Mapping between a podcast RSS feed and its YouTube channel / custom settings."""

    model_config = ConfigDict(extra="ignore")

    feed_url: str = Field(..., description="Podcast RSS feed URL")
    show_title: str = Field(..., description="Title of the podcast show")
    youtube_channel_url: str | None = Field(
        default=None,
        description="Associated YouTube channel URL or handle",
    )
    custom_settings: dict[str, Any] = Field(
        default_factory=dict,
        description="User-specific settings (e.g., preferred engine, custom prompt, language)",
    )


class EpisodeMapping(BaseModel):
    """Mapping between a specific podcast episode and a YouTube video URL."""

    model_config = ConfigDict(extra="ignore")

    show_id: str = Field(..., description="Identifier or title of the show")
    episode_id: str = Field(..., description="Identifier or GUID of the episode")
    youtube_video_url: str = Field(..., description="Direct YouTube video URL for subtitles")
    confirmed_by_user: bool = Field(
        default=True,
        description="Whether this mapping was confirmed by user or auto-discovered",
    )


class UserPreference(BaseModel):
    """Persistent user preference key-value pair."""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(..., description="Preference key identifier")
    value: Any = Field(..., description="Preference value (primitive, dict, or list)")
    updated_at: str | None = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO timestamp when preference was last updated",
    )
