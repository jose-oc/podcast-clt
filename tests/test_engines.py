"""Comprehensive unit tests for transcription engines, parsers, and dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest
import respx

from podcast_ctl.engines import (
    BaseTranscriptionEngine,
    CloudTranscriptionEngine,
    EngineUnavailableError,
    RSSTranscriptionEngine,
    TranscriptionDispatcher,
    TranscriptionEngineError,
    TranscriptNotFoundError,
    WhisperTranscriptionEngine,
    YouTubeTranscriptionEngine,
    detect_optimal_device_and_compute_type,
    extract_youtube_video_id,
    parse_json_transcript,
    parse_plain_text,
    parse_srt_content,
    parse_timestamp_seconds,
    parse_vtt_content,
)
from podcast_ctl.models import (
    EpisodeMapping,
    EpisodeMetadata,
    TranscriptResult,
    TranscriptSegment,
)
from podcast_ctl.storage import Database, StorageRepository

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def memory_repo() -> StorageRepository:
    """Provides an in-memory StorageRepository."""
    return StorageRepository(Database(":memory:"))


@pytest.fixture
def sample_episode() -> EpisodeMetadata:
    """Sample podcast episode metadata."""
    return EpisodeMetadata(
        show_title="Syntax FM",
        episode_title="Episode 500: Rust for JS Devs",
        episode_id="syntax-500",
        show_id="syntax",
        audio_url="https://audio.example.com/syntax500.mp3",
        duration_seconds=3600.0,
        published_date="2026-09-01T00:00:00Z",
        rss_transcripts=[
            {
                "url": "https://example.com/transcripts/syntax500.json",
                "type": "application/json",
            },
            {
                "url": "https://example.com/transcripts/syntax500.vtt",
                "type": "text/vtt",
            },
        ],
        source_type="rss",
    )


# =============================================================================
# 1. Base Engine & Exception Tests
# =============================================================================


class TestBaseEngineAndExceptions:
    def test_exception_hierarchy(self) -> None:
        assert issubclass(EngineUnavailableError, TranscriptionEngineError)
        assert issubclass(TranscriptNotFoundError, TranscriptionEngineError)
        assert issubclass(TranscriptionEngineError, Exception)

    def test_base_engine_abstract(self) -> None:
        class DummyEngine(BaseTranscriptionEngine):
            pass

        with pytest.raises(TypeError):
            DummyEngine()  # type: ignore


# =============================================================================
# 2. RSS Engine Parser Unit Tests
# =============================================================================


class TestRSSParsers:
    def test_parse_timestamp_seconds(self) -> None:
        assert parse_timestamp_seconds("00:00:05.500") == 5.5
        assert parse_timestamp_seconds("00:01:23.456") == 83.456
        assert parse_timestamp_seconds("01:23.456") == 83.456
        assert parse_timestamp_seconds("00:00:05,500") == 5.5  # SRT comma format
        assert parse_timestamp_seconds("01:02:03,123") == 3723.123
        assert parse_timestamp_seconds("42.5") == 42.5

        with pytest.raises(ValueError):
            parse_timestamp_seconds("invalid:timestamp:format:too:long")

    def test_parse_vtt_content(self) -> None:
        vtt_sample = """WEBVTT - Syntax 500

NOTE This is a commentary note that should be ignored.

STYLE
::cue { color: yellow; }

00:00:01.000 --> 00:00:04.500
<v Wes Bos>Welcome to Syntax podcast!</v>

00:00:04.500 --> 00:00:08.200 align:start size:50%
<v Scott Tolinski>Today we are talking about Rust.

00:00:08.500 --> 00:00:12.000
Guest: It is exciting to be here!
"""
        segments = parse_vtt_content(vtt_sample)
        assert len(segments) == 3

        assert segments[0].start == 1.0
        assert segments[0].end == 4.5
        assert segments[0].text == "Welcome to Syntax podcast!"
        assert segments[0].speaker == "Wes Bos"

        assert segments[1].start == 4.5
        assert segments[1].end == 8.2
        assert segments[1].text == "Today we are talking about Rust."
        assert segments[1].speaker == "Scott Tolinski"

        assert segments[2].start == 8.5
        assert segments[2].end == 12.0
        assert segments[2].text == "It is exciting to be here!"
        assert segments[2].speaker == "Guest"

    def test_parse_srt_content(self) -> None:
        srt_sample = """1
00:00:01,000 --> 00:00:04,500
[Host] Hello and welcome to the episode.

2
00:00:04,500 --> 00:00:09,000
Guest: Thank you for inviting me.
We will have a great discussion.
"""
        segments = parse_srt_content(srt_sample)
        assert len(segments) == 2

        assert segments[0].start == 1.0
        assert segments[0].end == 4.5
        assert segments[0].text == "Hello and welcome to the episode."
        assert segments[0].speaker == "Host"

        assert segments[1].start == 4.5
        assert segments[1].end == 9.0
        assert "Thank you for inviting me. We will have a great discussion." in segments[1].text
        assert segments[1].speaker == "Guest"

    def test_parse_json_transcript_podcasting_2(self) -> None:
        json_sample = {
            "version": "1.0.0",
            "segments": [
                {
                    "startTime": 0.5,
                    "endTime": 3.8,
                    "body": "Podcasting 2.0 JSON standard",
                    "speaker": "Alice",
                },
                {
                    "startTime": "00:00:04.000",
                    "endTime": "00:00:07.500",
                    "body": "Second segment text",
                    "speaker": "Bob",
                },
            ],
        }
        segments = parse_json_transcript(json_sample)
        assert len(segments) == 2
        assert segments[0].start == 0.5
        assert segments[0].end == 3.8
        assert segments[0].text == "Podcasting 2.0 JSON standard"
        assert segments[0].speaker == "Alice"

        assert segments[1].start == 4.0
        assert segments[1].end == 7.5
        assert segments[1].text == "Second segment text"
        assert segments[1].speaker == "Bob"

    def test_parse_json_transcript_whisper_and_words_format(self) -> None:
        # Standard start/end/text format
        json_sample = [
            {"start": 1.0, "duration": 2.0, "text": "Segment one", "speaker": "Host"},
            {"start": 3.0, "end": 5.5, "text": "Segment two", "confidence": 0.95},
        ]
        segments = parse_json_transcript(json_sample)
        assert len(segments) == 2
        assert segments[0].start == 1.0
        assert segments[0].end == 3.0
        assert segments[0].text == "Segment one"
        assert segments[0].speaker == "Host"

        assert segments[1].start == 3.0
        assert segments[1].end == 5.5
        assert segments[1].text == "Segment two"
        assert segments[1].confidence == 0.95

    def test_parse_plain_text(self) -> None:
        text_sample = "Paragraph 1: Welcome.\n\nParagraph 2: Second section."
        segments = parse_plain_text(text_sample, default_duration=100.0)
        assert len(segments) == 2
        assert segments[0].start == 0.0
        assert segments[0].end == 50.0
        assert segments[0].text == "Paragraph 1: Welcome."
        assert segments[1].start == 50.0
        assert segments[1].end == 100.0


# =============================================================================
# 3. RSSTranscriptionEngine Integration Tests
# =============================================================================


class TestRSSTranscriptionEngine:
    @respx.mock
    @pytest.mark.asyncio
    async def test_rss_engine_priority_and_success(self, sample_episode: EpisodeMetadata) -> None:
        json_content = json.dumps({
            "version": "1.0.0",
            "segments": [
                {"startTime": 0.0, "endTime": 5.0, "body": "JSON transcript content", "speaker": "Wes"}
            ],
        })

        respx.get("https://example.com/transcripts/syntax500.json").respond(
            200, text=json_content, headers={"Content-Type": "application/json"}
        )

        engine = RSSTranscriptionEngine()
        assert engine.is_available() is True

        result = await engine.transcribe(sample_episode)
        assert isinstance(result, TranscriptResult)
        assert result.tier_used == "rss"
        assert len(result.segments) == 1
        assert result.segments[0].text == "JSON transcript content"
        assert result.segments[0].speaker == "Wes"

    @respx.mock
    @pytest.mark.asyncio
    async def test_rss_engine_fallback_when_first_candidate_fails(
        self, sample_episode: EpisodeMetadata
    ) -> None:
        # JSON candidate fails with 404
        respx.get("https://example.com/transcripts/syntax500.json").respond(404)
        # VTT candidate succeeds
        vtt_content = "WEBVTT\n\n00:00:01.000 --> 00:00:05.000\nFallback VTT text\n"
        respx.get("https://example.com/transcripts/syntax500.vtt").respond(
            200, text=vtt_content, headers={"Content-Type": "text/vtt"}
        )

        engine = RSSTranscriptionEngine()
        result = await engine.transcribe(sample_episode)
        assert result.tier_used == "rss"
        assert len(result.segments) == 1
        assert result.segments[0].text == "Fallback VTT text"

    @pytest.mark.asyncio
    async def test_rss_engine_no_transcripts_raises(self) -> None:
        ep_no_transcripts = EpisodeMetadata(
            show_title="Test",
            episode_title="No transcripts",
            episode_id="ep-none",
            rss_transcripts=[],
        )
        engine = RSSTranscriptionEngine()
        with pytest.raises(TranscriptNotFoundError, match="No RSS transcripts available"):
            await engine.transcribe(ep_no_transcripts)


# =============================================================================
# 4. YouTubeTranscriptionEngine Unit Tests
# =============================================================================


class TestYouTubeEngine:
    def test_extract_youtube_video_id(self) -> None:
        assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("https://example.com/not_youtube") is None

    @pytest.mark.asyncio
    async def test_youtube_transcribe_via_transcript_api_mock(self) -> None:
        episode = EpisodeMetadata(
            show_title="Huberman Lab",
            episode_title="Episode 100",
            episode_id="dQw4w9WgXcQ",
            audio_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            source_type="youtube",
        )

        engine = YouTubeTranscriptionEngine()

        with patch.object(engine, "_fetch_via_youtube_transcript_api", return_value=[
            TranscriptSegment(start=0.0, end=4.5, text="Welcome to Huberman Lab.", speaker="Host"),
            TranscriptSegment(start=4.5, end=9.5, text="Today we discuss dopamine."),
        ]):
            result = await engine.transcribe(episode)
            assert result.tier_used == "youtube"
            assert len(result.segments) == 2
            assert result.segments[0].speaker == "Host"
            assert result.segments[1].text == "Today we discuss dopamine."

    @pytest.mark.asyncio
    async def test_youtube_transcribe_not_found(self) -> None:
        episode = EpisodeMetadata(
            show_title="Show",
            episode_title="Episode",
            episode_id="not_a_valid_youtube_url",
            audio_url="https://audio.example.com/file.mp3",
        )
        engine = YouTubeTranscriptionEngine()
        with pytest.raises(TranscriptNotFoundError, match="No YouTube video ID"):
            await engine.transcribe(episode)


# =============================================================================
# 5. WhisperTranscriptionEngine Unit Tests
# =============================================================================


class TestWhisperEngine:
    def test_detect_optimal_device_and_compute(self) -> None:
        device, compute = detect_optimal_device_and_compute_type()
        assert device in ("cuda", "cpu")
        assert compute in ("float16", "int8", "default")

    @pytest.mark.asyncio
    async def test_whisper_engine_transcribe_mock(
        self, sample_episode: EpisodeMetadata, tmp_path: Path
    ) -> None:
        engine = WhisperTranscriptionEngine(default_model_size="base")

        # Mock audio download and conversion
        dummy_wav = tmp_path / "dummy.wav"
        dummy_wav.write_bytes(b"RIFFdummywavbytes")

        mock_segments = [
            TranscriptSegment(start=0.0, end=4.2, text="Local Whisper segment 1", confidence=0.96),
            TranscriptSegment(start=4.2, end=8.5, text="Local Whisper segment 2", confidence=0.94),
        ]

        with patch.object(engine, "is_available", return_value=True), \
             patch.object(engine, "_download_audio", new_callable=AsyncMock), \
             patch.object(engine, "_convert_to_wav", new_callable=AsyncMock, return_value=True), \
             patch.object(engine, "_run_transcription", return_value=mock_segments):

            result = await engine.transcribe(sample_episode)
            assert result.tier_used == "whisper"
            assert len(result.segments) == 2
            assert result.segments[0].text == "Local Whisper segment 1"
            assert result.segments[0].confidence == 0.96


# =============================================================================
# 6. CloudTranscriptionEngine Unit Tests
# =============================================================================


class TestCloudEngine:
    def test_cloud_engine_availability_and_properties(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_123")
        engine_groq = CloudTranscriptionEngine(provider="groq")
        assert engine_groq.is_available() is True
        assert engine_groq.api_key == "gsk_test_key_123"
        assert urlparse(engine_groq.endpoint_url).hostname == "api.groq.com"
        assert engine_groq.default_model == "whisper-large-v3"

        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-key-456")
        engine_openai = CloudTranscriptionEngine(provider="openai")
        assert engine_openai.is_available() is True
        assert engine_openai.api_key == "sk-openai-key-456"
        assert urlparse(engine_openai.endpoint_url).hostname == "api.openai.com"
        assert engine_openai.default_model == "whisper-1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_cloud_transcribe_verbose_json_response(
        self, sample_episode: EpisodeMetadata, tmp_path: Path
    ) -> None:
        # Create a local audio file
        audio_file = tmp_path / "test_audio.mp3"
        audio_file.write_bytes(b"FAKE_AUDIO_DATA")

        cloud_resp = {
            "task": "transcribe",
            "language": "english",
            "duration": 15.0,
            "text": "Hello world from Groq Cloud.",
            "segments": [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 7.5,
                    "text": "Hello world",
                    "avg_logprob": -0.05,
                },
                {
                    "id": 1,
                    "start": 7.5,
                    "end": 15.0,
                    "text": "from Groq Cloud.",
                    "avg_logprob": -0.08,
                },
            ],
        }

        respx.post("https://api.groq.com/openai/v1/audio/transcriptions").respond(
            200, json=cloud_resp
        )

        engine = CloudTranscriptionEngine(provider="groq", api_key="gsk_mock_key")
        result = await engine.transcribe(sample_episode, audio_path=str(audio_file))

        assert result.tier_used == "cloud"
        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello world"
        assert result.segments[1].text == "from Groq Cloud."
        assert result.raw_text == "Hello world from Groq Cloud."


# =============================================================================
# 7. TranscriptionDispatcher Tests
# =============================================================================


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(
        self, memory_repo: StorageRepository, sample_episode: EpisodeMetadata
    ) -> None:
        cached_result = TranscriptResult(
            metadata=sample_episode,
            segments=[TranscriptSegment(start=0.0, end=10.0, text="Cached transcript text")],
            tier_used="rss",
            raw_text="Cached transcript text",
        )
        memory_repo.save_transcript(cached_result)

        dispatcher = TranscriptionDispatcher(storage_repo=memory_repo)

        # Transcribe should immediately return cached result without calling engines
        result = await dispatcher.transcribe(sample_episode)
        assert result.tier_used == "rss"
        assert result.raw_text == "Cached transcript text"

    @pytest.mark.asyncio
    async def test_force_bypasses_and_overwrites_cache(
        self, memory_repo: StorageRepository, sample_episode: EpisodeMetadata
    ) -> None:
        old_cached = TranscriptResult(
            metadata=sample_episode,
            segments=[TranscriptSegment(start=0.0, end=10.0, text="Old cached text")],
            tier_used="rss",
        )
        memory_repo.save_transcript(old_cached)

        # Mock engines in dispatcher
        mock_rss = MagicMock(spec=RSSTranscriptionEngine)
        mock_rss.is_available.return_value = True
        mock_rss.transcribe = AsyncMock(
            return_value=TranscriptResult(
                metadata=sample_episode,
                segments=[TranscriptSegment(start=0.0, end=10.0, text="Fresh transcribed text")],
                tier_used="rss",
            )
        )

        dispatcher = TranscriptionDispatcher(
            storage_repo=memory_repo,
            engines={"rss": mock_rss},
        )

        result = await dispatcher.transcribe(sample_episode, force=True)
        assert result.raw_text == "Fresh transcribed text"
        mock_rss.transcribe.assert_awaited_once()

        # Cache should now have fresh result
        cached_new = memory_repo.get_transcript(sample_episode.effective_show_id, sample_episode.episode_id)
        assert cached_new is not None
        assert cached_new.raw_text == "Fresh transcribed text"

    @pytest.mark.asyncio
    async def test_auto_fallback_hierarchy(
        self, memory_repo: StorageRepository, sample_episode: EpisodeMetadata
    ) -> None:
        # Mock Tier 1 (RSS) failing, Tier 2 (YouTube) failing, Tier 3 (Whisper) succeeding
        mock_rss = MagicMock(spec=RSSTranscriptionEngine)
        mock_rss.is_available.return_value = True
        mock_rss.transcribe = AsyncMock(side_effect=TranscriptNotFoundError("No RSS transcripts"))

        mock_youtube = MagicMock(spec=YouTubeTranscriptionEngine)
        mock_youtube.is_available.return_value = True
        mock_youtube.transcribe = AsyncMock(side_effect=TranscriptNotFoundError("No YouTube captions"))

        mock_whisper = MagicMock(spec=WhisperTranscriptionEngine)
        mock_whisper.is_available.return_value = True
        mock_whisper.transcribe = AsyncMock(
            return_value=TranscriptResult(
                metadata=sample_episode,
                segments=[TranscriptSegment(start=0.0, end=5.0, text="Whisper fallback text")],
                tier_used="whisper",
            )
        )

        mock_cloud = MagicMock(spec=CloudTranscriptionEngine)
        mock_cloud.is_available.return_value = True
        mock_cloud.transcribe = AsyncMock()

        dispatcher = TranscriptionDispatcher(
            storage_repo=memory_repo,
            engines={
                "rss": mock_rss,
                "youtube": mock_youtube,
                "whisper": mock_whisper,
                "cloud": mock_cloud,
            },
        )

        result = await dispatcher.transcribe(sample_episode, engine="auto")
        assert result.tier_used == "whisper"
        assert result.raw_text == "Whisper fallback text"

        mock_rss.transcribe.assert_awaited_once()
        mock_youtube.transcribe.assert_awaited_once()
        mock_whisper.transcribe.assert_awaited_once()
        mock_cloud.transcribe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_engine_override_specific(
        self, memory_repo: StorageRepository, sample_episode: EpisodeMetadata
    ) -> None:
        mock_rss = MagicMock(spec=RSSTranscriptionEngine)
        mock_rss.is_available.return_value = True
        mock_rss.transcribe = AsyncMock()

        mock_cloud = MagicMock(spec=CloudTranscriptionEngine)
        mock_cloud.is_available.return_value = True
        mock_cloud.transcribe = AsyncMock(
            return_value=TranscriptResult(
                metadata=sample_episode,
                segments=[TranscriptSegment(start=0.0, end=5.0, text="Explicit Groq result")],
                tier_used="cloud",
            )
        )

        dispatcher = TranscriptionDispatcher(
            storage_repo=memory_repo,
            engines={
                "rss": mock_rss,
                "groq": mock_cloud,
                "cloud": mock_cloud,
            },
        )

        result = await dispatcher.transcribe(sample_episode, engine="groq")
        assert result.tier_used == "cloud"
        assert result.raw_text == "Explicit Groq result"

        mock_rss.transcribe.assert_not_awaited()
        mock_cloud.transcribe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_knowledge_mapping_youtube_url_injection(
        self, memory_repo: StorageRepository, sample_episode: EpisodeMetadata
    ) -> None:
        # Save episode mapping in repository
        mapping = EpisodeMapping(
            show_id=sample_episode.effective_show_id,
            episode_id=sample_episode.episode_id,
            youtube_video_url="https://www.youtube.com/watch?v=mappedVideo123",
        )
        memory_repo.save_episode_mapping(mapping)

        mock_rss = MagicMock(spec=RSSTranscriptionEngine)
        mock_rss.is_available.return_value = True
        mock_rss.transcribe = AsyncMock(side_effect=TranscriptNotFoundError("No RSS"))

        mock_youtube = MagicMock(spec=YouTubeTranscriptionEngine)
        mock_youtube.is_available.return_value = True
        mock_youtube.transcribe = AsyncMock(
            return_value=TranscriptResult(
                metadata=sample_episode,
                segments=[TranscriptSegment(start=0.0, end=5.0, text="Mapped YouTube caption")],
                tier_used="youtube",
            )
        )

        dispatcher = TranscriptionDispatcher(
            storage_repo=memory_repo,
            engines={"rss": mock_rss, "youtube": mock_youtube},
        )

        result = await dispatcher.transcribe(sample_episode, engine="auto")
        assert result.tier_used == "youtube"

        # Verify youtube_url was passed to YouTube engine
        mock_youtube.transcribe.assert_awaited_once_with(
            sample_episode, youtube_url="https://www.youtube.com/watch?v=mappedVideo123"
        )

    @pytest.mark.asyncio
    async def test_all_engines_fail_raises_exception(
        self, memory_repo: StorageRepository, sample_episode: EpisodeMetadata
    ) -> None:
        mock_rss = MagicMock(spec=RSSTranscriptionEngine)
        mock_rss.is_available.return_value = True
        mock_rss.transcribe = AsyncMock(side_effect=TranscriptNotFoundError("RSS 404"))

        dispatcher = TranscriptionDispatcher(
            storage_repo=memory_repo,
            engines={"rss": mock_rss},
        )

        with pytest.raises(TranscriptionEngineError, match="All transcription engines failed"):
            await dispatcher.transcribe(sample_episode, engine="rss")

    @pytest.mark.asyncio
    async def test_bypass_cache_flag(
        self, memory_repo: StorageRepository, sample_episode: EpisodeMetadata
    ) -> None:
        cached_old = TranscriptResult(
            metadata=sample_episode,
            segments=[TranscriptSegment(start=0.0, end=1.0, text="Cached data")],
            tier_used="rss",
        )
        memory_repo.save_transcript(cached_old)

        mock_rss = MagicMock(spec=RSSTranscriptionEngine)
        mock_rss.is_available.return_value = True
        mock_rss.transcribe = AsyncMock(
            return_value=TranscriptResult(
                metadata=sample_episode,
                segments=[TranscriptSegment(start=0.0, end=1.0, text="Bypassed live data")],
                tier_used="rss",
            )
        )

        dispatcher = TranscriptionDispatcher(
            storage_repo=memory_repo,
            engines={"rss": mock_rss},
        )

        result = await dispatcher.transcribe(sample_episode, bypass_cache=True)
        assert result.raw_text == "Bypassed live data"

        # Cache in DB should remain the old cached data because write was bypassed
        db_cached = memory_repo.get_transcript(sample_episode.effective_show_id, sample_episode.episode_id)
        assert db_cached is not None
        assert db_cached.raw_text == "Cached data"

    def test_dispatcher_register_and_get_custom_engine(self, memory_repo: StorageRepository) -> None:
        dispatcher = TranscriptionDispatcher(storage_repo=memory_repo)

        class CustomEngine(BaseTranscriptionEngine):
            name = "custom"
            tier = "custom"
            def is_available(self) -> bool:
                return True
            async def transcribe(self, episode: EpisodeMetadata, **kwargs) -> TranscriptResult:
                return TranscriptResult(metadata=episode, segments=[], tier_used="custom")

        dispatcher.register_engine("custom", CustomEngine())
        engine = dispatcher.get_engine("custom")
        assert engine.name == "custom"
        assert "custom" in dispatcher.resolve_execution_chain("custom")

    def test_dispatcher_unknown_engine_raises(self, memory_repo: StorageRepository) -> None:
        dispatcher = TranscriptionDispatcher(storage_repo=memory_repo)
        with pytest.raises(EngineUnavailableError, match="Invalid engine 'nonexistent'"):
            dispatcher.resolve_execution_chain("nonexistent")


# =============================================================================
# 8. Extra Edge Case Tests for Parsers & Engines
# =============================================================================


class TestEdgeCases:
    def test_vtt_with_formatting_tags(self) -> None:
        vtt_text = """WEBVTT

00:00:01.000 --> 00:00:04.000
<b>Bold text</b> and <i>italic</i> with <c.yellow>color</c> and <v Speaker>Voice</v>
"""
        segments = parse_vtt_content(vtt_text)
        assert len(segments) == 1
        assert "Bold text and italic with color and Voice" in segments[0].text

    def test_parse_json_transcript_invalid_json(self) -> None:
        with pytest.raises(TranscriptionEngineError, match="Invalid JSON transcript"):
            parse_json_transcript("{malformed json here")

    @pytest.mark.asyncio
    async def test_cloud_engine_http_error(
        self, sample_episode: EpisodeMetadata, tmp_path: Path
    ) -> None:
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"DATA")

        with respx.mock:
            respx.post("https://api.groq.com/openai/v1/audio/transcriptions").respond(
                401, text="Unauthorized: Invalid API key"
            )

            engine = CloudTranscriptionEngine(provider="groq", api_key="invalid_key")
            with pytest.raises(TranscriptionEngineError, match="Cloud API request failed \\(401\\)"):
                await engine.transcribe(sample_episode, audio_path=str(audio_file))

    @pytest.mark.asyncio
    async def test_cloud_engine_missing_key_raises(
        self, sample_episode: EpisodeMetadata, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        engine = CloudTranscriptionEngine(provider="groq", api_key=None)
        with pytest.raises(EngineUnavailableError, match="requires an API key"):
            await engine.transcribe(sample_episode)

    @pytest.mark.asyncio
    async def test_cloud_engine_raw_text_only_fallback(
        self, sample_episode: EpisodeMetadata, tmp_path: Path
    ) -> None:
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"DATA")

        with respx.mock:
            respx.post("https://api.groq.com/openai/v1/audio/transcriptions").respond(
                200, json={"text": "Plain text transcript without segments array.", "duration": 10.0}
            )

            engine = CloudTranscriptionEngine(provider="groq", api_key="mock_key")
            result = await engine.transcribe(sample_episode, audio_path=str(audio_file))
            assert len(result.segments) == 1
            assert result.segments[0].text == "Plain text transcript without segments array."
            assert result.segments[0].end == 10.0

    @pytest.mark.asyncio
    async def test_whisper_engine_no_audio_raises(self) -> None:
        ep_no_audio = EpisodeMetadata(
            show_title="Test",
            episode_title="Ep",
            episode_id="ep-1",
            audio_url=None,
        )
        engine = WhisperTranscriptionEngine()
        with patch.object(engine, "is_available", return_value=True):
            with pytest.raises(TranscriptionEngineError, match="No valid audio URL"):
                await engine.transcribe(ep_no_audio)

