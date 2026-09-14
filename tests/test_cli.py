"""End-to-end integration tests for podcast-ctl Typer interface and subcommands."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from podcast_ctl import __version__, errors
from podcast_ctl.cli import main as main_module
from podcast_ctl.cli.main import app
from podcast_ctl.discovery.itunes import PodcastSearchResult
from podcast_ctl.discovery.resolver import ResolvedSource
from podcast_ctl.discovery.rss import ShowMetadata
from podcast_ctl.engines.base import TranscriptionEngineError
from podcast_ctl.engines.channel_search import ChannelVideo
from podcast_ctl.models.knowledge import ShowMapping
from podcast_ctl.models.transcript import EpisodeMetadata, TranscriptResult, TranscriptSegment
from podcast_ctl.storage.repository import StorageRepository

runner = CliRunner(env={"COLUMNS": "250"})


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ensure every test runs against an isolated temporary SQLite database."""
    db_file = tmp_path / "test_podcast_ctl.db"
    monkeypatch.setenv("PODCAST_CTL_DB_PATH", str(db_file))
    return db_file


@pytest.fixture(autouse=True)
def reset_debug_mode() -> None:
    """Ensure the global --debug switch never leaks between tests."""
    errors.set_debug(False)


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

    with patch("podcast_ctl.cli.commands.search.search_itunes", return_value=mock_results):
        result = runner.invoke(app, ["search", "AI", "--no-interactive"])
        assert result.exit_code == 0
        assert "Search Results for 'AI'" in result.stdout
        assert "Latent Space" in result.stdout
        assert "Swyx & Alessio" in result.stdout
        assert "42" in result.stdout
        assert "https://feeds.simplecast.com/latent-space" in result.stdout


def test_search_command_no_results() -> None:
    """Test search command when no matches are found."""
    with patch("podcast_ctl.cli.commands.search.search_itunes", return_value=[]):
        result = runner.invoke(app, ["search", "NonExistentShow123", "--no-interactive"])
        assert result.exit_code == 0
        assert "No podcast search results found" in result.stdout


def test_search_command_interactive_cancel_selection() -> None:
    """Test interactive search when user selects 'Cancel / Exit' or aborts."""
    import sys

    from podcast_ctl.cli.commands.search import search_command

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
        patch("podcast_ctl.cli.commands.search.search_itunes", return_value=mock_results),
        patch.object(sys.stdin, "isatty", return_value=True),
        patch("questionary.select") as mock_select,
    ):
        mock_select.return_value.ask.return_value = "cancel"
        # Should return gracefully without any exception
        search_command(query="Python", interactive=True)


def test_search_command_interactive_cancel_action() -> None:
    """Test interactive search when user selects a show but cancels the action."""
    import sys

    from podcast_ctl.cli.commands.search import search_command

    mock_item = PodcastSearchResult(
        collection_id=123,
        title="Talk Python To Me",
        author="Michael Kennedy",
        feed_url="https://talkpython.fm/rss",
        episode_count=450,
    )
    with (
        patch("podcast_ctl.cli.commands.search.search_itunes", return_value=[mock_item]),
        patch.object(sys.stdin, "isatty", return_value=True),
        patch("questionary.select") as mock_select,
    ):
        mock_select.return_value.ask.side_effect = [mock_item, "cancel"]
        # Should return gracefully without any exception
        search_command(query="Python", interactive=True)


def test_search_command_interactive_action_url(capsys: pytest.CaptureFixture) -> None:
    """Test interactive search selecting 'Print Feed URL' action."""
    import sys

    from podcast_ctl.cli.commands.search import search_command

    mock_item = PodcastSearchResult(
        collection_id=123,
        title="Talk Python To Me",
        author="Michael Kennedy",
        feed_url="https://talkpython.fm/rss",
        episode_count=450,
    )
    with (
        patch("podcast_ctl.cli.commands.search.search_itunes", return_value=[mock_item]),
        patch.object(sys.stdin, "isatty", return_value=True),
        patch("questionary.select") as mock_select,
    ):
        mock_select.return_value.ask.side_effect = [mock_item, "url"]
        search_command(query="Python", interactive=True)
        captured = capsys.readouterr()
        assert "https://talkpython.fm/rss" in captured.out


def test_search_command_interactive_action_inspect() -> None:
    """Test interactive search selecting 'Inspect Show & Episodes' action."""
    import sys

    from podcast_ctl.cli.commands.search import search_command

    mock_item = PodcastSearchResult(
        collection_id=123,
        title="Talk Python To Me",
        author="Michael Kennedy",
        feed_url="https://talkpython.fm/rss",
        episode_count=450,
    )
    with (
        patch("podcast_ctl.cli.commands.search.search_itunes", return_value=[mock_item]),
        patch.object(sys.stdin, "isatty", return_value=True),
        patch("questionary.select") as mock_select,
        patch("podcast_ctl.cli.commands.inspect.inspect_command") as mock_inspect,
    ):
        mock_select.return_value.ask.side_effect = [mock_item, "inspect"]
        search_command(query="Python", interactive=True)
        mock_inspect.assert_called_once_with(input_source="https://talkpython.fm/rss")


def test_search_command_interactive_action_transcribe() -> None:
    """Test interactive search selecting 'Transcribe Latest Episode' action."""
    import sys

    from podcast_ctl.cli.commands.search import search_command

    mock_item = PodcastSearchResult(
        collection_id=123,
        title="Talk Python To Me",
        author="Michael Kennedy",
        feed_url="https://talkpython.fm/rss",
        episode_count=450,
    )
    with (
        patch("podcast_ctl.cli.commands.search.search_itunes", return_value=[mock_item]),
        patch.object(sys.stdin, "isatty", return_value=True),
        patch("questionary.select") as mock_select,
        patch("podcast_ctl.cli.commands.transcribe.transcribe_command") as mock_transcribe,
    ):
        mock_select.return_value.ask.side_effect = [mock_item, "transcribe"]
        search_command(query="Python", interactive=True)
        mock_transcribe.assert_called_once_with(input_source="https://talkpython.fm/rss", latest=1)



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

    with patch("podcast_ctl.cli.commands.inspect.resolve_input", return_value=mock_resolved):
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
    with patch("podcast_ctl.cli.commands.inspect.resolve_input", return_value=mock_resolved):
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
        patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch.object(
            StorageRepository,
            "save_transcript",
            wraps=StorageRepository().save_transcript,
        ),
        patch(
            "podcast_ctl.engines.dispatcher.TranscriptionDispatcher.transcribe",
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
        patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch(
            "podcast_ctl.engines.dispatcher.TranscriptionDispatcher.transcribe",
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
        patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch("podcast_ctl.cli.commands.transcribe.prompt_batch_confirmation", return_value=False),
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

    with patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved):
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

    # Feed resolution is unreachable here: mappings must be saved exactly as provided
    mapping_resolve = patch(
        "podcast_ctl.cli.commands.mapping.resolve_input",
        side_effect=ConnectionError("no network in tests"),
    )

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
    with mapping_resolve:
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


def _mock_rss_resolved(episodes: list[EpisodeMetadata]) -> ResolvedSource:
    return ResolvedSource(
        source_type="rss",
        query="https://feed.com/rss",
        show_metadata=ShowMetadata(title="My Show", feed_url="https://feed.com/rss"),
        episodes=episodes,
    )


def test_mapping_add_show_resolves_feed_title() -> None:
    """Without --title, the show title is resolved from the feed itself."""
    with patch(
        "podcast_ctl.cli.commands.mapping.resolve_input",
        return_value=_mock_rss_resolved([]),
    ):
        res = runner.invoke(
            app,
            [
                "mapping",
                "add",
                "show",
                "https://feed.com/rss",
                "https://youtube.com/@show",
            ],
        )
    assert res.exit_code == 0
    assert "Resolved show title from the feed" in res.stdout
    assert "My Show" in res.stdout

    res_list = runner.invoke(app, ["mapping", "list"])
    assert "My Show" in res_list.stdout


def test_mapping_add_show_offline_warns_and_keeps_feed_url() -> None:
    """If the feed cannot be fetched, the mapping is still saved with a warning."""
    with patch(
        "podcast_ctl.cli.commands.mapping.resolve_input",
        side_effect=ConnectionError("no network in tests"),
    ):
        res = runner.invoke(
            app,
            [
                "mapping",
                "add",
                "show",
                "https://feed.com/rss",
                "https://youtube.com/@show",
            ],
        )
    assert res.exit_code == 0
    assert "Could not fetch the feed" in res.stdout
    assert "Saved show mapping" in res.stdout


def test_mapping_add_episode_resolves_exact_title_to_guid() -> None:
    """An exact episode title is resolved to its RSS GUID via the feed."""
    ep = EpisodeMetadata(
        show_title="My Show",
        episode_title="Episode 101: The Title",
        episode_id="guid-101",
        audio_url="https://feed.com/ep101.mp3",
        source_type="rss",
    )
    with patch(
        "podcast_ctl.cli.commands.mapping.resolve_input",
        return_value=_mock_rss_resolved([ep]),
    ):
        res = runner.invoke(
            app,
            [
                "mapping",
                "add",
                "episode",
                "My Show",
                "Episode 101: The Title",
                "https://youtube.com/watch?v=abc123xyz",
            ],
        )
    assert res.exit_code == 0
    assert "Resolved episode title to GUID" in res.stdout
    assert "guid-101" in res.stdout

    res_list = runner.invoke(app, ["mapping", "list"])
    assert "guid-101" in res_list.stdout


def test_mapping_add_episode_guid_passthrough_when_in_feed() -> None:
    """A value that already is an RSS GUID is kept unchanged."""
    ep = EpisodeMetadata(
        show_title="My Show",
        episode_title="Episode 101: The Title",
        episode_id="guid-101",
        audio_url="https://feed.com/ep101.mp3",
        source_type="rss",
    )
    with patch(
        "podcast_ctl.cli.commands.mapping.resolve_input",
        return_value=_mock_rss_resolved([ep]),
    ):
        res = runner.invoke(
            app,
            [
                "mapping",
                "add",
                "episode",
                "My Show",
                "guid-101",
                "https://youtube.com/watch?v=abc123xyz",
            ],
        )
    assert res.exit_code == 0
    assert "Resolved episode title to GUID" not in res.stdout
    assert "guid-101" in res.stdout


def test_mapping_add_episode_unknown_title_fails_with_hint() -> None:
    """An unknown title/GUID aborts with a hint towards inspect."""
    ep = EpisodeMetadata(
        show_title="My Show",
        episode_title="Episode 101: The Title",
        episode_id="guid-101",
        audio_url="https://feed.com/ep101.mp3",
        source_type="rss",
    )
    with patch(
        "podcast_ctl.cli.commands.mapping.resolve_input",
        return_value=_mock_rss_resolved([ep]),
    ):
        res = runner.invoke(
            app,
            [
                "mapping",
                "add",
                "episode",
                "My Show",
                "No Such Episode",
                "https://youtube.com/watch?v=abc123xyz",
            ],
        )
    assert res.exit_code == 1
    assert "No episode with GUID or exact title" in (res.stdout or res.output)


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

    with patch("podcast_ctl.cli.commands.inspect.resolve_input", side_effect=[mock_search_resolved, mock_rss_resolved]):
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
        patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch(
            "podcast_ctl.engines.dispatcher.TranscriptionDispatcher.transcribe",
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
        patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch("podcast_ctl.cli.commands.transcribe.prompt_batch_confirmation", return_value=True),
        patch("podcast_ctl.cli.commands.transcribe.prompt_cloud_cost_approval", return_value=(False, False)),
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


# =============================================================================
# Mapping sync & help-text tests
# =============================================================================


def _sync_episode(episode_id: str, title: str) -> EpisodeMetadata:
    return EpisodeMetadata(
        show_title="My Show",
        episode_title=title,
        episode_id=episode_id,
        audio_url=f"https://audio.example.com/{episode_id}.mp3",
    )


def test_mapping_group_help_explains_command() -> None:
    """The add/remove group help explains that COMMAND is the mapping kind, with examples."""
    res_add = runner.invoke(app, ["mapping", "add", "--help"])
    assert res_add.exit_code == 0
    assert "COMMAND" in res_add.stdout
    assert "show" in res_add.stdout
    assert "episode" in res_add.stdout
    assert "Examples" in res_add.stdout

    res_remove = runner.invoke(app, ["mapping", "remove", "--help"])
    assert res_remove.exit_code == 0
    assert "Examples" in res_remove.stdout
    assert "mapping list" in res_remove.stdout


def test_mapping_sync_matches_full_catalog() -> None:
    """mapping sync lists the channel once and stores accepted matches as unconfirmed."""
    episodes = [
        _sync_episode("ep-1", "Episode One: Python"),
        _sync_episode("ep-2", "Episode Two: Rust"),
        _sync_episode("ep-3", "Episode Three: Obscure Topic"),
    ]
    catalog = [
        ChannelVideo(video_id="vid0000001a", title="Episode One: Python"),
        ChannelVideo(video_id="vid0000002b", title="Episode Two: Rust"),
    ]
    with (
        patch("podcast_ctl.cli.commands.mapping.resolve_input", return_value=_mock_rss_resolved(episodes)),
        patch("podcast_ctl.cli.commands.mapping.list_channel_videos", return_value=catalog) as list_mock,
    ):
        result = runner.invoke(app, ["mapping", "sync", "My Show", "--channel", "https://youtube.com/@show"])

    assert result.exit_code == 0
    assert "Saved 2 episode mapping(s)" in result.stdout
    assert "1 had no close match" in result.stdout
    list_mock.assert_called_once_with("https://youtube.com/@show", max_videos=None)

    repo = StorageRepository()
    m1 = repo.get_episode_mapping("My Show", "ep-1")
    assert m1 is not None and m1.youtube_video_url.endswith("vid0000001a") and m1.confirmed_by_user is False
    assert repo.get_episode_mapping("My Show", "ep-2") is not None
    assert repo.get_episode_mapping("My Show", "ep-3") is None

    # Second run: existing mappings are left untouched
    with (
        patch("podcast_ctl.cli.commands.mapping.resolve_input", return_value=_mock_rss_resolved(episodes)),
        patch("podcast_ctl.cli.commands.mapping.list_channel_videos", return_value=catalog),
    ):
        result2 = runner.invoke(app, ["mapping", "sync", "My Show", "--channel", "https://youtube.com/@show"])
    assert result2.exit_code == 0
    assert "Saved 0 episode mapping(s)" in result2.stdout
    assert "2 episode(s) already had a mapping" in result2.stdout


def test_mapping_sync_dry_run_saves_nothing() -> None:
    episodes = [_sync_episode("ep-1", "Episode One: Python")]
    catalog = [ChannelVideo(video_id="vid0000001a", title="Episode One: Python")]
    with (
        patch("podcast_ctl.cli.commands.mapping.resolve_input", return_value=_mock_rss_resolved(episodes)),
        patch("podcast_ctl.cli.commands.mapping.list_channel_videos", return_value=catalog),
    ):
        result = runner.invoke(
            app, ["mapping", "sync", "My Show", "--channel", "https://youtube.com/@show", "--dry-run"]
        )
    assert result.exit_code == 0
    assert "Would save 1 episode mapping(s)" in result.stdout
    assert StorageRepository().get_episode_mapping("My Show", "ep-1") is None


def test_mapping_sync_uses_stored_show_mapping_channel() -> None:
    repo = StorageRepository()
    repo.save_show_mapping(
        ShowMapping(
            feed_url="https://feed.com/rss",
            show_title="My Show",
            youtube_channel_url="https://youtube.com/@stored",
        )
    )
    episodes = [_sync_episode("ep-1", "Episode One: Python")]
    with (
        patch("podcast_ctl.cli.commands.mapping.resolve_input", return_value=_mock_rss_resolved(episodes)),
        patch("podcast_ctl.cli.commands.mapping.list_channel_videos", return_value=[]) as list_mock,
    ):
        result = runner.invoke(app, ["mapping", "sync", "My Show"])
    assert list_mock.call_args.args[0] == "https://youtube.com/@stored"
    assert result.exit_code == 1  # empty catalog is an error, but resolution used the stored channel
    assert "No videos found" in result.stderr


def test_mapping_sync_without_channel_errors() -> None:
    episodes = [_sync_episode("ep-1", "Episode One: Python")]
    with patch("podcast_ctl.cli.commands.mapping.resolve_input", return_value=_mock_rss_resolved(episodes)):
        result = runner.invoke(app, ["mapping", "sync", "My Show"])
    assert result.exit_code == 1
    assert "No YouTube channel known" in result.stderr


def test_mapping_sync_rejects_bad_threshold() -> None:
    result = runner.invoke(app, ["mapping", "sync", "My Show", "--threshold", "1.5"])
    assert result.exit_code == 2
    assert "--threshold must be in (0, 1]" in result.stderr


# =============================================================================
# Persistent log file tests
# =============================================================================


def test_log_file_is_created_next_to_the_database(tmp_path: Path) -> None:
    """Every run keeps a persistent INFO log next to the SQLite catalog."""
    # NOTE: --help exits eagerly before the app callback configures logging,
    # so a real subcommand is needed to exercise the log setup.
    result = runner.invoke(app, ["mapping", "list"])
    assert result.exit_code == 0
    log_file = tmp_path / "logs" / "podcast-ctl.log"
    assert log_file.exists()


def test_log_file_flag_overrides_location(tmp_path: Path) -> None:
    custom = tmp_path / "custom" / "run.log"
    result = runner.invoke(app, ["--log-file", str(custom), "mapping", "list"])
    assert result.exit_code == 0
    assert custom.exists()


# =============================================================================
# YouTube pacing & rate-limit UX tests
# =============================================================================


def test_transcribe_youtube_delay_flag_passed_through(tmp_path: Path) -> None:
    """--youtube-delay reaches the dispatcher (and defaults to polite pacing)."""
    mock_episode = EpisodeMetadata(
        show_title="Podcast Alpha",
        episode_title="Episode 100",
        episode_id="alpha-100",
        duration_seconds=600.0,
        audio_url="https://audio.com/100.mp3",
        source_type="rss",
    )
    mock_resolved = ResolvedSource(source_type="rss", query="https://alpha.com/feed.xml", episodes=[mock_episode])
    mock_result = TranscriptResult(
        metadata=mock_episode,
        segments=[TranscriptSegment(start=0.0, end=5.0, text="Hello world.")],
        tier_used="youtube",
    )
    with (
        patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch(
            "podcast_ctl.engines.dispatcher.TranscriptionDispatcher.transcribe",
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
                str(tmp_path),
                "--format",
                "markdown",
                "--yes",
                "--youtube-delay",
                "5",
            ],
        )
    assert result.exit_code == 0
    assert mock_transcribe.await_args.kwargs["youtube_delay"] == 5.0


def test_transcribe_youtube_delay_default(tmp_path: Path) -> None:
    """Without the flag, pacing defaults to 2s base."""
    mock_episode = EpisodeMetadata(
        show_title="Podcast Alpha",
        episode_title="Episode 100",
        episode_id="alpha-100",
        audio_url="https://audio.com/100.mp3",
        source_type="rss",
    )
    mock_resolved = ResolvedSource(source_type="rss", query="https://alpha.com/feed.xml", episodes=[mock_episode])
    mock_result = TranscriptResult(
        metadata=mock_episode,
        segments=[TranscriptSegment(start=0.0, end=5.0, text="Hello world.")],
        tier_used="youtube",
    )
    with (
        patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch(
            "podcast_ctl.engines.dispatcher.TranscriptionDispatcher.transcribe",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_transcribe,
    ):
        result = runner.invoke(
            app,
            ["transcribe", "https://alpha.com/feed.xml", "--output-dir", str(tmp_path), "--yes"],
        )
    assert result.exit_code == 0
    assert mock_transcribe.await_args.kwargs["youtube_delay"] == 2.0


def test_transcribe_reports_engine_disabled_mid_batch(tmp_path: Path) -> None:
    """A rate-limited engine is announced once and reflected in the batch summary."""
    episodes = [
        EpisodeMetadata(
            show_title="Podcast Alpha",
            episode_title=f"Episode {n}",
            episode_id=f"alpha-{n}",
            audio_url=f"https://audio.com/{n}.mp3",
            source_type="rss",
        )
        for n in (1, 2)
    ]
    mock_resolved = ResolvedSource(source_type="rss", query="https://alpha.com/feed.xml", episodes=episodes)

    async def fake_transcribe(self, episode, **kwargs):
        self._disabled_engines["youtube"] = "YouTube is rate-limiting requests from this IP (yt-dlp: HTTP 429)."
        raise TranscriptionEngineError("All transcription engines failed")

    with (
        patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch(
            "podcast_ctl.engines.dispatcher.TranscriptionDispatcher.transcribe",
            new=fake_transcribe,
        ),
    ):
        result = runner.invoke(
            app,
            [
                "transcribe",
                "https://alpha.com/feed.xml",
                "--all",
                "--output-dir",
                str(tmp_path),
                "--yes",
                "--engine",
                "youtube",
            ],
        )
    output = result.stdout + (result.stderr or "")
    assert "disabled for the rest of the batch" in output
    assert "1 remaining episode(s)" in output
    assert "disabled mid-batch after rate limiting" in output


# =============================================================================
# Error Handling UX Tests
# =============================================================================


def _run_entrypoint(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> int:
    """Invoke the production console-script entry point in-process; return the exit code."""
    monkeypatch.setattr(sys, "argv", ["podcast-ctl", *args])
    with pytest.raises(SystemExit) as exc_info:
        main_module.run()
    return exc_info.value.code if isinstance(exc_info.value.code, int) else 0


def _flat_output(capsys: pytest.CaptureFixture[str]) -> str:
    """Captured stdout with whitespace collapsed, so rich line-wrapping is harmless."""
    return " ".join(capsys.readouterr().out.split())


def test_help_lists_debug_option() -> None:
    """The global --debug switch is documented in --help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Strip ANSI styling and whitespace: rich may fold long table cells in
    # narrow environments (CI), splitting "--debug" across lines.
    flat = re.sub(r"\s+", "", re.sub(r"\x1b\[[0-9;]*m", "", result.stdout))
    assert "--debug" in flat


def test_db_path_pointing_to_directory_shows_friendly_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A directory as PODCAST_CTL_DB_PATH prints a short actionable message, not a traceback."""
    monkeypatch.setenv("PODCAST_CTL_DB_PATH", str(tmp_path))
    code = _run_entrypoint(monkeypatch, ["cache", "stats"])
    out = _flat_output(capsys)
    assert code == 1
    assert "Cannot open the SQLite database" in out
    assert "PODCAST_CTL_DB_PATH" in out
    assert "Traceback" not in out


def test_db_path_with_uncreatable_parent_shows_friendly_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unwritable data-directory location prints a short actionable message, not a traceback."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setenv("PODCAST_CTL_DB_PATH", str(blocker / "db.sqlite"))
    code = _run_entrypoint(monkeypatch, ["cache", "stats"])
    out = _flat_output(capsys)
    assert code == 1
    assert "Cannot create the data directory" in out
    assert "Traceback" not in out


def test_unexpected_error_is_summarized_and_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], isolated_db: Path
) -> None:
    """An unexpected failure prints a one-line summary and logs the full traceback to the log file."""
    def boom(self: StorageRepository) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(StorageRepository, "get_cache_stats", boom)
    code = _run_entrypoint(monkeypatch, ["cache", "stats"])
    out = _flat_output(capsys)
    assert code == 1
    assert "Unexpected error: RuntimeError: boom" in out
    assert "--debug" in out
    assert "Traceback" not in out
    log_file = isolated_db.parent / "logs" / "podcast-ctl.log"
    assert log_file.exists()
    log_text = log_file.read_text()
    assert "Traceback" in log_text
    assert "RuntimeError" in log_text


def test_debug_env_var_reraises_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """PODCAST_CTL_DEBUG=1 surfaces the full traceback (the exception propagates)."""
    monkeypatch.setenv("PODCAST_CTL_DEBUG", "1")

    def boom(self: StorageRepository) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(StorageRepository, "get_cache_stats", boom)
    monkeypatch.setattr(sys, "argv", ["podcast-ctl", "cache", "stats"])
    with pytest.raises(RuntimeError, match="boom"):
        main_module.run()


def test_debug_flag_reraises_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """--debug surfaces the full traceback (the exception propagates)."""
    def boom(self: StorageRepository) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(StorageRepository, "get_cache_stats", boom)
    monkeypatch.setattr(sys, "argv", ["podcast-ctl", "--debug", "cache", "stats"])
    with pytest.raises(RuntimeError, match="boom"):
        main_module.run()


def test_expected_errors_stay_friendly_in_debug_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Expected/user errors keep the short message even with debug mode on; tracebacks go to the log."""
    monkeypatch.setenv("PODCAST_CTL_DEBUG", "1")
    monkeypatch.setenv("PODCAST_CTL_DB_PATH", str(tmp_path))
    code = _run_entrypoint(monkeypatch, ["cache", "stats"])
    out = _flat_output(capsys)
    assert code == 1
    assert "Cannot open the SQLite database" in out
    assert "Traceback" not in out
