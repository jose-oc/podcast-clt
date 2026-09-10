"""Storage repository providing high-level CRUD operations for domain models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

from podcast_ctl.models.knowledge import EpisodeMapping, ShowMapping, UserPreference
from podcast_ctl.models.transcript import EpisodeMetadata, TranscriptResult
from podcast_ctl.storage.db import Database


class StorageRepository:
    """Repository abstraction over SQLite database for podcast-ctl domain entities."""

    def __init__(self, db: Optional[Union[Database, str, Path]] = None) -> None:
        if isinstance(db, Database):
            self.db = db
        else:
            self.db = Database(db)
        self.db.init_schema()

    # -------------------------------------------------------------------------
    # Shows CRUD
    # -------------------------------------------------------------------------

    def save_show(
        self,
        metadata: Union[dict[str, Any], str],
        title: Optional[str] = None,
        feed_url: Optional[str] = None,
        metadata_dict: Optional[dict[str, Any]] = None,
    ) -> None:
        """Save or update a podcast show record."""
        if isinstance(metadata, dict):
            show_id = metadata.get("id") or metadata.get("show_id") or metadata.get("title")
            show_title = metadata.get("title") or metadata.get("show_title") or show_id
            show_feed_url = metadata.get("feed_url") or feed_url
            meta_json = json.dumps(metadata)
        else:
            show_id = metadata
            show_title = title or show_id
            show_feed_url = feed_url
            meta_json = json.dumps(metadata_dict or {})

        if not show_id:
            raise ValueError("Show ID or title must not be empty.")

        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO shows (id, title, feed_url, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    feed_url = coalesce(excluded.feed_url, shows.feed_url),
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(show_id), str(show_title), show_feed_url, meta_json),
            )

    def get_show(self, show_id_or_feed_url: str) -> Optional[dict[str, Any]]:
        """Retrieve a show by ID or RSS feed URL."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT id, title, feed_url, metadata_json, updated_at FROM shows WHERE id = ? OR feed_url = ?",
                (show_id_or_feed_url, show_id_or_feed_url),
            )
            row = cursor.fetchone()
            if not row:
                return None

            metadata = {}
            if row["metadata_json"]:
                try:
                    metadata = json.loads(row["metadata_json"])
                except json.JSONDecodeError:
                    metadata = {}

            return {
                "id": row["id"],
                "title": row["title"],
                "feed_url": row["feed_url"],
                "metadata": metadata,
                "updated_at": row["updated_at"],
            }

    def list_shows(self) -> list[dict[str, Any]]:
        """List all saved shows."""
        with self.db.connection() as conn:
            cursor = conn.execute("SELECT id, title, feed_url, metadata_json, updated_at FROM shows ORDER BY updated_at DESC")
            shows = []
            for row in cursor.fetchall():
                metadata = {}
                if row["metadata_json"]:
                    try:
                        metadata = json.loads(row["metadata_json"])
                    except json.JSONDecodeError:
                        metadata = {}
                shows.append({
                    "id": row["id"],
                    "title": row["title"],
                    "feed_url": row["feed_url"],
                    "metadata": metadata,
                    "updated_at": row["updated_at"],
                })
            return shows

    def delete_show(self, show_id: str) -> bool:
        """Delete a show record by ID."""
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM shows WHERE id = ?", (show_id,))
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Episodes CRUD
    # -------------------------------------------------------------------------

    def save_episode(self, episode_data: Union[dict[str, Any], EpisodeMetadata]) -> None:
        """Save or update an episode record."""
        if isinstance(episode_data, EpisodeMetadata):
            show_id = episode_data.effective_show_id
            episode_id = episode_data.episode_id
            title = episode_data.episode_title
            duration = episode_data.duration_seconds
            audio_url = episode_data.audio_url
            published_date = episode_data.published_date
            meta_json = episode_data.model_dump_json()
        else:
            show_id = episode_data.get("show_id") or episode_data.get("show_title") or "unknown"
            episode_id = episode_data.get("id") or episode_data.get("episode_id")
            title = episode_data.get("title") or episode_data.get("episode_title") or episode_id
            duration = episode_data.get("duration") or episode_data.get("duration_seconds")
            audio_url = episode_data.get("audio_url")
            published_date = episode_data.get("published_date")
            meta_json = json.dumps(episode_data)

        if not episode_id:
            raise ValueError("Episode ID must not be empty.")

        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO episodes (id, show_id, title, duration, audio_url, published_date, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(show_id, id) DO UPDATE SET
                    title = excluded.title,
                    duration = excluded.duration,
                    audio_url = excluded.audio_url,
                    published_date = excluded.published_date,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(episode_id), str(show_id), str(title), duration, audio_url, published_date, meta_json),
            )

    def get_episode(self, show_id: str, episode_id: str) -> Optional[dict[str, Any]]:
        """Retrieve an episode record by show ID and episode ID."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT id, show_id, title, duration, audio_url, published_date, metadata_json, updated_at FROM episodes WHERE show_id = ? AND id = ?",
                (show_id, episode_id),
            )
            row = cursor.fetchone()
            if not row:
                return None

            metadata = {}
            if row["metadata_json"]:
                try:
                    metadata = json.loads(row["metadata_json"])
                except json.JSONDecodeError:
                    metadata = {}

            return {
                "id": row["id"],
                "show_id": row["show_id"],
                "title": row["title"],
                "duration": row["duration"],
                "audio_url": row["audio_url"],
                "published_date": row["published_date"],
                "metadata": metadata,
                "updated_at": row["updated_at"],
            }

    # -------------------------------------------------------------------------
    # Transcripts Cache CRUD
    # -------------------------------------------------------------------------

    def save_transcript(self, result: TranscriptResult, show_id: Optional[str] = None) -> None:
        """Save a transcript result into SQLite cache and update episodes metadata."""
        effective_show_id = show_id or result.metadata.effective_show_id
        episode_id = result.metadata.episode_id
        transcript_json = result.model_dump_json()

        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO transcripts (show_id, episode_id, tier_used, transcript_json, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(show_id, episode_id) DO UPDATE SET
                    tier_used = excluded.tier_used,
                    transcript_json = excluded.transcript_json,
                    created_at = CURRENT_TIMESTAMP
                """,
                (effective_show_id, episode_id, result.tier_used, transcript_json),
            )

        # Also store/update episode metadata
        self.save_episode(result.metadata)

    def get_transcript(self, show_id: str, episode_id: str) -> Optional[TranscriptResult]:
        """Retrieve a cached TranscriptResult by show ID and episode ID."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT transcript_json FROM transcripts WHERE show_id = ? AND episode_id = ?",
                (show_id, episode_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return TranscriptResult.model_validate_json(row["transcript_json"])

    def list_transcripts(self, show_id: Optional[str] = None) -> list[TranscriptResult]:
        """List all cached TranscriptResults, optionally filtered by show_id."""
        with self.db.connection() as conn:
            if show_id is not None:
                cursor = conn.execute(
                    "SELECT transcript_json FROM transcripts WHERE show_id = ? ORDER BY created_at DESC",
                    (show_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT transcript_json FROM transcripts ORDER BY created_at DESC"
                )

            results = []
            for row in cursor.fetchall():
                results.append(TranscriptResult.model_validate_json(row["transcript_json"]))
            return results

    # Alias for spec compatibility
    list_cached_transcripts = list_transcripts

    def delete_transcript(self, show_id: str, episode_id: str) -> bool:
        """Delete a single cached transcript."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM transcripts WHERE show_id = ? AND episode_id = ?",
                (show_id, episode_id),
            )
            return cursor.rowcount > 0

    def clear_cache(self, show_id: Optional[str] = None) -> int:
        """Clear cached transcripts for all shows or a specific show. Returns count of deleted transcripts."""
        with self.db.connection() as conn:
            if show_id is not None:
                cursor = conn.execute("DELETE FROM transcripts WHERE show_id = ?", (show_id,))
            else:
                cursor = conn.execute("DELETE FROM transcripts")
            return cursor.rowcount

    # -------------------------------------------------------------------------
    # Knowledge Mappings (Show & Episode mappings)
    # -------------------------------------------------------------------------

    def save_show_mapping(self, mapping: ShowMapping) -> None:
        """Save or update a ShowMapping (Podcast Feed URL -> YouTube Channel & Custom Settings)."""
        meta_json = json.dumps({
            "show_title": mapping.show_title,
            "custom_settings": mapping.custom_settings,
        })
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_mappings (mapping_type, key, target_url, confirmed_by_user, metadata_json, updated_at)
                VALUES ('show', ?, ?, 1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    target_url = excluded.target_url,
                    confirmed_by_user = excluded.confirmed_by_user,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (mapping.feed_url, mapping.youtube_channel_url, meta_json),
            )

    def get_show_mapping(self, feed_url: str) -> Optional[ShowMapping]:
        """Retrieve a ShowMapping by feed URL."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT key, target_url, metadata_json FROM knowledge_mappings WHERE mapping_type = 'show' AND key = ?",
                (feed_url,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            data = {}
            if row["metadata_json"]:
                try:
                    data = json.loads(row["metadata_json"])
                except json.JSONDecodeError:
                    data = {}

            return ShowMapping(
                feed_url=row["key"],
                show_title=data.get("show_title", ""),
                youtube_channel_url=row["target_url"],
                custom_settings=data.get("custom_settings", {}),
            )

    def list_show_mappings(self) -> list[ShowMapping]:
        """List all saved ShowMappings."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT key, target_url, metadata_json FROM knowledge_mappings WHERE mapping_type = 'show' ORDER BY updated_at DESC"
            )
            mappings = []
            for row in cursor.fetchall():
                data = {}
                if row["metadata_json"]:
                    try:
                        data = json.loads(row["metadata_json"])
                    except json.JSONDecodeError:
                        data = {}
                mappings.append(
                    ShowMapping(
                        feed_url=row["key"],
                        show_title=data.get("show_title", ""),
                        youtube_channel_url=row["target_url"],
                        custom_settings=data.get("custom_settings", {}),
                    )
                )
            return mappings

    def delete_show_mapping(self, feed_url: str) -> bool:
        """Delete a ShowMapping by feed URL."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM knowledge_mappings WHERE mapping_type = 'show' AND key = ?",
                (feed_url,),
            )
            return cursor.rowcount > 0

    def save_episode_mapping(self, mapping: EpisodeMapping) -> None:
        """Save or update an EpisodeMapping (Show ID + Episode ID -> YouTube Video URL)."""
        key = f"{mapping.show_id}::{mapping.episode_id}"
        meta_json = json.dumps({
            "show_id": mapping.show_id,
            "episode_id": mapping.episode_id,
        })
        confirmed_int = 1 if mapping.confirmed_by_user else 0

        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_mappings (mapping_type, key, target_url, confirmed_by_user, metadata_json, updated_at)
                VALUES ('episode', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    target_url = excluded.target_url,
                    confirmed_by_user = excluded.confirmed_by_user,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, mapping.youtube_video_url, confirmed_int, meta_json),
            )

    def get_episode_mapping(self, show_id: str, episode_id: str) -> Optional[EpisodeMapping]:
        """Retrieve an EpisodeMapping by show ID and episode ID."""
        key = f"{show_id}::{episode_id}"
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT key, target_url, confirmed_by_user, metadata_json FROM knowledge_mappings WHERE mapping_type = 'episode' AND key = ?",
                (key,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            data = {}
            if row["metadata_json"]:
                try:
                    data = json.loads(row["metadata_json"])
                except json.JSONDecodeError:
                    data = {}

            return EpisodeMapping(
                show_id=data.get("show_id", show_id),
                episode_id=data.get("episode_id", episode_id),
                youtube_video_url=row["target_url"],
                confirmed_by_user=bool(row["confirmed_by_user"]),
            )

    def list_episode_mappings(self, show_id: Optional[str] = None) -> list[EpisodeMapping]:
        """List all saved EpisodeMappings, optionally filtered by show_id."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT key, target_url, confirmed_by_user, metadata_json FROM knowledge_mappings WHERE mapping_type = 'episode' ORDER BY updated_at DESC"
            )
            mappings = []
            for row in cursor.fetchall():
                data = {}
                if row["metadata_json"]:
                    try:
                        data = json.loads(row["metadata_json"])
                    except json.JSONDecodeError:
                        data = {}
                item_show_id = data.get("show_id", "")
                if show_id is not None and item_show_id != show_id:
                    continue
                mappings.append(
                    EpisodeMapping(
                        show_id=item_show_id,
                        episode_id=data.get("episode_id", ""),
                        youtube_video_url=row["target_url"],
                        confirmed_by_user=bool(row["confirmed_by_user"]),
                    )
                )
            return mappings

    def delete_episode_mapping(self, show_id: str, episode_id: str) -> bool:
        """Delete an EpisodeMapping by show ID and episode ID."""
        key = f"{show_id}::{episode_id}"
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM knowledge_mappings WHERE mapping_type = 'episode' AND key = ?",
                (key,),
            )
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # User Preferences CRUD
    # -------------------------------------------------------------------------

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Retrieve a user preference value by key."""
        with self.db.connection() as conn:
            cursor = conn.execute("SELECT value_json FROM preferences WHERE key = ?", (key,))
            row = cursor.fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value_json"])
            except json.JSONDecodeError:
                return row["value_json"]

    def set_preference(self, key: Union[str, UserPreference], value: Any = None) -> None:
        """Set or update a user preference key-value pair."""
        if isinstance(key, UserPreference):
            pref_key = key.key
            pref_val = key.value
        else:
            pref_key = key
            pref_val = value

        val_json = json.dumps(pref_val)
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO preferences (key, value_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(pref_key), val_json),
            )

    def delete_preference(self, key: str) -> bool:
        """Delete a user preference by key."""
        with self.db.connection() as conn:
            cursor = conn.execute("DELETE FROM preferences WHERE key = ?", (key,))
            return cursor.rowcount > 0

    def list_preferences(self) -> dict[str, Any]:
        """Retrieve all stored user preferences as a dictionary."""
        with self.db.connection() as conn:
            cursor = conn.execute("SELECT key, value_json FROM preferences")
            prefs = {}
            for row in cursor.fetchall():
                try:
                    prefs[row["key"]] = json.loads(row["value_json"])
                except json.JSONDecodeError:
                    prefs[row["key"]] = row["value_json"]
            return prefs

    # -------------------------------------------------------------------------
    # Statistics & Health
    # -------------------------------------------------------------------------

    def get_cache_stats(self) -> dict[str, Any]:
        """Return cache statistics including counts of entities and database size."""
        with self.db.connection() as conn:
            shows_count = conn.execute("SELECT COUNT(*) FROM shows").fetchone()[0]
            episodes_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            transcripts_count = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
            mappings_count = conn.execute("SELECT COUNT(*) FROM knowledge_mappings").fetchone()[0]
            preferences_count = conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]

        size_bytes = 0
        if not self.db.is_memory and self.db.db_path.exists():
            size_bytes = self.db.db_path.stat().st_size

        return {
            "transcripts_count": transcripts_count,
            "shows_count": shows_count,
            "episodes_count": episodes_count,
            "mappings_count": mappings_count,
            "preferences_count": preferences_count,
            "database_path": str(self.db.db_path),
            "size_bytes": size_bytes,
        }
