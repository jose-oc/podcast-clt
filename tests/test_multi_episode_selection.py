"""Tests for the multi-episode selection UX: --episodes, --match, --since/--until, --pick.

Covers the approved design: `--episode` stays the exact single selector, while
`--episodes` (lists/ranges by episode number), `--match` (title regex) and
`--since`/`--until` (publication dates) compose as a logical AND, `--pick` narrows
the result interactively, and every selection ends in the pre-flight display with
number, date, title and duration.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import questionary
from typer.testing import CliRunner

from podcast_ctl.cli import selection
from podcast_ctl.cli.commands.transcribe import _display_selected_episodes, _select_episodes_multi
from podcast_ctl.cli.main import app
from podcast_ctl.discovery.resolver import ResolvedSource
from podcast_ctl.models.transcript import EpisodeMetadata, TranscriptResult, TranscriptSegment

runner = CliRunner(env={"COLUMNS": "250"})


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ensure every test runs against an isolated temporary SQLite database."""
    db_file = tmp_path / "test_podcast_ctl.db"
    monkeypatch.setenv("PODCAST_CTL_DB_PATH", str(db_file))
    return db_file


def _ep(
    title: str,
    ep_id: str,
    number: int | None = None,
    published: str | None = None,
    duration: float | None = None,
) -> EpisodeMetadata:
    return EpisodeMetadata(
        show_title="Marketing Online",
        episode_title=title,
        episode_id=ep_id,
        episode_number=number,
        published_date=published,
        duration_seconds=duration,
        source_type="rss",
    )


def _marketing_online_like_feed() -> list[EpisodeMetadata]:
    """Feed-like list ordered newest-first with numbered titles (like the real feed)."""
    return [
        _ep("3164. Sara 5.0", "guid-3164", published="Wed, 09 Sep 2026 07:00:00 GMT", duration=1800.0),
        _ep(
            "2894. Reinicia tu negocio #9. Newsletter",
            "guid-2894",
            published="Wed, 25 Feb 2026 07:00:00 GMT",
            duration=1381.0,
        ),
        _ep("2893. SEO para SaaS", "guid-2893", published="Wed, 18 Feb 2026 07:00:00 GMT", duration=1500.0),
        _ep("2892. Kubernetes en produccion", "guid-2892", published="Wed, 11 Feb 2026 07:00:00 GMT", duration=1620.0),
        _ep("2891. Talos sin miedo", "guid-2891", published="Wed, 04 Feb 2026 07:00:00 GMT", duration=1440.0),
        _ep("2890. Newsletter de enero", "guid-2890", published="Wed, 28 Jan 2026 07:00:00 GMT", duration=1200.0),
        _ep("277. Teoria de los cliductos", "guid-277", published="Wed, 10 Jan 2024 07:00:00 GMT", duration=900.0),
    ]


# =============================================================================
# Spec parsing (--episodes)
# =============================================================================


class TestParseEpisodeNumberSpec:
    def test_single_numbers(self) -> None:
        spec = selection.parse_episode_number_spec("2890,2894,2901")
        assert spec.singles == [2890, 2894, 2901]
        assert spec.ranges == []

    def test_range(self) -> None:
        spec = selection.parse_episode_number_spec("2890..2900")
        assert spec.singles == []
        assert spec.ranges == [(2890, 2900)]

    def test_mixed_list_and_ranges_with_whitespace(self) -> None:
        spec = selection.parse_episode_number_spec(" 2894, 2890..2892 , 2901 ")
        assert spec.singles == [2894, 2901]
        assert spec.ranges == [(2890, 2892)]

    def test_empty_spec_rejected(self) -> None:
        with pytest.raises(selection.EpisodeSpecError, match="Empty episode list"):
            selection.parse_episode_number_spec(" , ,")

    def test_non_numeric_token_rejected(self) -> None:
        with pytest.raises(selection.EpisodeSpecError, match="Invalid episode number 'abc'"):
            selection.parse_episode_number_spec("2890,abc")

    def test_malformed_range_rejected(self) -> None:
        with pytest.raises(selection.EpisodeSpecError, match="Invalid range"):
            selection.parse_episode_number_spec("2890..2900..2910")

    def test_reversed_range_rejected(self) -> None:
        with pytest.raises(selection.EpisodeSpecError, match="less than or equal"):
            selection.parse_episode_number_spec("2900..2890")


# =============================================================================
# Selection by number spec
# =============================================================================


class TestSelectByNumberSpec:
    def test_list_selects_by_title_number_not_position(self) -> None:
        """Regression guard: numbers mean the episode's own number, never the feed position."""
        episodes = _marketing_online_like_feed()
        spec = selection.parse_episode_number_spec("2894,2890")
        selected, missing = selection.select_by_number_spec(episodes, spec)
        assert [ep.episode_id for ep in selected] == ["guid-2894", "guid-2890"]
        assert missing == []

    def test_range_selects_ascending_numeric_order(self) -> None:
        episodes = _marketing_online_like_feed()
        spec = selection.parse_episode_number_spec("2890..2892")
        selected, missing = selection.select_by_number_spec(episodes, spec)
        assert [ep.episode_id for ep in selected] == ["guid-2890", "guid-2891", "guid-2892"]
        assert missing == []

    def test_declared_number_wins_over_title_number(self) -> None:
        episodes = [
            _ep("2894. Title says 2894 but declares 4000", "guid-declared", number=4000),
            _ep("Other", "guid-other"),
        ]
        spec = selection.parse_episode_number_spec("4000")
        selected, _ = selection.select_by_number_spec(episodes, spec)
        assert [ep.episode_id for ep in selected] == ["guid-declared"]
        # And 2894 must NOT match that episode anymore
        spec = selection.parse_episode_number_spec("2894")
        selected, missing = selection.select_by_number_spec(episodes, spec)
        assert selected == []
        assert missing == [2894]

    def test_missing_numbers_are_reported(self) -> None:
        episodes = _marketing_online_like_feed()
        spec = selection.parse_episode_number_spec("2890,9999,2895..2897")
        selected, missing = selection.select_by_number_spec(episodes, spec)
        assert [ep.episode_id for ep in selected] == ["guid-2890"]
        assert missing == [9999, 2895, 2896, 2897]

    def test_duplicates_between_singles_and_ranges_are_removed(self) -> None:
        episodes = _marketing_online_like_feed()
        spec = selection.parse_episode_number_spec("2890,2890..2891")
        selected, _ = selection.select_by_number_spec(episodes, spec)
        assert [ep.episode_id for ep in selected] == ["guid-2890", "guid-2891"]


# =============================================================================
# Title pattern filter (--match)
# =============================================================================


class TestFilterByTitlePattern:
    def test_case_insensitive_regex_with_alternation(self) -> None:
        episodes = _marketing_online_like_feed()
        matched = selection.filter_by_title_pattern(episodes, "kubernetes|talos")
        assert [ep.episode_id for ep in matched] == ["guid-2892", "guid-2891"]

    def test_plain_substring_behaves_as_expected(self) -> None:
        episodes = _marketing_online_like_feed()
        matched = selection.filter_by_title_pattern(episodes, "NEWSLETTER")
        assert [ep.episode_id for ep in matched] == ["guid-2894", "guid-2890"]

    def test_invalid_regex_rejected(self) -> None:
        with pytest.raises(selection.EpisodeSpecError, match="Invalid title pattern"):
            selection.filter_by_title_pattern(_marketing_online_like_feed(), "(unclosed")


# =============================================================================
# Date filters (--since / --until)
# =============================================================================


class TestPublicationDates:
    def test_parse_rfc2822_date(self) -> None:
        ep = _ep("Any", "id-1", published="Wed, 10 Sep 2026 07:00:00 GMT")
        assert selection.episode_publication_date(ep) == date(2026, 9, 10)

    def test_parse_iso8601_date(self) -> None:
        ep = _ep("Any", "id-1", published="2026-09-10T07:00:00Z")
        assert selection.episode_publication_date(ep) == date(2026, 9, 10)

    def test_unparseable_date_returns_none(self) -> None:
        assert selection.episode_publication_date(_ep("Any", "id-1", published="not a date")) is None
        assert selection.episode_publication_date(_ep("Any", "id-1")) is None

    def test_cli_date_parsing(self) -> None:
        assert selection.parse_cli_date("2026-01-31") == date(2026, 1, 31)
        with pytest.raises(selection.EpisodeSpecError, match="Invalid date"):
            selection.parse_cli_date("31/01/2026")

    def test_inclusive_bounds(self) -> None:
        episodes = _marketing_online_like_feed()
        filtered, unknown = selection.filter_by_publication_date(
            episodes, since=date(2026, 2, 4), until=date(2026, 2, 11)
        )
        assert [ep.episode_id for ep in filtered] == ["guid-2892", "guid-2891"]
        assert unknown == 0

    def test_episodes_without_date_are_excluded_and_counted(self) -> None:
        episodes = [
            _ep("2894. Dated", "guid-dated", published="Wed, 25 Feb 2026 07:00:00 GMT"),
            _ep("Undated", "guid-undated"),
        ]
        filtered, unknown = selection.filter_by_publication_date(episodes, since=date(2026, 1, 1), until=None)
        assert [ep.episode_id for ep in filtered] == ["guid-dated"]
        assert unknown == 1

    def test_no_bounds_returns_everything(self) -> None:
        episodes = _marketing_online_like_feed()
        filtered, unknown = selection.filter_by_publication_date(episodes, None, None)
        assert filtered == episodes
        assert unknown == 0


# =============================================================================
# Duration formatting
# =============================================================================


class TestFormatDuration:
    def test_hours_minutes_seconds(self) -> None:
        assert selection.format_duration(3920.0) == "1h 5m 20s"

    def test_minutes_seconds(self) -> None:
        assert selection.format_duration(1381.0) == "23m 1s"

    def test_unknown_duration(self) -> None:
        assert selection.format_duration(None) == "-"
        assert selection.format_duration(0) == "-"


# =============================================================================
# Composition (_select_episodes_multi)
# =============================================================================


class TestSelectEpisodesMulti:
    def test_episodes_combined_with_match(self) -> None:
        episodes = _marketing_online_like_feed()
        selected = _select_episodes_multi(
            episodes,
            episode_filter=None,
            all_flag=False,
            latest=1,
            episodes_spec="2890..2894",
            match_pattern="kubernetes|talos",
            since=None,
            until=None,
            pick=False,
        )
        assert [ep.episode_id for ep in selected] == ["guid-2891", "guid-2892"]

    def test_match_combined_with_dates(self) -> None:
        episodes = _marketing_online_like_feed()
        selected = _select_episodes_multi(
            episodes,
            episode_filter=None,
            all_flag=False,
            latest=1,
            episodes_spec=None,
            match_pattern="newsletter",
            since=date(2026, 2, 1),
            until=None,
            pick=False,
        )
        assert [ep.episode_id for ep in selected] == ["guid-2894"]

    def test_single_episode_semantics_unchanged(self) -> None:
        episodes = _marketing_online_like_feed()
        selected = _select_episodes_multi(
            episodes,
            episode_filter="2894",
            all_flag=False,
            latest=1,
            episodes_spec=None,
            match_pattern=None,
            since=None,
            until=None,
            pick=False,
        )
        assert [ep.episode_id for ep in selected] == ["guid-2894"]


# =============================================================================
# Interactive picker (--pick)
# =============================================================================


class TestInteractivePicker:
    def test_non_interactive_terminal_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        with pytest.raises(selection.EpisodeSpecError, match="interactive terminal"):
            selection.pick_episodes_interactively(_marketing_online_like_feed())

    def test_checkbox_selection_returns_picked_episodes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        episodes = _marketing_online_like_feed()

        class FakeCheckbox:
            def __init__(self, _message: str, choices: list, validate: object = None) -> None:
                self.choices = choices

            def ask(self) -> list[int]:
                return [1, 3]  # second and fourth candidates

        monkeypatch.setattr(questionary, "checkbox", lambda *a, **kw: FakeCheckbox(*a, **kw))
        picked = selection.pick_episodes_interactively(episodes)
        assert picked is not None
        assert [ep.episode_id for ep in picked] == ["guid-2894", "guid-2892"]

    def test_cancellation_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        class Cancelled:
            def ask(self) -> None:
                return None

        monkeypatch.setattr(questionary, "checkbox", lambda *a, **kw: Cancelled())
        assert selection.pick_episodes_interactively(_marketing_online_like_feed()) is None

    def test_choice_titles_show_number_title_date_and_duration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        episodes = [
            _ep("2894. Reinicia tu negocio", "guid-2894", published="Wed, 25 Feb 2026 07:00:00 GMT", duration=1381.0)
        ]
        captured: dict[str, list] = {}

        class FakeCheckbox:
            def __init__(self, _message: str, choices: list, validate: object = None) -> None:
                captured["choices"] = choices

            def ask(self) -> list[int]:
                return [0]

        monkeypatch.setattr(questionary, "checkbox", lambda *a, **kw: FakeCheckbox(*a, **kw))
        picked = selection.pick_episodes_interactively(episodes)
        assert picked is not None and picked[0].episode_id == "guid-2894"
        title = captured["choices"][0].title
        assert "2894" in title
        assert "Reinicia tu negocio" in title
        assert "2026-02-25" in title
        assert "23m 1s" in title


# =============================================================================
# Pre-flight display includes duration
# =============================================================================


class TestPreflightDisplay:
    def test_single_episode_panel_shows_number_title_date_and_duration(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ep = _ep("2894. Reinicia tu negocio", "guid-2894", published="Wed, 25 Feb 2026 07:00:00 GMT", duration=1381.0)
        _display_selected_episodes([ep])
        out = capsys.readouterr().out
        assert "2894" in out
        assert "Reinicia tu negocio" in out
        assert "guid-2894" in out
        assert "2026-02-25" in out or "25 Feb 2026" in out
        assert "23m 1s" in out

    def test_batch_table_shows_duration_column(self, capsys: pytest.CaptureFixture[str]) -> None:
        episodes = _marketing_online_like_feed()[:2]
        _display_selected_episodes(episodes)
        out = capsys.readouterr().out
        assert "Duration" in out
        assert "30m 0s" in out
        assert "23m 1s" in out


# =============================================================================
# End-to-end CLI behavior
# =============================================================================


def _mock_transcribe_result(ep: EpisodeMetadata) -> TranscriptResult:
    return TranscriptResult(
        metadata=ep,
        segments=[TranscriptSegment(start=0.0, end=3.0, text="content")],
        tier_used="whisper",
        raw_text="content",
    )


def _run_transcribe(args: list[str], episodes: list[EpisodeMetadata]):
    mock_resolved = ResolvedSource(
        source_type="rss",
        query="https://marketing.example.com/rss",
        episodes=episodes,
    )

    def fake_transcribe(*args: object, **kwargs: object) -> TranscriptResult:
        return _mock_transcribe_result(kwargs["episode"])  # type: ignore[arg-type]

    with (
        patch("podcast_ctl.cli.commands.transcribe.resolve_input", return_value=mock_resolved),
        patch(
            "podcast_ctl.engines.dispatcher.TranscriptionDispatcher.transcribe",
            new_callable=AsyncMock,
            side_effect=fake_transcribe,
        ) as mock_transcribe,
    ):
        result = runner.invoke(app, ["transcribe", "https://marketing.example.com/rss", *args])
    return result, mock_transcribe


class TestCliMultiSelection:
    def test_episodes_list_end_to_end(self, tmp_path: Path) -> None:
        episodes = _marketing_online_like_feed()
        result, mock_transcribe = _run_transcribe(["--episodes", "2894,2890", "-o", str(tmp_path), "--yes"], episodes)
        assert result.exit_code == 0, result.output
        assert mock_transcribe.await_count == 2
        assert "Reinicia tu negocio" in result.output
        assert "Newsletter de enero" in result.output
        # List order is preserved: 2894 first, then 2890
        assert result.output.index("Reinicia tu negocio") < result.output.index("Newsletter de enero")

    def test_episodes_range_end_to_end(self, tmp_path: Path) -> None:
        episodes = _marketing_online_like_feed()
        result, mock_transcribe = _run_transcribe(["--episodes", "2891..2892", "-o", str(tmp_path), "--yes"], episodes)
        assert result.exit_code == 0, result.output
        assert mock_transcribe.await_count == 2
        # Ranges run in ascending numeric order: 2891 before 2892
        assert result.output.index("Talos sin miedo") < result.output.index("Kubernetes en produccion")

    def test_missing_number_warns_but_proceeds(self, tmp_path: Path) -> None:
        episodes = _marketing_online_like_feed()
        result, mock_transcribe = _run_transcribe(["--episodes", "2894,9999", "-o", str(tmp_path), "--yes"], episodes)
        assert result.exit_code == 0, result.output
        assert mock_transcribe.await_count == 1
        assert "9999" in result.output

    def test_match_end_to_end(self, tmp_path: Path) -> None:
        episodes = _marketing_online_like_feed()
        result, mock_transcribe = _run_transcribe(
            ["--match", "kubernetes|talos", "-o", str(tmp_path), "--yes"], episodes
        )
        assert result.exit_code == 0, result.output
        assert mock_transcribe.await_count == 2

    def test_since_until_end_to_end(self, tmp_path: Path) -> None:
        episodes = _marketing_online_like_feed()
        result, mock_transcribe = _run_transcribe(
            ["--since", "2026-02-01", "--until", "2026-02-28", "-o", str(tmp_path), "--yes"], episodes
        )
        assert result.exit_code == 0, result.output
        assert mock_transcribe.await_count == 4  # 2894, 2893, 2892, 2891 (all published in Feb 2026)

    def test_episode_cannot_combine_with_multi_flags(self) -> None:
        episodes = _marketing_online_like_feed()
        result, _ = _run_transcribe(["-e", "2894", "--episodes", "2890"], episodes)
        assert result.exit_code == 2
        assert "cannot be combined" in result.output

    def test_all_cannot_combine_with_multi_flags(self) -> None:
        episodes = _marketing_online_like_feed()
        result, _ = _run_transcribe(["--all", "--match", "seo"], episodes)
        assert result.exit_code == 2
        assert "cannot be combined" in result.output

    def test_invalid_spec_exits_with_usage_error(self) -> None:
        episodes = _marketing_online_like_feed()
        result, _ = _run_transcribe(["--episodes", "abc"], episodes)
        assert result.exit_code == 2
        assert "Invalid episode number" in result.output

    def test_since_after_until_rejected(self) -> None:
        episodes = _marketing_online_like_feed()
        result, _ = _run_transcribe(["--since", "2026-03-01", "--until", "2026-01-01"], episodes)
        assert result.exit_code == 2
        assert "on or before" in result.output

    def test_no_match_reports_empty_selection(self) -> None:
        episodes = _marketing_online_like_feed()
        result, _ = _run_transcribe(["--match", "no such topic anywhere"], episodes)
        assert result.exit_code == 1
        assert "No episodes matched" in result.output

    def test_pick_requires_interactive_terminal(self) -> None:
        episodes = _marketing_online_like_feed()
        result, _ = _run_transcribe(["--pick"], episodes)
        assert result.exit_code == 2
        assert "interactive terminal" in result.output
