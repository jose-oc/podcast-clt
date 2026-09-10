"""End-to-end integration tests for podcast-cli Typer interface and subcommands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from typer.testing import CliRunner

from podcast_cli import __version__
from podcast_cli.cli.main import app
from podcast_cli.discovery.itunes import PodcastSearchResult
from podcast_cli.discovery.resolver import ResolvedSource
from podcast_cli.discovery.rss import ShowMetadata
from podcast_cli.models.transcript import EpisodeMetadata, TranscriptResult, TranscriptSegment
from podcast_cli.storage.repository import StorageRepository

runner = CliRunner(env={"COLUMNS": "250"})


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ensure every test runs against an isolated temporary SQLite database."""
    db_file = tmp_path / "test_podcast_cli.db"
    monkeypatch.setenv("PODCAST_CLI_DB_PATH", str(db_file))
    return db_file


# =============================================================================
# Global & General CLI Tests
# =============================================================================


def test_cli_help() -> None:
    """Test top-level --help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Fast, modular CLI" in result.stdout
    assert "search" in result.stdout
    assert "inspect" in result.stdout
    assert "transcribe" in result.stdout
    assert "mapping" in result.stdout
    assert "cache" in result.stdout


def test_cli_version() -> None:
    """Test top-level --version / -v flag."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"v{__version__}" in result.stdout


def test_cli_verbose_flag() -> None:
    """Test top-level --verbose flag doesn't crash."""
    result = runner.invoke(app, ["--verbose", "--help"])
    assert result.exit_code == 0


# =============================================================================
# Search Command Tests
# =============================================================================


def test_search_command_with_results() -> None:
    """Test search command displaying rich results table."""
    mock_results = [
        PodcastSearchResult(
            collection_id=123,
            title="Latent Space",
            author="Swyx & Alessio",
            feed_url="https://feeds.simplecast.com/latent-space",
            episode_count=42,
        ),
        PodcastSearchResult(
            collection_id=456,
            title="AI Breakdown",
            author="NLW",
            feed_url="https://feeds.buzzsprout.com/ai-breakdown",
            episode_count=100,
        ),
    ]

    with patch("podcast_cli.cli.commands.search.search_itunes", return_value=mock_results):
        result = runner.invoke(app, ["search", "AI", "--no-interactive"])
        assert result.exit_code == 0
        assert "Search Results for 'AI'" in result.stdout
        assert "Latent Space" in result.stdout
        assert "Swyx & Alessio" in result.stdout
        assert "42" in result.stdout
        assert "https://feeds.simplecast.com/latent-space" in result.stdout


def test_search_command_no_results() -> None:
    """Test search command when no matches are found."""
    with patch("podcast_cli.cli.commands.search.search_itunes", return_value=[]):
        result = runner.invoke(app, ["search", "NonExistentShow123", "--no-interactive"])
        assert result.exit_code == 0
        assert "No podcast search results found" in result.stdout


def test_search_command_interactive_cancel_selection() -> None:
    """Test interactive search when user selects 'Cancel / Exit' or aborts."""
    from podcast_cli.cli.commands.search import search_command
    import sys

    mock_results = [
        PodcastSearchResult(
            collection_id=123,
            title="Talk Python To Me",
            author="Michael Kennedy",
            feed_url="https://talkpython.fm/rss",
            episode_count=450,
        )
    ]
    with (
        patch("podcast_cli.cli.commands.search.search_itunes", return_value=mock_results),
        patch.object(sys.stdin, "isatty", return_value=True),
        patch("questionary.select") as mock_select,
    ):
        mock_select.return_value.ask.return_value = "cancel"
        # Should return gracefully without any exception
        search_command(query="Python", interactive=True)


def test_search_command_interactive_cancel_action() -> None:
    """Test interactive search when user selects a show but cancels the action."""
    from podcast_cli.cli.commands.search import search_command
    import sys

    mock_item = PodcastSearchResult(
        collection_id=123,
        title="Talk Python To Me",
        author="Michael Kennedy",
        feed_url="https://talkpython.fm/rss",
        episode_count=450,
    )
    with (
        patch("podcast_cli.cli.commands.search.search_itunes", return_value=[mock_item]),
        patch.object(sys.stdin, "isatty", return_value=True),
        patch("questionary.select") as mock_select,
    ):
        mock_select.return_value.ask.side_effect = [mock_item, "cancel"]
        # Should return gracefully without any exception
        search_command(query="Python", interactive=True)


def test_search_command_interactive_action_url(capsys: pytest.CaptureFixture) -> None:
    """Test interactive search selecting 'Print Feed URL' action."""
    from podcast_cli.cli.commands.search import search_command
    import sys

    mock_item = PodcastSearchResult(
        collection_id=123,
        title="Talk Python To Me",
        author="Michael Kennedy",
        feed_url="https://talkpython.fm/rss",
        episode_count=450,
    )
    with (
        patch("podcast_cli.cli.commands.search.search_itunes", return_value=[mock_item]),
        patch.object(sys.stdin, "isatty", return_value=True),
        patch("questionary.select") as mock_select,
    ):
        mock_select.return_value.ask.side_effect = [mock_item, "url"]
        search_command(query="Python", interactive=True)
        captured = capsys.readouterr()
        assert "https://talkpython.fm/rss" in captured.out


# =============================================================================
# Inspect Command Tests
# =============================================================================


def test_inspect_command_rss_feed() -> None:
    """Test inspect command on a podcast RSS feed."""
    mock_episodes = [
        EpisodeMetadata(
            show_title="Tech Weekly",
            episode_title="Episode 1: The Beginning",
            episode_id="ep-1",
            duration_seconds=3600.0,
            audio_url="https://audio.com/ep1.mp3",
            published_date="2026-01-01T12:00:00Z",
            rss_transcripts=[{"url": "https://audio.com/ep1.vtt", "type": "text/vtt"}],
            source_type="rss",
        ),
        EpisodeMetadata(
            show_title="Tech Weekly",
            episode_title="Episode 2: Deep Dive",
            episode_id="ep-2",
            duration_seconds=1800.0,
            audio_url="https://audio.com/ep2.mp3",
            published_date="2026-01-08T12:00:00Z",
            source_type="rss",
        ),
    ]
    mock_resolved = ResolvedSource(
        source_type="rss",
        query="https://example.com/feed.xml",
        show_metadata=ShowMetadata(
            title="Tech Weekly",
            feed_url="https://example.com/feed.xml",
            description="A great tech podcast.",
        ),
        episodes=mock_episodes,
    )

    with patch("podcast_cli.cli.commands.inspect.resolve_input", return_value=mock_resolved):
        result = runner.invoke(app, ["inspect", "https://example.com/feed.xml"])
        assert result.exit_code == 0
        assert "Tech Weekly" in result.stdout
        assert "Total Episodes" in result.stdout
        assert "RSS (Tier 1)" in result.stdout
        assert "Episode 1: The Beginning" in result.stdout


def test_inspect_command_no_episodes() -> None:
    """Test inspect command when source yields zero episodes."""
    mock_resolved = ResolvedSource(
        source_type="rss",
        query="https://example.com/empty.xml",
        episodes=[],
    )
    with patch("podcast_cli.cli.commands.inspect.resolve_input", return_value=mock_resolved):
        result = runner.invoke(app, ["inspect", "https://example.com/empty.xml"])
        assert result.exit_code == 0
        assert "No episodes found" in result.stdout


# =============================================================================
# Transcribe Command Tests
# =============================================================================


def test_transcribe_single_episode_success(tmp_path: Path) -> None:
    """Test end-to-end transcription with mocked dispatcher and export generation."""
    out_dir = tmp_path / "transcripts"
    mock_episode = EpisodeMetadata(
        show_title="Podcast Alpha",
        episode_title="Episode 100",
        episode_id="alpha-100",
        duration_seconds=600.0,
        audio_url="https://audio.com/100.mp3",
        source_type="rss",
    )
    mock_resolved = ResolvedSource(
        source_type="rss",
        query="https://alpha.com/feed.xml",
        episodes=[mock_episode],
    )
    mock_result = TranscriptResult(
        metadata=mock_episode,
        segments=[
            TranscriptSegment(start=0.0, end=5.0, text="Hello world and welcome to alpha."),
        ],
        tier_used="rss",
        raw_text="Hello world and welcome to alpha.",
    )

    with (
        patch("podcast_cli.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch.object(
            StorageRepository,
            "save_transcript",
            wraps=StorageRepository().save_transcript,
        ),
        patch(
            "podcast_cli.engines.dispatcher.TranscriptionDispatcher.transcribe",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_transcribe,
    ):
        result = runner.invoke(
            app,
            [
                "transcribe",
                "https://alpha.com/feed.xml",
                "--output-dir",
                str(out_dir),
                "--format",
                "markdown",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "Successfully transcribed" in result.stdout
        assert "Episode 100" in result.stdout
        mock_transcribe.assert_awaited_once()

        # Verify exported markdown file exists
        expected_md = out_dir / "podcast-alpha" / "episode-100.md"
        assert expected_md.exists()
        assert "Hello world and welcome to alpha." in expected_md.read_text(encoding="utf-8")


def test_transcribe_filter_by_index_and_title(tmp_path: Path) -> None:
    """Test episode filtering via 1-based index and title substring."""
    out_dir = tmp_path / "transcripts"
    ep1 = EpisodeMetadata(
        show_title="Show A",
        episode_title="First Episode",
        episode_id="ep-1",
        duration_seconds=300.0,
        source_type="rss",
    )
    ep2 = EpisodeMetadata(
        show_title="Show A",
        episode_title="Second Episode",
        episode_id="ep-2",
        duration_seconds=400.0,
        source_type="rss",
    )
    mock_resolved = ResolvedSource(
        source_type="rss",
        query="https://showa.com/rss",
        episodes=[ep1, ep2],
    )
    mock_result = TranscriptResult(
        metadata=ep2,
        segments=[TranscriptSegment(start=0.0, end=3.0, text="Second episode content")],
        tier_used="whisper",
        raw_text="Second episode content",
    )

    with (
        patch("podcast_cli.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch(
            "podcast_cli.engines.dispatcher.TranscriptionDispatcher.transcribe",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
    ):
        # Transcribe 2nd episode by index
        result = runner.invoke(
            app,
            [
                "transcribe",
                "https://showa.com/rss",
                "-e",
                "2",
                "-o",
                str(out_dir),
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "Second Episode" in result.stdout

        # Transcribe by title substring
        result_title = runner.invoke(
            app,
            [
                "transcribe",
                "https://showa.com/rss",
                "-e",
                "Second",
                "-o",
                str(out_dir),
                "--yes",
            ],
        )
        assert result_title.exit_code == 0
        assert "Second Episode" in result_title.stdout


def test_transcribe_abort_on_batch_prompt() -> None:
    """Test graceful abort when user declines pre-flight confirmation."""
    mock_episode = EpisodeMetadata(
        show_title="Show B",
        episode_title="Episode 1",
        episode_id="ep-1",
        duration_seconds=100.0,
        source_type="rss",
    )
    mock_resolved = ResolvedSource(
        source_type="rss",
        query="https://showb.com/rss",
        episodes=[mock_episode],
    )

    with (
        patch("podcast_cli.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch("podcast_cli.cli.commands.transcribe.prompt_batch_confirmation", return_value=False),
    ):
        result = runner.invoke(app, ["transcribe", "https://showb.com/rss"])
        assert result.exit_code == 0
        assert "Transcription aborted by user" in result.stdout


def test_transcribe_invalid_episode_filter() -> None:
    """Test error when episode filter does not match any episodes."""
    mock_episode = EpisodeMetadata(
        show_title="Show C",
        episode_title="Intro",
        episode_id="ep-1",
        source_type="rss",
    )
    mock_resolved = ResolvedSource(
        source_type="rss",
        query="https://showc.com/rss",
        episodes=[mock_episode],
    )

    with patch("podcast_cli.cli.commands.transcribe.resolve_input", return_value=mock_resolved):
        result = runner.invoke(app, ["transcribe", "https://showc.com/rss", "-e", "NonExistent"])
        assert result.exit_code == 1
        assert "No episode found matching filter" in (result.stderr or result.stdout or result.output)


# =============================================================================
# Mapping Command Tests
# =============================================================================


def test_mapping_lifecycle() -> None:
    """Test listing, adding, and removing Show and Episode YouTube mappings."""
    # 1. Initially empty
    res_list = runner.invoke(app, ["mapping", "list"])
    assert res_list.exit_code == 0
    assert "No YouTube mappings found" in res_list.stdout

    # 2. Add show mapping
    res_add_show = runner.invoke(
        app,
        [
            "mapping",
            "add",
            "show",
            "https://feed.com/rss",
            "https://youtube.com/@show",
            "--title",
            "My Show",
        ],
    )
    assert res_add_show.exit_code == 0
    assert "Saved show mapping" in res_add_show.stdout

    # 3. Add episode mapping
    res_add_ep = runner.invoke(
        app,
        [
            "mapping",
            "add",
            "episode",
            "My Show",
            "ep-101",
            "https://youtube.com/watch?v=abc123xyz",
        ],
    )
    assert res_add_ep.exit_code == 0
    assert "Saved episode mapping" in res_add_ep.stdout

    # 4. List mappings
    res_list2 = runner.invoke(app, ["mapping", "list"])
    assert res_list2.exit_code == 0
    assert "https://feed.com/rss" in res_list2.stdout
    assert "https://youtube.com/@show" in res_list2.stdout
    assert "ep-101" in res_list2.stdout
    assert "https://youtube.com/watch?v=abc123xyz" in res_list2.stdout

    # 5. Remove episode mapping
    res_rm_ep = runner.invoke(app, ["mapping", "remove", "episode", "My Show", "ep-101"])
    assert res_rm_ep.exit_code == 0
    assert "Removed episode mapping" in res_rm_ep.stdout

    # 6. Remove show mapping
    res_rm_show = runner.invoke(app, ["mapping", "remove", "show", "https://feed.com/rss"])
    assert res_rm_show.exit_code == 0
    assert "Removed show mapping" in res_rm_show.stdout


# =============================================================================
# Cache Command Tests
# =============================================================================


def test_cache_stats_and_clean() -> None:
    """Test cache stats display, listing, and cleaning."""
    repo = StorageRepository()
    ep = EpisodeMetadata(
        show_title="Cached Show",
        episode_title="Cached Episode",
        episode_id="c-1",
        source_type="rss",
    )
    res = TranscriptResult(
        metadata=ep,
        segments=[TranscriptSegment(start=0.0, end=1.0, text="Cached text.")],
        tier_used="rss",
        raw_text="Cached text.",
    )
    repo.save_transcript(res)

    # 1. Stats
    res_stats = runner.invoke(app, ["cache", "stats"])
    assert res_stats.exit_code == 0
    assert "Database & Cache Statistics" in res_stats.stdout
    assert "Cached Transcripts" in res_stats.stdout

    # 2. List
    res_list = runner.invoke(app, ["cache", "list"])
    assert res_list.exit_code == 0
    assert "Cached Show" in res_list.stdout
    assert "Cached Episode" in res_list.stdout

    # 3. Clean with --yes
    res_clean = runner.invoke(app, ["cache", "clean", "--yes"])
    assert res_clean.exit_code == 0
    assert "Cleared 1 cached transcript(s)" in res_clean.stdout

    # 4. Verify list is now empty
    res_list2 = runner.invoke(app, ["cache", "list"])
    assert res_list2.exit_code == 0
    assert "No transcripts found in the local cache" in res_list2.stdout


# =============================================================================
# Additional Edge Case & Advanced Integration Tests
# =============================================================================


def test_inspect_search_query_resolution() -> None:
    """Test inspect command resolving a plain search query to an iTunes feed."""
    search_hit = PodcastSearchResult(
        collection_id=999,
        title="Discovered Show",
        author="Host Name",
        feed_url="https://discovered.com/feed.xml",
        episode_count=10,
    )
    mock_search_resolved = ResolvedSource(
        source_type="search",
        query="Discovered Show",
        search_results=[search_hit],
    )
    mock_rss_resolved = ResolvedSource(
        source_type="rss",
        query="https://discovered.com/feed.xml",
        show_metadata=ShowMetadata(
            title="Discovered Show",
            feed_url="https://discovered.com/feed.xml",
            description="Found via search.",
        ),
        episodes=[
            EpisodeMetadata(
                show_title="Discovered Show",
                episode_title="Episode 1",
                episode_id="ep-1",
                duration_seconds=1200.0,
                source_type="rss",
            )
        ],
    )

    with patch("podcast_cli.cli.commands.inspect.resolve_input", side_effect=[mock_search_resolved, mock_rss_resolved]):
        result = runner.invoke(app, ["inspect", "Discovered Show"])
        assert result.exit_code == 0
        assert "Resolved search query" in result.stdout
        assert "Discovered Show" in result.stdout
        assert "Episode 1" in result.stdout


def test_transcribe_all_and_latest_flags(tmp_path: Path) -> None:
    """Test transcribe command handling --latest and --all options."""
    out_dir = tmp_path / "transcripts"
    episodes = [
        EpisodeMetadata(
            show_title="Multi Show",
            episode_title=f"Episode {i}",
            episode_id=f"ep-{i}",
            duration_seconds=300.0,
            source_type="rss",
        )
        for i in range(1, 5)
    ]
    mock_resolved = ResolvedSource(
        source_type="rss",
        query="https://multi.com/rss",
        episodes=episodes,
    )

    def mock_transcribe_side_effect(*args, **kwargs):
        ep = kwargs.get("episode") or (args[0] if args else None)
        return TranscriptResult(
            metadata=ep,
            segments=[TranscriptSegment(start=0.0, end=1.0, text=f"Text for {ep.episode_title}")],
            tier_used="rss",
            raw_text=f"Text for {ep.episode_title}",
        )

    with (
        patch("podcast_cli.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch(
            "podcast_cli.engines.dispatcher.TranscriptionDispatcher.transcribe",
            new_callable=AsyncMock,
            side_effect=mock_transcribe_side_effect,
        ) as mock_transcribe,
    ):
        # 1. Test --latest 2
        result_latest = runner.invoke(
            app,
            [
                "transcribe",
                "https://multi.com/rss",
                "--latest",
                "2",
                "-o",
                str(out_dir),
                "--yes",
            ],
        )
        assert result_latest.exit_code == 0
        assert mock_transcribe.call_count == 2
        assert "Completed 2 of 2 episode(s)" in result_latest.stdout

        mock_transcribe.reset_mock()

        # 2. Test --all
        result_all = runner.invoke(
            app,
            [
                "transcribe",
                "https://multi.com/rss",
                "--all",
                "-o",
                str(out_dir),
                "--yes",
            ],
        )
        assert result_all.exit_code == 0
        assert mock_transcribe.call_count == 4
        assert "Completed 4 of 4 episode(s)" in result_all.stdout


def test_transcribe_cloud_guardrail_declined() -> None:
    """Test cloud cost guardrail declining transcription."""
    mock_episode = EpisodeMetadata(
        show_title="Cloud Show",
        episode_title="Cloud Episode",
        episode_id="cloud-1",
        duration_seconds=3600.0,
        source_type="rss",
    )
    mock_resolved = ResolvedSource(
        source_type="rss",
        query="https://cloud.com/rss",
        episodes=[mock_episode],
    )

    with (
        patch("podcast_cli.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch("podcast_cli.cli.commands.transcribe.prompt_batch_confirmation", return_value=True),
        patch("podcast_cli.cli.commands.transcribe.prompt_cloud_cost_approval", return_value=(False, False)),
    ):
        result = runner.invoke(
            app,
            [
                "transcribe",
                "https://cloud.com/rss",
                "--engine",
                "groq",
            ],
        )
        assert result.exit_code == 1
        assert "Skipping cloud transcription" in result.stdout
