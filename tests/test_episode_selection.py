"""Regression tests for episode selection semantics and pre-flight display.

Covers the reported bug: `--episode 2894` on a feed ordered newest-first
selected the episode at positional index 2894 ("277. Teoria de los cliductos")
instead of the episode whose own number is 2894.
"""

from podcast_ctl.cli.commands.transcribe import (
    _display_selected_episodes,
    _episode_number_label,
    _select_episodes,
)
from podcast_ctl.discovery import parse_feed_content
from podcast_ctl.models.transcript import EpisodeMetadata


def _ep(title: str, ep_id: str, number: int | None = None) -> EpisodeMetadata:
    return EpisodeMetadata(
        show_title="Marketing Online",
        episode_title=title,
        episode_id=ep_id,
        episode_number=number,
        source_type="rss",
    )


def _numbered_feed_like_episodes() -> list[EpisodeMetadata]:
    """Feed-like list ordered newest-first with numbers in titles.

    Mirrors the real 'Marketing Online' feed: 3100 items, newest first, so
    positional index and episode number point at different episodes.
    """
    episodes = [
        _ep("3164. Sara 5.0", "guid-3164"),
        _ep("2894. Reinicia tu negocio #9. Newsletter", "guid-2894"),
        _ep("500. Medio millar", "guid-500"),
    ]
    # Pad so positional index 2894 is in range and lands on an unrelated episode.
    episodes.extend(_ep(f" filler {i}", f"guid-filler-{i}") for i in range(2890))
    episodes.append(_ep("277. Teoria de los cliductos", "guid-277"))
    return episodes


class TestNumericEpisodeSelection:
    def test_numeric_filter_prefers_title_episode_number(self) -> None:
        """Regression: 2894 must select episode number 2894, not index 2894."""
        episodes = _numbered_feed_like_episodes()
        selected = _select_episodes(episodes, episode_filter="2894")
        assert [ep.episode_id for ep in selected] == ["guid-2894"]

    def test_numeric_filter_prefers_declared_itunes_number(self) -> None:
        episodes = [
            _ep("Newest episode", "guid-new", number=10),
            _ep("Oldest episode", "guid-old", number=1),
        ]
        selected = _select_episodes(episodes, episode_filter="1")
        assert [ep.episode_id for ep in selected] == ["guid-old"]

    def test_numeric_filter_falls_back_to_positional_index(self) -> None:
        """Documented behavior: plain 1-based index when no episode number matches."""
        episodes = [_ep("Newest episode", "guid-new"), _ep("Oldest episode", "guid-old")]
        selected = _select_episodes(episodes, episode_filter="1")
        assert [ep.episode_id for ep in selected] == ["guid-new"]

    def test_numeric_filter_out_of_range_without_number_match_returns_empty(self) -> None:
        episodes = [_ep("Newest episode", "guid-new"), _ep("Oldest episode", "guid-old")]
        assert _select_episodes(episodes, episode_filter="9999") == []

    def test_hash_prefixed_title_number_matches(self) -> None:
        episodes = [_ep("#2894 - Reinicia tu negocio", "guid-2894"), _ep("Other", "guid-other")]
        selected = _select_episodes(episodes, episode_filter="2894")
        assert [ep.episode_id for ep in selected] == ["guid-2894"]

    def test_exact_id_and_title_substring_still_work(self) -> None:
        episodes = _numbered_feed_like_episodes()
        by_id = _select_episodes(episodes, episode_filter="guid-277")
        assert [ep.episode_id for ep in by_id] == ["guid-277"]
        by_title = _select_episodes(episodes, episode_filter="cliductos")
        assert [ep.episode_id for ep in by_title] == ["guid-277"]


class TestItunesEpisodeParsing:
    FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Numbered Show</title>
    <item>
      <title>Some title without a number</title>
      <guid>guid-42</guid>
      <itunes:episode>42</itunes:episode>
      <enclosure url="https://example.com/42.mp3" type="audio/mpeg" />
    </item>
    <item>
      <title>Another episode</title>
      <guid>guid-abc</guid>
      <itunes:episode>not-a-number</itunes:episode>
    </item>
  </channel>
</rss>
"""

    def test_itunes_episode_number_is_parsed(self) -> None:
        _show, episodes = parse_feed_content(self.FEED, feed_url="https://example.com/feed.xml")
        assert episodes[0].episode_number == 42

    def test_non_numeric_itunes_episode_is_ignored(self) -> None:
        _show, episodes = parse_feed_content(self.FEED, feed_url="https://example.com/feed.xml")
        assert episodes[1].episode_number is None


class TestSelectedEpisodeDisplay:
    def test_episode_number_label(self) -> None:
        assert _episode_number_label(_ep("Any", "id-1", number=7)) == "7"
        assert _episode_number_label(_ep("2894. Reinicia tu negocio", "id-2")) == "2894"
        assert _episode_number_label(_ep("No number here", "id-3")) == "-"

    def test_display_single_and_multiple_episodes(self, capsys) -> None:  # type: ignore[no-untyped-def]
        single = _ep("2894. Reinicia tu negocio #9. Newsletter", "guid-2894")
        _display_selected_episodes([single])
        out = capsys.readouterr().out
        assert "2894" in out
        assert "Reinicia tu negocio" in out
        assert "guid-2894" in out

        episodes = _numbered_feed_like_episodes()
        _display_selected_episodes(episodes)
        out = capsys.readouterr().out
        assert "Selected episodes" in out
        assert "more episode(s)" in out  # preview capped at 20 rows
