"""Unit tests for Pre-Flight Gatekeeper and Interactive Knowledge Learning."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from podcast_ctl.gatekeeper import (
    KnowledgeLearner,
    PreFlightInspector,
    PreFlightSummary,
    estimate_cloud_cost,
    prompt_batch_confirmation,
    prompt_cloud_cost_approval,
    prompt_youtube_mapping,
)
from podcast_ctl.models import (
    EpisodeMetadata,
    TranscriptResult,
    TranscriptSegment,
)
from podcast_ctl.storage import Database, StorageRepository
from podcast_ctl.ui.console import UIConsole

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def memory_repo() -> StorageRepository:
    """Provides an in-memory StorageRepository."""
    return StorageRepository(Database(":memory:"))


@pytest.fixture
def test_console() -> UIConsole:
    """Provides a quiet UIConsole for test rendering without terminal pollution."""
    return UIConsole(record=True)


@pytest.fixture
def sample_episodes() -> list[EpisodeMetadata]:
    """Sample list of episodes with varied metadata."""
    return [
        EpisodeMetadata(
            show_title="Lex Fridman Podcast",
            episode_title="Episode 100: AI Safety",
            episode_id="lex-100",
            show_id="lex-fridman",
            audio_url="https://audio.example.com/lex100.mp3",
            duration_seconds=3600.0,  # 1 hour
            rss_transcripts=[{"url": "https://example.com/lex100.json", "type": "application/json"}],
            source_type="rss",
        ),
        EpisodeMetadata(
            show_title="Lex Fridman Podcast",
            episode_title="Episode 101: Robotics",
            episode_id="lex-101",
            show_id="lex-fridman",
            audio_url="https://audio.example.com/lex101.mp3",
            duration_seconds=1800.0,  # 30 minutes
            rss_transcripts=[],
            source_type="rss",
        ),
        EpisodeMetadata(
            show_title="Huberman Lab",
            episode_title="Episode 42: Sleep Science",
            episode_id="hl-42",
            show_id="huberman-lab",
            audio_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            duration_seconds=5400.0,  # 1.5 hours
            rss_transcripts=[],
            source_type="youtube",
        ),
        EpisodeMetadata(
            show_title="Indie Show",
            episode_title="Episode 1: Pilot",
            episode_id="indie-1",
            show_id="indie-show",
            audio_url="https://audio.example.com/indie1.mp3",
            duration_seconds=1200.0,  # 20 minutes
            rss_transcripts=[],
            source_type="rss",
        ),
    ]


# =============================================================================
# 1. PreFlightSummary Unit Tests
# =============================================================================


class TestPreFlightSummary:
    def test_default_summary(self) -> None:
        summary = PreFlightSummary()
        assert summary.total_episodes == 0
        assert summary.total_duration_seconds == 0.0
        assert summary.estimated_storage_mb == 0.0
        assert summary.tier_breakdown == {"cached": 0, "rss": 0, "youtube": 0, "whisper": 0, "cloud": 0}
        assert summary.episodes == []
        assert summary.formatted_duration == "0s"
        assert summary.formatted_storage == "0.0 MB"
        assert summary.requires_transcription is False

    def test_formatted_duration_formatting(self) -> None:
        # 45 seconds
        s1 = PreFlightSummary(total_duration_seconds=45.0)
        assert s1.formatted_duration == "45s"

        # 83 seconds (1m 23s)
        s2 = PreFlightSummary(total_duration_seconds=83.0)
        assert s2.formatted_duration == "1m 23s"

        # 3665 seconds (1h 1m 5s)
        s3 = PreFlightSummary(total_duration_seconds=3665.0)
        assert s3.formatted_duration == "1h 1m 5s"

        # 7200 seconds (2h 0m 0s)
        s4 = PreFlightSummary(total_duration_seconds=7200.0)
        assert s4.formatted_duration == "2h 0m 0s"

    def test_formatted_storage(self) -> None:
        s1 = PreFlightSummary(estimated_storage_mb=45.5)
        assert s1.formatted_storage == "45.5 MB"

        s2 = PreFlightSummary(estimated_storage_mb=1024.0)
        assert s2.formatted_storage == "1.00 GB"

        s3 = PreFlightSummary(estimated_storage_mb=2560.0)
        assert s3.formatted_storage == "2.50 GB"

    def test_property_counts_and_requires_transcription(self) -> None:
        summary = PreFlightSummary(
            total_episodes=5,
            tier_breakdown={"cached": 2, "rss": 1, "youtube": 1, "whisper": 1, "cloud": 0},
        )
        assert summary.cached_count == 2
        assert summary.rss_count == 1
        assert summary.youtube_count == 1
        assert summary.whisper_count == 1
        assert summary.cloud_count == 0
        assert summary.requires_transcription is True

        all_cached = PreFlightSummary(
            total_episodes=3,
            tier_breakdown={"cached": 3, "rss": 0, "youtube": 0, "whisper": 0, "cloud": 0},
        )
        assert all_cached.requires_transcription is False


# =============================================================================
# 2. PreFlightInspector Analysis Tests
# =============================================================================


class TestPreFlightInspector:
    def test_empty_episodes(self, memory_repo: StorageRepository) -> None:
        inspector = PreFlightInspector(repository=memory_repo)
        summary = inspector.inspect_episodes_sync([])
        assert summary.total_episodes == 0
        assert summary.total_duration_seconds == 0.0
        assert summary.estimated_storage_mb == 0.0
        assert summary.tier_breakdown == {"cached": 0, "rss": 0, "youtube": 0, "whisper": 0, "cloud": 0}

    def test_all_cached_episodes(
        self, memory_repo: StorageRepository, sample_episodes: list[EpisodeMetadata]
    ) -> None:
        # Cache all sample episodes
        for ep in sample_episodes:
            res = TranscriptResult(
                metadata=ep,
                segments=[TranscriptSegment(start=0.0, end=10.0, text="Cached text")],
                tier_used="whisper",
            )
            memory_repo.save_transcript(res)

        inspector = PreFlightInspector(repository=memory_repo)
        summary = inspector.inspect_episodes_sync(sample_episodes)

        assert summary.total_episodes == 4
        assert summary.tier_breakdown["cached"] == 4
        assert summary.tier_breakdown["rss"] == 0
        assert summary.tier_breakdown["youtube"] == 0
        assert summary.tier_breakdown["whisper"] == 0
        assert summary.tier_breakdown["cloud"] == 0
        # No local Whisper needed, so storage estimate should be 0.0
        assert summary.estimated_storage_mb == 0.0
        assert summary.requires_transcription is False

    def test_mixed_workload_tier_resolution(
        self, memory_repo: StorageRepository, sample_episodes: list[EpisodeMetadata]
    ) -> None:
        # Episode 0: "lex-100" (has RSS transcript) -> Should be "rss"
        # Episode 1: "lex-101" (we cache it) -> Should be "cached"
        cached_res = TranscriptResult(
            metadata=sample_episodes[1],
            segments=[TranscriptSegment(start=0.0, end=10.0, text="Cached")],
            tier_used="rss",
        )
        memory_repo.save_transcript(cached_res)

        # Episode 2: "hl-42" (source_type="youtube" & youtube url) -> Should be "youtube"
        # Episode 3: "indie-1" (plain audio, no mapping, no rss) -> Should be "whisper" (1200s = 20 min)

        inspector = PreFlightInspector(repository=memory_repo)
        summary = inspector.inspect_episodes_sync(sample_episodes, preferred_engine="auto")

        assert summary.total_episodes == 4
        assert summary.tier_breakdown["rss"] == 1
        assert summary.tier_breakdown["cached"] == 1
        assert summary.tier_breakdown["youtube"] == 1
        assert summary.tier_breakdown["whisper"] == 1
        assert summary.tier_breakdown["cloud"] == 0

        assert summary.episode_tiers["lex-100"] == "rss"
        assert summary.episode_tiers["lex-101"] == "cached"
        assert summary.episode_tiers["hl-42"] == "youtube"
        assert summary.episode_tiers["indie-1"] == "whisper"

        # Total duration = 3600 + 1800 + 5400 + 1200 = 12000s
        assert summary.total_duration_seconds == 12000.0
        assert summary.formatted_duration == "3h 20m 0s"

        # Storage footprint should only be calculated for the whisper episode (1200s = 20m -> 20.0 MB)
        assert summary.estimated_storage_mb == pytest.approx(20.0, abs=0.1)

    def test_youtube_mapping_in_repository_recognized(
        self, memory_repo: StorageRepository
    ) -> None:
        ep = EpisodeMetadata(
            show_title="Tech Show",
            episode_title="Episode 5",
            episode_id="tech-5",
            show_id="tech-show",
            audio_url="https://audio.example.com/tech5.mp3",
            duration_seconds=600.0,
            rss_transcripts=[],
            source_type="rss",
        )
        # Learn YouTube mapping
        KnowledgeLearner.learn_youtube_mapping(
            repository=memory_repo,
            show_id="tech-show",
            episode_id="tech-5",
            youtube_url="https://www.youtube.com/watch?v=techVideo123",
        )

        inspector = PreFlightInspector(repository=memory_repo)
        summary = inspector.inspect_episodes_sync([ep], preferred_engine="auto")

        assert summary.tier_breakdown["youtube"] == 1
        assert summary.episode_tiers["tech-5"] == "youtube"
        assert summary.estimated_storage_mb == 0.0

    def test_youtube_channel_mapping_in_repository_recognized(
        self, memory_repo: StorageRepository
    ) -> None:
        ep = EpisodeMetadata(
            show_title="Channel Show",
            episode_title="Ep 1",
            episode_id="ch-1",
            show_id="channel-show",
            audio_url="https://audio.example.com/ch1.mp3",
            duration_seconds=600.0,
            rss_transcripts=[],
            source_type="rss",
        )
        # Learn Show channel mapping
        KnowledgeLearner.learn_youtube_mapping(
            repository=memory_repo,
            show_id="channel-show",
            episode_id="other-ep",
            youtube_url="https://youtube.com/watch?v=other",
            channel_url="https://youtube.com/@channelshow",
        )

        inspector = PreFlightInspector(repository=memory_repo)
        summary = inspector.inspect_episodes_sync([ep], preferred_engine="auto")

        assert summary.tier_breakdown["youtube"] == 1
        assert summary.episode_tiers["ch-1"] == "youtube"

    def test_engine_override_cloud(
        self, memory_repo: StorageRepository, sample_episodes: list[EpisodeMetadata]
    ) -> None:
        inspector = PreFlightInspector(repository=memory_repo)
        summary = inspector.inspect_episodes_sync(sample_episodes, preferred_engine="cloud")

        assert summary.total_episodes == 4
        assert summary.tier_breakdown["cloud"] == 4
        assert summary.tier_breakdown["whisper"] == 0
        assert summary.tier_breakdown["rss"] == 0
        assert summary.estimated_storage_mb == 0.0

    def test_engine_override_groq_and_openai(
        self, memory_repo: StorageRepository, sample_episodes: list[EpisodeMetadata]
    ) -> None:
        inspector = PreFlightInspector(repository=memory_repo)

        summary_groq = inspector.inspect_episodes_sync(sample_episodes, preferred_engine="groq")
        assert summary_groq.tier_breakdown["cloud"] == 4

        summary_openai = inspector.inspect_episodes_sync(sample_episodes, preferred_engine="openai")
        assert summary_openai.tier_breakdown["cloud"] == 4

    def test_engine_override_whisper(
        self, memory_repo: StorageRepository, sample_episodes: list[EpisodeMetadata]
    ) -> None:
        inspector = PreFlightInspector(repository=memory_repo)
        summary = inspector.inspect_episodes_sync(sample_episodes, preferred_engine="whisper")

        assert summary.tier_breakdown["whisper"] == 4
        # Total duration = 12000s = 200m -> 200 MB
        assert summary.estimated_storage_mb == pytest.approx(200.0, abs=0.1)

    def test_engine_override_rss_and_youtube(
        self, memory_repo: StorageRepository, sample_episodes: list[EpisodeMetadata]
    ) -> None:
        inspector = PreFlightInspector(repository=memory_repo)

        summary_rss = inspector.inspect_episodes_sync(sample_episodes, preferred_engine="rss")
        assert summary_rss.tier_breakdown["rss"] == 4

        summary_yt = inspector.inspect_episodes_sync(sample_episodes, preferred_engine="youtube")
        assert summary_yt.tier_breakdown["youtube"] == 4

    @pytest.mark.asyncio
    async def test_async_inspect_episodes(
        self, memory_repo: StorageRepository, sample_episodes: list[EpisodeMetadata]
    ) -> None:
        inspector = PreFlightInspector(repository=memory_repo)
        summary = await inspector.inspect_episodes(sample_episodes)
        assert summary.total_episodes == 4
        assert summary.tier_breakdown["rss"] == 1
        assert summary.tier_breakdown["youtube"] == 1
        assert summary.tier_breakdown["whisper"] == 2

    def test_episode_without_duration(self, memory_repo: StorageRepository) -> None:
        ep = EpisodeMetadata(
            show_title="Show",
            episode_title="Ep",
            episode_id="ep-nodur",
            duration_seconds=None,
        )
        inspector = PreFlightInspector(repository=memory_repo)
        summary = inspector.inspect_episodes_sync([ep])
        assert summary.total_duration_seconds == 0.0
        assert summary.estimated_storage_mb == 0.0


# =============================================================================
# 3. Cost Estimator Tests
# =============================================================================


class TestCostEstimator:
    def test_estimate_cloud_cost(self) -> None:
        assert estimate_cloud_cost(0.0) == 0.0
        assert estimate_cloud_cost(None) == 0.0
        assert estimate_cloud_cost(-10.0) == 0.0

        # 10 minutes = 600 seconds @ $0.006/min = $0.060
        assert estimate_cloud_cost(600.0) == pytest.approx(0.06, abs=0.0001)

        # 60 minutes = 3600 seconds @ $0.006/min = $0.360
        assert estimate_cloud_cost(3600.0) == pytest.approx(0.36, abs=0.0001)

        # Custom rate: 60 minutes @ $0.003/min = $0.180
        assert estimate_cloud_cost(3600.0, rate_per_minute=0.003) == pytest.approx(0.18, abs=0.0001)


# =============================================================================
# 4. Interactive & Non-Interactive Prompts Tests
# =============================================================================


class TestPrompts:
    def test_batch_confirmation_auto_confirm(
        self, test_console: UIConsole
    ) -> None:
        summary = PreFlightSummary(total_episodes=3, total_duration_seconds=3600.0)
        # When auto_confirm is True, proceeds without prompting
        result = prompt_batch_confirmation(summary, auto_confirm=True, console=test_console)
        assert result is True

    def test_batch_confirmation_non_interactive_tty(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        summary = PreFlightSummary(total_episodes=3, total_duration_seconds=3600.0)
        # Mock sys.stdin.isatty to False
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        result = prompt_batch_confirmation(summary, auto_confirm=False, console=test_console)
        assert result is True

    def test_batch_confirmation_interactive_yes(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        summary = PreFlightSummary(total_episodes=2, total_duration_seconds=1800.0)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        # Mock questionary confirm to return True
        mock_confirm = MagicMock()
        mock_confirm.ask.return_value = True
        with patch("questionary.confirm", return_value=mock_confirm):
            result = prompt_batch_confirmation(summary, auto_confirm=False, console=test_console)
            assert result is True

    def test_batch_confirmation_interactive_no(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        summary = PreFlightSummary(total_episodes=2, total_duration_seconds=1800.0)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        # Mock questionary confirm to return False
        mock_confirm = MagicMock()
        mock_confirm.ask.return_value = False
        with patch("questionary.confirm", return_value=mock_confirm):
            result = prompt_batch_confirmation(summary, auto_confirm=False, console=test_console)
            assert result is False

    def test_batch_confirmation_aborted(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        summary = PreFlightSummary(total_episodes=2, total_duration_seconds=1800.0)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        # Mock questionary confirm returning None (cancelled / EOF)
        mock_confirm = MagicMock()
        mock_confirm.ask.return_value = None
        with patch("questionary.confirm", return_value=mock_confirm):
            result = prompt_batch_confirmation(summary, auto_confirm=False, console=test_console)
            assert result is False

    def test_youtube_mapping_auto_confirm(
        self, test_console: UIConsole
    ) -> None:
        action, custom_url = prompt_youtube_mapping(
            show_title="Lex Fridman",
            episode_title="AI Safety",
            candidate_title="Lex Fridman on AI Safety",
            candidate_url="https://youtube.com/watch?v=abc12345678",
            duration_str="1h 00m",
            channel_title="Lex Fridman",
            auto_confirm=True,
            confidence=0.95,
            console=test_console,
        )
        assert action == "use"
        assert custom_url is None

    def test_youtube_mapping_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        action, custom_url = prompt_youtube_mapping(
            show_title="Lex Fridman",
            episode_title="AI Safety",
            candidate_title="Lex Fridman on AI Safety",
            candidate_url="https://youtube.com/watch?v=abc12345678",
            duration_str="1h 00m",
            channel_title="Lex Fridman",
            auto_confirm=False,
            console=test_console,
        )
        assert action == "use"
        assert custom_url is None

    def test_youtube_mapping_interactive_use(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        mock_select = MagicMock()
        mock_select.ask.return_value = "use"

        with patch("questionary.select", return_value=mock_select):
            action, custom_url = prompt_youtube_mapping(
                show_title="Lex Fridman",
                episode_title="AI Safety",
                candidate_title="Candidate Title",
                candidate_url="https://youtube.com/watch?v=test1234567",
                duration_str="45m",
                channel_title="Lex Fridman",
                console=test_console,
            )
            assert action == "use"
            assert custom_url is None

    def test_youtube_mapping_interactive_skip_yt(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        mock_select = MagicMock()
        mock_select.ask.return_value = "skip_yt"

        with patch("questionary.select", return_value=mock_select):
            action, custom_url = prompt_youtube_mapping(
                show_title="Lex Fridman",
                episode_title="AI Safety",
                candidate_title="Candidate Title",
                candidate_url="https://youtube.com/watch?v=test1234567",
                duration_str="45m",
                channel_title="Lex Fridman",
                console=test_console,
            )
            assert action == "skip_yt"
            assert custom_url is None

    def test_youtube_mapping_interactive_custom_url(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        mock_select = MagicMock()
        mock_select.ask.return_value = "custom"

        mock_text = MagicMock()
        mock_text.ask.return_value = "https://youtube.com/watch?v=customVideoID"

        with patch("questionary.select", return_value=mock_select), \
             patch("questionary.text", return_value=mock_text):
            action, custom_url = prompt_youtube_mapping(
                show_title="Lex Fridman",
                episode_title="AI Safety",
                candidate_title="Candidate Title",
                candidate_url="https://youtube.com/watch?v=test1234567",
                duration_str="45m",
                channel_title="Lex Fridman",
                console=test_console,
            )
            assert action == "custom"
            assert custom_url == "https://youtube.com/watch?v=customVideoID"

    def test_youtube_mapping_interactive_skip_episode(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        mock_select = MagicMock()
        mock_select.ask.return_value = "skip_episode"

        with patch("questionary.select", return_value=mock_select):
            action, custom_url = prompt_youtube_mapping(
                show_title="Show",
                episode_title="Ep",
                candidate_title="Title",
                candidate_url="https://youtube.com/watch?v=123",
                duration_str="10m",
                channel_title="Channel",
                console=test_console,
            )
            assert action == "skip_episode"
            assert custom_url is None

    def test_cloud_cost_approval_auto_confirm(
        self, test_console: UIConsole
    ) -> None:
        ep = EpisodeMetadata(
            show_title="Lex Fridman",
            episode_title="Episode 100",
            episode_id="ep-100",
            duration_seconds=3600.0,
        )
        approved, always_show = prompt_cloud_cost_approval(
            episode=ep,
            estimated_cost_usd=0.36,
            auto_confirm=True,
            console=test_console,
        )
        assert approved is True
        assert always_show is False

    def test_cloud_cost_approval_non_interactive_declined(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        ep = EpisodeMetadata(
            show_title="Lex Fridman",
            episode_title="Episode 100",
            episode_id="ep-100",
            duration_seconds=3600.0,
        )
        approved, always_show = prompt_cloud_cost_approval(
            episode=ep,
            estimated_cost_usd=0.36,
            auto_confirm=False,
            console=test_console,
        )
        # Non-interactive without auto-confirm should decline cloud spend for safety
        assert approved is False
        assert always_show is False

    def test_cloud_cost_approval_interactive_approve_once(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        ep = EpisodeMetadata(
            show_title="Lex Fridman",
            episode_title="Episode 100",
            episode_id="ep-100",
        )
        mock_select = MagicMock()
        mock_select.ask.return_value = "yes"

        with patch("questionary.select", return_value=mock_select):
            approved, always_show = prompt_cloud_cost_approval(
                episode=ep,
                estimated_cost_usd=0.15,
                console=test_console,
            )
            assert approved is True
            assert always_show is False

    def test_cloud_cost_approval_interactive_always_for_show(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        ep = EpisodeMetadata(
            show_title="Lex Fridman",
            episode_title="Episode 100",
            episode_id="ep-100",
        )
        mock_select = MagicMock()
        mock_select.ask.return_value = "always"

        with patch("questionary.select", return_value=mock_select):
            approved, always_show = prompt_cloud_cost_approval(
                episode=ep,
                estimated_cost_usd=0.15,
                console=test_console,
            )
            assert approved is True
            assert always_show is True

    def test_cloud_cost_approval_interactive_decline(
        self, monkeypatch: pytest.MonkeyPatch, test_console: UIConsole
    ) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        ep = EpisodeMetadata(
            show_title="Lex Fridman",
            episode_title="Episode 100",
            episode_id="ep-100",
        )
        mock_select = MagicMock()
        mock_select.ask.return_value = "no"

        with patch("questionary.select", return_value=mock_select):
            approved, always_show = prompt_cloud_cost_approval(
                episode=ep,
                estimated_cost_usd=0.15,
                console=test_console,
            )
            assert approved is False
            assert always_show is False


# =============================================================================
# 5. Knowledge Learning & Persistence Tests
# =============================================================================


class TestKnowledgeLearner:
    def test_learn_and_get_youtube_mapping(
        self, memory_repo: StorageRepository
    ) -> None:
        # Initially not found
        assert KnowledgeLearner.get_known_youtube_mapping(memory_repo, "lex-fridman", "400") is None

        # Learn mapping
        mapping = KnowledgeLearner.learn_youtube_mapping(
            repository=memory_repo,
            show_id="lex-fridman",
            episode_id="400",
            youtube_url="https://youtube.com/watch?v=lex400vid",
            show_title="Lex Fridman Podcast",
            channel_url="https://youtube.com/@lexfridman",
        )
        assert mapping.show_id == "lex-fridman"
        assert mapping.episode_id == "400"
        assert mapping.youtube_video_url == "https://youtube.com/watch?v=lex400vid"
        assert mapping.confirmed_by_user is True

        # Retrieve via helper
        url = KnowledgeLearner.get_known_youtube_mapping(memory_repo, "lex-fridman", "400")
        assert url == "https://youtube.com/watch?v=lex400vid"

        # Check show channel was also saved
        chan = KnowledgeLearner.get_known_show_channel(memory_repo, "lex-fridman")
        assert chan == "https://youtube.com/@lexfridman"

        # Check repository directly
        repo_ep = memory_repo.get_episode_mapping("lex-fridman", "400")
        assert repo_ep is not None
        assert repo_ep.youtube_video_url == "https://youtube.com/watch?v=lex400vid"

        repo_show = memory_repo.get_show_mapping("lex-fridman")
        assert repo_show is not None
        assert repo_show.youtube_channel_url == "https://youtube.com/@lexfridman"

    def test_forget_youtube_mapping(self, memory_repo: StorageRepository) -> None:
        KnowledgeLearner.learn_youtube_mapping(
            repository=memory_repo,
            show_id="lex-fridman",
            episode_id="400",
            youtube_url="https://youtube.com/watch?v=lex400vid",
        )
        assert KnowledgeLearner.get_known_youtube_mapping(memory_repo, "lex-fridman", "400") is not None

        deleted = KnowledgeLearner.forget_youtube_mapping(memory_repo, "lex-fridman", "400")
        assert deleted is True
        assert KnowledgeLearner.get_known_youtube_mapping(memory_repo, "lex-fridman", "400") is None

    def test_learn_and_check_cloud_preference(
        self, memory_repo: StorageRepository
    ) -> None:
        # Initially false
        assert KnowledgeLearner.is_cloud_allowed(memory_repo, "huberman-lab") is False

        # Learn preference
        KnowledgeLearner.learn_cloud_preference(memory_repo, "huberman-lab", always_allow_cloud=True)
        assert KnowledgeLearner.is_cloud_allowed(memory_repo, "huberman-lab") is True

        # Check directly in preferences table
        pref_val = memory_repo.get_preference("cloud_allowed:huberman-lab")
        assert pref_val is True

        # Forget preference
        deleted = KnowledgeLearner.forget_cloud_preference(memory_repo, "huberman-lab")
        assert deleted is True
        assert KnowledgeLearner.is_cloud_allowed(memory_repo, "huberman-lab") is False

    def test_instance_methods_convenience(
        self, memory_repo: StorageRepository
    ) -> None:
        learner = KnowledgeLearner(repository=memory_repo)

        # YouTube mapping instance method
        learner.record_youtube_mapping(
            show_id="show-inst",
            episode_id="ep-1",
            youtube_url="https://youtube.com/watch?v=inst123",
            channel_url="https://youtube.com/@showinst",
        )
        assert KnowledgeLearner.get_known_youtube_mapping(memory_repo, "show-inst", "ep-1") == "https://youtube.com/watch?v=inst123"

        # Cloud preference instance method
        assert learner.check_cloud_allowed("show-inst") is False
        learner.record_cloud_preference("show-inst", always_allow_cloud=True)
        assert learner.check_cloud_allowed("show-inst") is True

    def test_instance_without_repo_raises_error(self) -> None:
        learner = KnowledgeLearner(repository=None)
        with pytest.raises(ValueError, match="Storage repository is required"):
            learner.record_youtube_mapping("show", "ep", "https://youtube.com/1")

        with pytest.raises(ValueError, match="Storage repository is required"):
            learner.record_cloud_preference("show", True)

        with pytest.raises(ValueError, match="Storage repository is required"):
            learner.check_cloud_allowed("show")
