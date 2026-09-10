"""Integration tests against real external services.

These tests hit the live network: the iTunes Search API, public podcast RSS
feeds, and YouTube. They are marked with the ``integration`` marker so the
fast unit-test job can exclude them (``pytest -m "not integration"``); a
dedicated CI job runs them with ``pytest -m integration``.

Stability policy
----------------
- Transient infrastructure failures (connect/timeouts, HTTP 5xx, 429) and
  provider-side IP blocks (YouTube bot checks, which are expected on most
  datacenter IPs, including CI runners) cause a SKIP, not a failure.
- Content assertions (structure, non-empty data, Spanish-language content)
  DO fail. A skipped test means "could not reach the service", never
  "the service returned something unexpected".

Real-world subjects (both Spanish podcasts):
- Radio Fitness Revolucionario (Marcos Vazquez): RSS-only podcast, no
  Podcasting 2.0 transcript tags and no matching YouTube channel.
- monos estocasticos (Antonio Ortiz & Matias S. Zavia): podcast with an RSS
  feed (Cuonda) and a YouTube channel that publishes every episode with
  captions.
"""

from __future__ import annotations

import httpx
import pytest

from podcast_ctl.discovery.itunes import PodcastSearchResult, search_itunes
from podcast_ctl.discovery.rss import EpisodeMetadata, fetch_and_parse_feed
from podcast_ctl.engines.base import TranscriptNotFoundError
from podcast_ctl.engines.rss_engine import RSSTranscriptionEngine
from podcast_ctl.engines.youtube_engine import YouTubeTranscriptionEngine

pytestmark = pytest.mark.integration

RFR_FEED_URL = "https://www.fitnessrevolucionario.com/feed/podcast"
RFR_SHOW_TITLE = "Radio Fitness Revolucionario"

MONOS_FEED_URL = "https://cuonda.com/monos-estocasticos/feed"
MONOS_SHOW_TITLE = "monos estocásticos"
MONOS_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PL-6s6cUsxTnsY_V0rqQFURaHDYuXD0AXj"
# Fallback episode if the playlist cannot be enumerated (video from the
# official monos estocásticos playlist).
MONOS_FALLBACK_VIDEO_ID = "M7STSpVnaqk"

YOUTUBE_BLOCK_MARKERS = (
    "sign in to confirm",
    "blocking requests from your ip",
    "requestblocked",
    "ipblocked",
    "too many requests",
    "http error 429",
)


def _skip_if_transient_http(exc: httpx.HTTPError) -> None:
    """Skip the test for transient HTTP failures; re-raise anything else."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status >= 500 or status in (408, 409, 425, 429):
            pytest.skip(f"Transient HTTP {status} from remote service: {exc}")
        return  # 4xx (other than above) is a real response: let the test fail
    pytest.skip(f"Transient network error contacting remote service: {exc!r}")


def _skip_if_youtube_blocked(exc: Exception) -> None:
    """Skip when YouTube refuses the request because of the caller IP."""
    message = str(exc).lower()
    if any(marker in message for marker in YOUTUBE_BLOCK_MARKERS):
        pytest.skip(f"YouTube is blocking requests from this IP (expected on CI runners): {exc}")


def _search_or_skip(query: str) -> list[PodcastSearchResult]:
    """iTunes search that skips (not fails) when the API itself is unreachable.

    ``search_itunes`` swallows network errors and returns ``[]``, so an empty
    result is ambiguous. Resolve the ambiguity with a raw API request.
    """
    results = search_itunes(query, limit=10)
    if results:
        return results
    try:
        resp = httpx.get(
            "https://itunes.apple.com/search",
            params={"term": query, "media": "podcast", "entity": "podcast", "limit": 10},
            timeout=15.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        _skip_if_transient_http(exc)
        pytest.skip(f"iTunes Search API unreachable: {exc!r}")
    pytest.fail(f"iTunes Search API reachable but returned no results for {query!r}")
    return []  # pragma: no cover - pytest.fail raises


def _fetch_feed_or_skip(feed_url: str) -> tuple[object, list[EpisodeMetadata]]:
    try:
        return fetch_and_parse_feed(feed_url, timeout=20.0)
    except httpx.HTTPError as exc:
        _skip_if_transient_http(exc)
        pytest.fail(f"Feed {feed_url} returned a non-transient HTTP error: {exc}")
    return None, []  # pragma: no cover - the branches above always raise


def _spanish_marker_count(texts: list[str]) -> int:
    """Count texts containing characters/words typical of Spanish."""
    markers = ("¿", "¡", "ñ", "á", "é", "í", "ó", "ú")
    return sum(1 for t in texts if any(m in t.lower() for m in markers))


# ---------------------------------------------------------------------------
# Radio Fitness Revolucionario: RSS discovery and parsing (Spanish podcast)
# ---------------------------------------------------------------------------


class TestRadioFitnessRevolucionarioRSS:
    def test_itunes_search_finds_show_with_feed(self) -> None:
        results = _search_or_skip(RFR_SHOW_TITLE)
        match = next((r for r in results if r.title == RFR_SHOW_TITLE), None)
        assert match is not None, f"{RFR_SHOW_TITLE!r} not in iTunes results: {[r.title for r in results]}"
        assert match.feed_url, "iTunes result has no feed URL"
        assert match.feed_url.startswith("https://")

    def test_feed_parses_spanish_episodes_with_audio(self) -> None:
        show, episodes = _fetch_feed_or_skip(RFR_FEED_URL)

        assert show.title == RFR_SHOW_TITLE  # type: ignore[attr-defined]
        assert len(episodes) >= 100, f"Expected a long-running feed, got {len(episodes)} episodes"

        sample = episodes[:20]
        assert all(e.audio_url and e.audio_url.startswith("http") for e in sample)
        assert all(e.episode_title.strip() for e in sample)
        # Recent episodes should carry itunes durations.
        assert any(e.duration_seconds and e.duration_seconds > 300 for e in sample)
        # The podcast is in Spanish: most episode titles use Spanish markers.
        titles = [e.episode_title for e in sample]
        assert _spanish_marker_count(titles) >= len(titles) // 3, (
            f"Titles do not look Spanish: {titles[:5]}"
        )

    @pytest.mark.asyncio
    async def test_rss_tier_reports_no_transcript_for_this_feed(self) -> None:
        """The feed has no Podcasting 2.0 transcript tags: Tier 1 must decline."""
        _show, episodes = _fetch_feed_or_skip(RFR_FEED_URL)
        latest = episodes[0]
        assert not latest.rss_transcripts, (
            "Feed now publishes <podcast:transcript> tags: update this test to assert a Tier 1 download instead"
        )

        engine = RSSTranscriptionEngine()
        assert engine.is_available()
        with pytest.raises(TranscriptNotFoundError):
            await engine.transcribe(latest)


# ---------------------------------------------------------------------------
# monos estocásticos: RSS feed and YouTube captions (Spanish podcast)
# ---------------------------------------------------------------------------


class TestMonosEstocasticos:
    def test_itunes_search_finds_show_with_feed(self) -> None:
        results = _search_or_skip("monos estocásticos")
        match = next((r for r in results if r.title.lower() == MONOS_SHOW_TITLE), None)
        assert match is not None, f"{MONOS_SHOW_TITLE!r} not in iTunes results: {[r.title for r in results]}"
        assert match.feed_url and match.feed_url.startswith("https://")

    def test_feed_parses_episodes(self) -> None:
        show, episodes = _fetch_feed_or_skip(MONOS_FEED_URL)
        assert MONOS_SHOW_TITLE in show.title.lower()  # type: ignore[union-attr]
        assert len(episodes) >= 50, f"Expected a long-running feed, got {len(episodes)} episodes"
        sample = episodes[:10]
        assert all(e.episode_title.strip() for e in sample)

    def _resolve_monos_video_id(self) -> str:
        """Resolve the latest episode video ID from the official playlist."""
        try:
            import yt_dlp

            opts = {"extract_flat": True, "quiet": True, "no_warnings": True}
            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[attr-defined]
                info = ydl.extract_info(MONOS_PLAYLIST_URL, download=False)
            entries = [e for e in info.get("entries", []) if e and e.get("id")]
            if entries:
                return entries[0]["id"]
        except Exception as exc:
            _skip_if_youtube_blocked(exc)
        return MONOS_FALLBACK_VIDEO_ID

    @pytest.mark.asyncio
    async def test_youtube_tier_fetches_spanish_captions(self) -> None:
        """Tier 2 must return real Spanish captions for a monos estocásticos episode.

        YouTube blocks caption endpoints from many datacenter IPs (CI runners
        included); in that case the test skips instead of failing.
        """
        video_id = self._resolve_monos_video_id()
        engine = YouTubeTranscriptionEngine(preferred_languages=["es", "es-ES", "en"])
        assert engine.is_available()

        episode = EpisodeMetadata(
            show_title=MONOS_SHOW_TITLE,
            episode_title=f"integration:{video_id}",
            episode_id=f"https://www.youtube.com/watch?v={video_id}",
            show_id=MONOS_SHOW_TITLE,
            source_type="youtube",
        )
        try:
            result = await engine.transcribe(episode)
        except TranscriptNotFoundError as exc:
            _skip_if_youtube_blocked(exc)
            pytest.fail(f"Captions unexpectedly unavailable for video {video_id}: {exc}")
            return  # pragma: no cover

        assert result.tier_used == "youtube"
        assert len(result.segments) > 100, f"Suspiciously few caption segments: {len(result.segments)}"
        text_sample = " ".join(s.text for s in result.segments[:200]).lower()
        assert _spanish_marker_count([s.text for s in result.segments[:50]]) >= 5, (
            f"Captions do not look Spanish: {text_sample[:200]}"
        )
        for seg in result.segments[:20]:
            assert seg.end >= seg.start
            assert seg.text.strip()
