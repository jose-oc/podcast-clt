"""Unit tests for domain models and SQLite storage repository."""

from pathlib import Path
import sqlite3
import pytest

from podcast_cli.models import (
    EpisodeMapping,
    EpisodeMetadata,
    ShowMapping,
    TranscriptResult,
    TranscriptSegment,
    UserPreference,
)
from podcast_cli.storage import (
    DEFAULT_DB_DIR,
    DEFAULT_DB_FILE,
    Database,
    StorageRepository,
    get_default_db_path,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def memory_repo() -> StorageRepository:
    """Provides a fresh StorageRepository backed by an in-memory SQLite database."""
    db = Database(":memory:")
    return StorageRepository(db)


@pytest.fixture
def temp_disk_repo(tmp_path: Path) -> StorageRepository:
    """Provides a StorageRepository backed by a temporary file-based SQLite database."""
    db_file = tmp_path / "test_podcast.db"
    return StorageRepository(db_file)


@pytest.fixture
def sample_segments() -> list[TranscriptSegment]:
    """Sample list of timed transcript segments."""
    return [
        TranscriptSegment(start=0.0, end=4.5, text="Welcome to the podcast.", speaker="Host", confidence=0.98),
        TranscriptSegment(start=4.5, end=9.2, text="Today we discuss AI systems.", speaker="Host", confidence=0.95),
        TranscriptSegment(start=9.2, end=15.0, text="It is great to be here.", speaker="Guest", confidence=0.92),
    ]


@pytest.fixture
def sample_metadata() -> EpisodeMetadata:
    """Sample episode metadata."""
    return EpisodeMetadata(
        show_title="Tech Frontier",
        episode_title="Episode 42: Future of AI",
        episode_id="ep-42-ai",
        show_id="tech-frontier",
        audio_url="https://example.com/audio/ep42.mp3",
        duration_seconds=3600.0,
        published_date="2026-09-01T12:00:00Z",
        rss_transcripts=[{"url": "https://example.com/ep42.vtt", "type": "text/vtt", "language": "en"}],
        source_type="rss",
    )


@pytest.fixture
def sample_transcript_result(
    sample_metadata: EpisodeMetadata, sample_segments: list[TranscriptSegment]
) -> TranscriptResult:
    """Sample TranscriptResult containing metadata and segments."""
    return TranscriptResult(
        metadata=sample_metadata,
        segments=sample_segments,
        tier_used="rss",
        raw_text="Welcome to the podcast. Today we discuss AI systems. It is great to be here.",
        created_at="2026-09-09T08:00:00Z",
    )


# =============================================================================
# 1. Pydantic Domain Model Tests
# =============================================================================


class TestDomainModels:
    def test_transcript_segment_creation_and_duration(self) -> None:
        seg = TranscriptSegment(start=10.5, end=20.0, text="Hello world", speaker="Alice", confidence=0.89)
        assert seg.start == 10.5
        assert seg.end == 20.0
        assert seg.text == "Hello world"
        assert seg.speaker == "Alice"
        assert seg.confidence == 0.89
        assert seg.duration == pytest.approx(9.5)

    def test_transcript_segment_optional_fields_default_to_none(self) -> None:
        seg = TranscriptSegment(start=0.0, end=5.0, text="No speaker")
        assert seg.speaker is None
        assert seg.confidence is None
        assert seg.duration == pytest.approx(5.0)

    def test_episode_metadata_defaults_and_effective_show_id(self) -> None:
        meta_with_slug = EpisodeMetadata(
            show_title="My Show",
            episode_title="My Ep",
            episode_id="ep-1",
            show_id="my-show-slug",
        )
        assert meta_with_slug.effective_show_id == "my-show-slug"
        assert meta_with_slug.source_type == "rss"
        assert meta_with_slug.rss_transcripts == []

        meta_without_slug = EpisodeMetadata(
            show_title="My Show",
            episode_title="My Ep",
            episode_id="ep-1",
        )
        assert meta_without_slug.effective_show_id == "My Show"

    def test_transcript_result_auto_raw_text(self, sample_metadata: EpisodeMetadata) -> None:
        segments = [
            TranscriptSegment(start=0.0, end=2.0, text="Part one."),
            TranscriptSegment(start=2.0, end=4.0, text="Part two."),
        ]
        result = TranscriptResult(
            metadata=sample_metadata,
            segments=segments,
            tier_used="whisper",
        )
        assert result.raw_text == "Part one. Part two."
        assert result.created_at is not None

    def test_transcript_result_explicit_raw_text_preserved(
        self, sample_metadata: EpisodeMetadata
    ) -> None:
        result = TranscriptResult(
            metadata=sample_metadata,
            segments=[TranscriptSegment(start=0.0, end=2.0, text="Ignored for raw_text override")],
            tier_used="whisper",
            raw_text="Explicit custom transcript string.",
        )
        assert result.raw_text == "Explicit custom transcript string."

    def test_transcript_result_json_roundtrip(self, sample_transcript_result: TranscriptResult) -> None:
        json_str = sample_transcript_result.model_dump_json()
        restored = TranscriptResult.model_validate_json(json_str)
        assert restored.metadata.show_title == sample_transcript_result.metadata.show_title
        assert restored.metadata.episode_id == sample_transcript_result.metadata.episode_id
        assert len(restored.segments) == len(sample_transcript_result.segments)
        assert restored.segments[0].speaker == "Host"
        assert restored.tier_used == "rss"
        assert restored.raw_text == sample_transcript_result.raw_text

    def test_show_mapping_model(self) -> None:
        mapping = ShowMapping(
            feed_url="https://feeds.example.com/show.rss",
            show_title="Test Show",
            youtube_channel_url="https://youtube.com/@testshow",
            custom_settings={"engine": "whisper", "model": "medium"},
        )
        assert mapping.feed_url == "https://feeds.example.com/show.rss"
        assert mapping.show_title == "Test Show"
        assert mapping.youtube_channel_url == "https://youtube.com/@testshow"
        assert mapping.custom_settings["engine"] == "whisper"

        # Defaults
        mapping_defaults = ShowMapping(feed_url="https://feed.rss", show_title="Show")
        assert mapping_defaults.youtube_channel_url is None
        assert mapping_defaults.custom_settings == {}

    def test_episode_mapping_model(self) -> None:
        mapping = EpisodeMapping(
            show_id="show-1",
            episode_id="ep-100",
            youtube_video_url="https://youtube.com/watch?v=abc123xyz",
        )
        assert mapping.show_id == "show-1"
        assert mapping.episode_id == "ep-100"
        assert mapping.youtube_video_url == "https://youtube.com/watch?v=abc123xyz"
        assert mapping.confirmed_by_user is True

    def test_user_preference_model(self) -> None:
        pref = UserPreference(key="default_engine", value="whisper")
        assert pref.key == "default_engine"
        assert pref.value == "whisper"
        assert pref.updated_at is not None


# =============================================================================
# 2. Database Connection & Schema Initialization Tests
# =============================================================================


class TestDatabaseConnection:
    def test_default_db_path_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PODCAST_CLI_DB_PATH", raising=False)
        default_path = get_default_db_path()
        assert default_path == DEFAULT_DB_DIR / DEFAULT_DB_FILE

        monkeypatch.setenv("PODCAST_CLI_DB_PATH", "/tmp/custom_podcast.db")
        custom_path = get_default_db_path()
        assert custom_path == Path("/tmp/custom_podcast.db")

    def test_in_memory_database_creation(self) -> None:
        db = Database(":memory:")
        assert db.is_memory is True
        db.init_schema()

        with db.connection() as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            assert {"shows", "episodes", "transcripts", "knowledge_mappings", "preferences"}.issubset(tables)

        db.close()

    def test_pragmas_applied(self, tmp_path: Path) -> None:
        db_file = tmp_path / "pragmas_test.db"
        db = Database(db_file)
        db.init_schema()

        with db.connection() as conn:
            foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]

            assert foreign_keys == 1
            assert journal_mode.lower() == "wal"
            assert synchronous == 1  # NORMAL is 1 in SQLite

        db.close()

    def test_transaction_rollback_on_error(self) -> None:
        db = Database(":memory:")
        db.init_schema()

        with pytest.raises(sqlite3.OperationalError):
            with db.connection() as conn:
                conn.execute("INSERT INTO preferences (key, value_json) VALUES ('key1', '\"val1\"')")
                # Trigger SQL syntax error
                conn.execute("INVALID SQL SYNTAX THAT FAILS")

        with db.connection() as conn:
            row = conn.execute("SELECT * FROM preferences WHERE key = 'key1'").fetchone()
            assert row is None


# =============================================================================
# 3. StorageRepository Shows CRUD Tests
# =============================================================================


class TestRepositoryShows:
    def test_save_and_get_show_by_id_and_feed(self, memory_repo: StorageRepository) -> None:
        show_data = {
            "id": "lex-fridman",
            "title": "Lex Fridman Podcast",
            "feed_url": "https://lexfridman.com/feed/podcast/",
            "author": "Lex Fridman",
            "categories": ["Technology", "Science"],
        }
        memory_repo.save_show(show_data)

        # Retrieve by ID
        by_id = memory_repo.get_show("lex-fridman")
        assert by_id is not None
        assert by_id["id"] == "lex-fridman"
        assert by_id["title"] == "Lex Fridman Podcast"
        assert by_id["feed_url"] == "https://lexfridman.com/feed/podcast/"
        assert by_id["metadata"]["author"] == "Lex Fridman"

        # Retrieve by feed_url
        by_feed = memory_repo.get_show("https://lexfridman.com/feed/podcast/")
        assert by_feed is not None
        assert by_feed["id"] == "lex-fridman"

    def test_save_show_upsert_update(self, memory_repo: StorageRepository) -> None:
        memory_repo.save_show("huberman", title="Huberman Lab", feed_url="https://huberman.com/feed")
        initial = memory_repo.get_show("huberman")
        assert initial is not None
        assert initial["title"] == "Huberman Lab"

        # Update title
        memory_repo.save_show("huberman", title="Huberman Lab Updated", feed_url="https://huberman.com/feed_v2")
        updated = memory_repo.get_show("huberman")
        assert updated is not None
        assert updated["title"] == "Huberman Lab Updated"
        assert updated["feed_url"] == "https://huberman.com/feed_v2"

    def test_list_shows(self, memory_repo: StorageRepository) -> None:
        memory_repo.save_show({"id": "show-1", "title": "Show 1", "feed_url": "https://s1.com/feed"})
        memory_repo.save_show({"id": "show-2", "title": "Show 2", "feed_url": "https://s2.com/feed"})

        shows = memory_repo.list_shows()
        assert len(shows) == 2
        ids = {s["id"] for s in shows}
        assert ids == {"show-1", "show-2"}

    def test_delete_show(self, memory_repo: StorageRepository) -> None:
        memory_repo.save_show({"id": "to-delete", "title": "Delete Me"})
        assert memory_repo.get_show("to-delete") is not None

        deleted = memory_repo.delete_show("to-delete")
        assert deleted is True
        assert memory_repo.get_show("to-delete") is None

        # Deleting non-existent returns False
        assert memory_repo.delete_show("non-existent") is False


# =============================================================================
# 4. StorageRepository Episodes CRUD Tests
# =============================================================================


class TestRepositoryEpisodes:
    def test_save_and_get_episode_from_model(
        self, memory_repo: StorageRepository, sample_metadata: EpisodeMetadata
    ) -> None:
        memory_repo.save_episode(sample_metadata)

        ep = memory_repo.get_episode("tech-frontier", "ep-42-ai")
        assert ep is not None
        assert ep["id"] == "ep-42-ai"
        assert ep["show_id"] == "tech-frontier"
        assert ep["title"] == "Episode 42: Future of AI"
        assert ep["duration"] == 3600.0
        assert ep["audio_url"] == "https://example.com/audio/ep42.mp3"
        assert ep["published_date"] == "2026-09-01T12:00:00Z"
        assert ep["metadata"]["show_title"] == "Tech Frontier"

    def test_save_episode_from_dict(self, memory_repo: StorageRepository) -> None:
        ep_dict = {
            "show_id": "my-show",
            "id": "ep-1",
            "title": "Introduction",
            "duration": 120.0,
            "audio_url": "https://audio.example.com/1.mp3",
            "published_date": "2026-01-01",
        }
        memory_repo.save_episode(ep_dict)

        ep = memory_repo.get_episode("my-show", "ep-1")
        assert ep is not None
        assert ep["title"] == "Introduction"
        assert ep["duration"] == 120.0


# =============================================================================
# 5. StorageRepository Transcripts Cache Tests
# =============================================================================


class TestRepositoryTranscripts:
    def test_save_and_get_transcript(
        self, memory_repo: StorageRepository, sample_transcript_result: TranscriptResult
    ) -> None:
        memory_repo.save_transcript(sample_transcript_result)

        # Retrieve transcript
        cached = memory_repo.get_transcript("tech-frontier", "ep-42-ai")
        assert cached is not None
        assert cached.metadata.episode_title == "Episode 42: Future of AI"
        assert cached.tier_used == "rss"
        assert len(cached.segments) == 3
        assert cached.segments[0].text == "Welcome to the podcast."
        assert cached.segments[1].speaker == "Host"
        assert cached.segments[2].confidence == 0.92
        assert cached.raw_text == sample_transcript_result.raw_text

        # Also verifies that episode metadata was saved
        ep = memory_repo.get_episode("tech-frontier", "ep-42-ai")
        assert ep is not None
        assert ep["title"] == "Episode 42: Future of AI"

    def test_save_transcript_upsert_overwrite(
        self, memory_repo: StorageRepository, sample_transcript_result: TranscriptResult
    ) -> None:
        memory_repo.save_transcript(sample_transcript_result)
        first_get = memory_repo.get_transcript("tech-frontier", "ep-42-ai")
        assert first_get is not None
        assert first_get.tier_used == "rss"

        # Overwrite with whisper tier
        updated_result = sample_transcript_result.model_copy(
            update={"tier_used": "whisper", "raw_text": "Updated whisper text"}
        )
        memory_repo.save_transcript(updated_result)

        second_get = memory_repo.get_transcript("tech-frontier", "ep-42-ai")
        assert second_get is not None
        assert second_get.tier_used == "whisper"
        assert second_get.raw_text == "Updated whisper text"

    def test_list_transcripts_filtered_and_unfiltered(
        self, memory_repo: StorageRepository, sample_metadata: EpisodeMetadata
    ) -> None:
        res1 = TranscriptResult(
            metadata=sample_metadata.model_copy(update={"episode_id": "ep-1", "show_id": "show-A"}),
            segments=[],
            tier_used="rss",
            raw_text="Show A Ep 1",
        )
        res2 = TranscriptResult(
            metadata=sample_metadata.model_copy(update={"episode_id": "ep-2", "show_id": "show-A"}),
            segments=[],
            tier_used="youtube",
            raw_text="Show A Ep 2",
        )
        res3 = TranscriptResult(
            metadata=sample_metadata.model_copy(update={"episode_id": "ep-1", "show_id": "show-B"}),
            segments=[],
            tier_used="whisper",
            raw_text="Show B Ep 1",
        )

        memory_repo.save_transcript(res1)
        memory_repo.save_transcript(res2)
        memory_repo.save_transcript(res3)

        # List all
        all_transcripts = memory_repo.list_transcripts()
        assert len(all_transcripts) == 3

        # List filtered by show
        show_a_transcripts = memory_repo.list_transcripts("show-A")
        assert len(show_a_transcripts) == 2
        assert {t.metadata.episode_id for t in show_a_transcripts} == {"ep-1", "ep-2"}

        show_b_transcripts = memory_repo.list_transcripts("show-B")
        assert len(show_b_transcripts) == 1
        assert show_b_transcripts[0].metadata.episode_id == "ep-1"

    def test_delete_transcript(
        self, memory_repo: StorageRepository, sample_transcript_result: TranscriptResult
    ) -> None:
        memory_repo.save_transcript(sample_transcript_result)
        assert memory_repo.get_transcript("tech-frontier", "ep-42-ai") is not None

        deleted = memory_repo.delete_transcript("tech-frontier", "ep-42-ai")
        assert deleted is True
        assert memory_repo.get_transcript("tech-frontier", "ep-42-ai") is None

        # Deleting non-existent returns False
        assert memory_repo.delete_transcript("tech-frontier", "ep-42-ai") is False

    def test_clear_cache(
        self, memory_repo: StorageRepository, sample_metadata: EpisodeMetadata
    ) -> None:
        res1 = TranscriptResult(
            metadata=sample_metadata.model_copy(update={"episode_id": "ep-1", "show_id": "show-A"}),
            segments=[],
            tier_used="rss",
            raw_text="A1",
        )
        res2 = TranscriptResult(
            metadata=sample_metadata.model_copy(update={"episode_id": "ep-2", "show_id": "show-A"}),
            segments=[],
            tier_used="rss",
            raw_text="A2",
        )
        res3 = TranscriptResult(
            metadata=sample_metadata.model_copy(update={"episode_id": "ep-1", "show_id": "show-B"}),
            segments=[],
            tier_used="rss",
            raw_text="B1",
        )

        memory_repo.save_transcript(res1)
        memory_repo.save_transcript(res2)
        memory_repo.save_transcript(res3)

        # Clear only show-A
        deleted_count = memory_repo.clear_cache(show_id="show-A")
        assert deleted_count == 2
        assert len(memory_repo.list_transcripts("show-A")) == 0
        assert len(memory_repo.list_transcripts("show-B")) == 1

        # Clear remaining
        total_cleared = memory_repo.clear_cache()
        assert total_cleared == 1
        assert len(memory_repo.list_transcripts()) == 0


# =============================================================================
# 6. StorageRepository Knowledge Mapping Tests
# =============================================================================


class TestRepositoryMappings:
    def test_show_mapping_crud(self, memory_repo: StorageRepository) -> None:
        mapping = ShowMapping(
            feed_url="https://lexfridman.com/feed/podcast/",
            show_title="Lex Fridman Podcast",
            youtube_channel_url="https://youtube.com/@lexfridman",
            custom_settings={"preferred_tier": "youtube"},
        )
        memory_repo.save_show_mapping(mapping)

        # Get
        retrieved = memory_repo.get_show_mapping("https://lexfridman.com/feed/podcast/")
        assert retrieved is not None
        assert retrieved.feed_url == "https://lexfridman.com/feed/podcast/"
        assert retrieved.show_title == "Lex Fridman Podcast"
        assert retrieved.youtube_channel_url == "https://youtube.com/@lexfridman"
        assert retrieved.custom_settings == {"preferred_tier": "youtube"}

        # List
        mappings = memory_repo.list_show_mappings()
        assert len(mappings) == 1
        assert mappings[0].show_title == "Lex Fridman Podcast"

        # Delete
        deleted = memory_repo.delete_show_mapping("https://lexfridman.com/feed/podcast/")
        assert deleted is True
        assert memory_repo.get_show_mapping("https://lexfridman.com/feed/podcast/") is None

    def test_episode_mapping_crud(self, memory_repo: StorageRepository) -> None:
        mapping1 = EpisodeMapping(
            show_id="lex-fridman",
            episode_id="400",
            youtube_video_url="https://youtube.com/watch?v=ep400",
            confirmed_by_user=True,
        )
        mapping2 = EpisodeMapping(
            show_id="lex-fridman",
            episode_id="401",
            youtube_video_url="https://youtube.com/watch?v=ep401",
            confirmed_by_user=False,
        )
        mapping3 = EpisodeMapping(
            show_id="huberman-lab",
            episode_id="150",
            youtube_video_url="https://youtube.com/watch?v=hl150",
            confirmed_by_user=True,
        )

        memory_repo.save_episode_mapping(mapping1)
        memory_repo.save_episode_mapping(mapping2)
        memory_repo.save_episode_mapping(mapping3)

        # Get
        retrieved = memory_repo.get_episode_mapping("lex-fridman", "400")
        assert retrieved is not None
        assert retrieved.show_id == "lex-fridman"
        assert retrieved.episode_id == "400"
        assert retrieved.youtube_video_url == "https://youtube.com/watch?v=ep400"
        assert retrieved.confirmed_by_user is True

        # List filtered
        lex_mappings = memory_repo.list_episode_mappings(show_id="lex-fridman")
        assert len(lex_mappings) == 2
        assert {m.episode_id for m in lex_mappings} == {"400", "401"}

        # List all
        all_mappings = memory_repo.list_episode_mappings()
        assert len(all_mappings) == 3

        # Delete
        deleted = memory_repo.delete_episode_mapping("lex-fridman", "400")
        assert deleted is True
        assert memory_repo.get_episode_mapping("lex-fridman", "400") is None
        assert len(memory_repo.list_episode_mappings(show_id="lex-fridman")) == 1


# =============================================================================
# 7. StorageRepository User Preferences Tests
# =============================================================================


class TestRepositoryPreferences:
    def test_set_and_get_primitive_preferences(self, memory_repo: StorageRepository) -> None:
        memory_repo.set_preference("default_engine", "whisper")
        memory_repo.set_preference("auto_approve_cost", 0.05)
        memory_repo.set_preference("enable_color", True)

        assert memory_repo.get_preference("default_engine") == "whisper"
        assert memory_repo.get_preference("auto_approve_cost") == pytest.approx(0.05)
        assert memory_repo.get_preference("enable_color") is True

    def test_set_and_get_complex_preferences(self, memory_repo: StorageRepository) -> None:
        formats = ["markdown", "srt", "json"]
        settings = {"groq_api_key": "sec_123", "retry_limit": 3}

        memory_repo.set_preference("output_formats", formats)
        memory_repo.set_preference("engine_settings", settings)

        assert memory_repo.get_preference("output_formats") == formats
        assert memory_repo.get_preference("engine_settings") == settings

    def test_set_preference_using_model(self, memory_repo: StorageRepository) -> None:
        pref = UserPreference(key="model_size", value="large-v3")
        memory_repo.set_preference(pref)
        assert memory_repo.get_preference("model_size") == "large-v3"

    def test_get_preference_default_fallback(self, memory_repo: StorageRepository) -> None:
        assert memory_repo.get_preference("non_existent_key") is None
        assert memory_repo.get_preference("non_existent_key", default="fallback_val") == "fallback_val"

    def test_delete_and_list_preferences(self, memory_repo: StorageRepository) -> None:
        memory_repo.set_preference("pref1", "val1")
        memory_repo.set_preference("pref2", "val2")

        prefs = memory_repo.list_preferences()
        assert prefs == {"pref1": "val1", "pref2": "val2"}

        deleted = memory_repo.delete_preference("pref1")
        assert deleted is True
        assert memory_repo.get_preference("pref1") is None
        assert memory_repo.list_preferences() == {"pref2": "val2"}


# =============================================================================
# 8. Temporary Disk Database & Cache Stats Tests
# =============================================================================


class TestDiskDatabaseAndStats:
    def test_disk_repository_persistence_and_stats(
        self, temp_disk_repo: StorageRepository, sample_transcript_result: TranscriptResult
    ) -> None:
        temp_disk_repo.save_show({"id": "disk-show", "title": "Disk Show"})
        temp_disk_repo.save_transcript(sample_transcript_result)
        temp_disk_repo.save_show_mapping(
            ShowMapping(feed_url="https://disk.rss", show_title="Disk Show")
        )
        temp_disk_repo.set_preference("disk_pref", "active")

        stats = temp_disk_repo.get_cache_stats()
        assert stats["shows_count"] >= 1
        assert stats["transcripts_count"] == 1
        assert stats["mappings_count"] == 1
        assert stats["preferences_count"] == 1
        assert stats["size_bytes"] > 0
        assert "test_podcast.db" in stats["database_path"]
