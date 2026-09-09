"""Comprehensive unit tests for the discovery and ingestion engine."""

import json
from pathlib import Path
import subprocess
import wave
import httpx
import pytest
import respx

from podcast_cli.discovery import (
    ITUNES_LOOKUP_URL,
    ITUNES_SEARCH_URL,
    PodcastSearchResult,
    ResolvedSource,
    ShowMetadata,
    extract_youtube_video_id,
    fetch_and_parse_feed,
    get_youtube_subtitles_metadata,
    get_youtube_video_info,
    inspect_local_file,
    is_supported_audio_file,
    is_youtube_url,
    lookup_itunes,
    lookup_podcast,
    parse_duration,
    parse_feed_content,
    parse_youtube_url,
    probe_media_file,
    resolve_input,
    search_itunes,
    search_podcast,
    search_youtube_candidates,
    youtube_video_to_metadata,
)
from podcast_cli.models.transcript import EpisodeMetadata

# =============================================================================
# 1. iTunes Search & Lookup Tests
# =============================================================================

SAMPLE_ITUNES_SEARCH_RESPONSE = {
    "resultCount": 2,
    "results": [
        {
            "wrapperType": "track",
            "kind": "podcast",
            "collectionId": 1545953110,
            "trackId": 1545953110,
            "artistName": "Scicomm Media",
            "collectionName": "Huberman Lab",
            "trackName": "Huberman Lab",
            "feedUrl": "https://feeds.megaphone.fm/hubermanlab",
            "artworkUrl600": "https://is1-ssl.mzstatic.com/image/thumb/huberman.jpg",
            "releaseDate": "2024-03-04T08:00:00Z",
            "country": "USA",
            "primaryGenreName": "Health & Fitness",
            "trackCount": 180,
            "genres": ["Health & Fitness", "Podcasts", "Science"],
        },
        {
            "wrapperType": "track",
            "kind": "podcast",
            "collectionId": 1234567890,
            "trackId": 1234567890,
            "artistName": "Lex Fridman",
            "collectionName": "Lex Fridman Podcast",
            "trackName": "Lex Fridman Podcast",
            "feedUrl": "https://lexfridman.com/feed/podcast/",
            "artworkUrl100": "https://lexfridman.com/art.jpg",
            "releaseDate": "2024-03-01T12:00:00Z",
            "country": "USA",
            "primaryGenreName": "Technology",
            "trackCount": 420,
            "genres": ["Technology"],
        },
    ],
}


class TestItunesDiscovery:
    @respx.mock
    def test_search_itunes_success(self) -> None:
        respx.get(ITUNES_SEARCH_URL).mock(
            return_value=httpx.Response(200, json=SAMPLE_ITUNES_SEARCH_RESPONSE)
        )

        results = search_itunes("Huberman", limit=2)
        assert len(results) == 2
        assert isinstance(results[0], PodcastSearchResult)
        assert results[0].title == "Huberman Lab"
        assert results[0].author == "Scicomm Media"
        assert results[0].feed_url == "https://feeds.megaphone.fm/hubermanlab"
        assert results[0].artwork_url == "https://is1-ssl.mzstatic.com/image/thumb/huberman.jpg"
        assert results[0].episode_count == 180
        assert results[0].collection_id == 1545953110
        assert "Health & Fitness" in results[0].genres
        assert results[0].country == "USA"

        # Alias verification
        alias_results = search_podcast("Huberman", limit=2)
        assert len(alias_results) == 2

    @respx.mock
    def test_search_itunes_empty_and_error(self) -> None:
        # Empty query
        assert search_itunes("") == []
        assert search_itunes("   ") == []

        # Empty result from API
        respx.get(ITUNES_SEARCH_URL).mock(
            return_value=httpx.Response(200, json={"resultCount": 0, "results": []})
        )
        assert search_itunes("NonExistentPodcastXYZ") == []

        # HTTP error handling
        respx.get(ITUNES_SEARCH_URL).mock(return_value=httpx.Response(500))
        assert search_itunes("error query") == []

    @respx.mock
    def test_lookup_itunes_success(self) -> None:
        respx.get(ITUNES_LOOKUP_URL).mock(
            return_value=httpx.Response(
                200,
                json={"resultCount": 1, "results": [SAMPLE_ITUNES_SEARCH_RESPONSE["results"][0]]},
            )
        )

        res = lookup_itunes(1545953110)
        assert res is not None
        assert res.collection_id == 1545953110
        assert res.title == "Huberman Lab"
        assert res.author == "Scicomm Media"
        assert res.feed_url == "https://feeds.megaphone.fm/hubermanlab"

        # Alias verification
        alias_res = lookup_podcast("1545953110")
        assert alias_res is not None
        assert alias_res.title == "Huberman Lab"

    @respx.mock
    def test_lookup_itunes_not_found(self) -> None:
        assert lookup_itunes("") is None

        respx.get(ITUNES_LOOKUP_URL).mock(
            return_value=httpx.Response(200, json={"resultCount": 0, "results": []})
        )
        assert lookup_itunes(999999999999) is None

        respx.get(ITUNES_LOOKUP_URL).mock(return_value=httpx.Response(500))
        assert lookup_itunes(1545953110) is None


# =============================================================================
# 2. Duration Parser Tests
# =============================================================================


class TestDurationParser:
    def test_numeric_seconds(self) -> None:
        assert parse_duration(1800) == 1800.0
        assert parse_duration(1800.5) == 1800.5
        assert parse_duration("1800") == 1800.0
        assert parse_duration("1800.5") == 1800.5
        assert parse_duration(0) == 0.0

    def test_mm_ss_format(self) -> None:
        assert parse_duration("45:30") == 2730.0
        assert parse_duration("05:00") == 300.0
        assert parse_duration("5:00") == 300.0
        assert parse_duration("00:45") == 45.0
        assert parse_duration("45:30.500") == 2730.5

    def test_hh_mm_ss_format(self) -> None:
        assert parse_duration("01:15:30") == 4530.0
        assert parse_duration("1:02:03") == 3723.0
        assert parse_duration("00:01:05") == 65.0
        assert parse_duration("01:15:30.500") == 4530.5

    def test_dd_hh_mm_ss_format(self) -> None:
        assert parse_duration("1:00:00:00") == 86400.0

    def test_iso_8601_duration(self) -> None:
        assert parse_duration("PT1H30M15S") == 5415.0
        assert parse_duration("PT45M") == 2700.0
        assert parse_duration("PT30S") == 30.0
        assert parse_duration("PT1H") == 3600.0
        assert parse_duration("pt1h30m") == 5400.0

    def test_invalid_durations(self) -> None:
        assert parse_duration(None) is None
        assert parse_duration("") is None
        assert parse_duration("   ") is None
        assert parse_duration("invalid_string") is None
        assert parse_duration("abc:def") is None
        assert parse_duration(-50) is None
        assert parse_duration([]) is None


# =============================================================================
# 3. RSS & Podcasting 2.0 Parser Tests
# =============================================================================

SAMPLE_PODCASTING_20_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://podcastindex.org/namespace/1.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Podcasting 2.0 Showcase</title>
    <link>https://podcastindex.org/showcase</link>
    <description>Demonstrating Podcasting 2.0 tags and transcripts</description>
    <itunes:author>Podcasting 2.0 Working Group</itunes:author>
    <itunes:image href="https://example.com/show_art.jpg" />
    <language>en-US</language>

    <item>
      <title>Episode 101: The Future of Podcasting</title>
      <guid isPermaLink="false">pod-ep-101-guid</guid>
      <pubDate>Mon, 04 Mar 2024 12:00:00 GMT</pubDate>
      <enclosure url="https://example.com/audio/ep101.mp3" length="45000000" type="audio/mpeg" />
      <itunes:duration>01:15:30</itunes:duration>
      <!-- Multiple Podcasting 2.0 Transcripts -->
      <podcast:transcript url="https://example.com/transcripts/ep101.json" type="application/json" language="en" rel="captions" />
      <podcast:transcript url="https://example.com/transcripts/ep101.vtt" type="text/vtt" language="en" />
      <podcast:transcript url="https://example.com/transcripts/ep101.srt" type="application/srt" language="en" />
      <podcast:transcript url="https://example.com/transcripts/ep101_es.vtt" type="text/vtt" language="es" />
    </item>

    <item>
      <title>Episode 100: Retrospective</title>
      <guid isPermaLink="false">pod-ep-100-guid</guid>
      <pubDate>Mon, 26 Feb 2024 12:00:00 GMT</pubDate>
      <enclosure url="https://example.com/audio/ep100.m4a" length="35000000" type="audio/x-m4a" />
      <itunes:duration>45:20</itunes:duration>
      <podcast:transcript url="https://example.com/transcripts/ep100.vtt" type="text/vtt" />
    </item>

    <item>
      <title>Episode 99: No Transcripts Legacy</title>
      <guid isPermaLink="false">pod-ep-099-guid</guid>
      <pubDate>Mon, 19 Feb 2024 12:00:00 GMT</pubDate>
      <enclosure url="https://example.com/audio/ep99.mp3" length="30000000" type="audio/mpeg" />
      <itunes:duration>1800</itunes:duration>
    </item>
  </channel>
</rss>
"""


class TestRssDiscovery:
    def test_parse_feed_content_podcasting_20(self) -> None:
        show_meta, episodes = parse_feed_content(
            SAMPLE_PODCASTING_20_FEED, feed_url="https://example.com/feed.xml"
        )

        assert isinstance(show_meta, ShowMetadata)
        assert show_meta.title == "Podcasting 2.0 Showcase"
        assert show_meta.author == "Podcasting 2.0 Working Group"
        assert show_meta.feed_url == "https://example.com/feed.xml"
        assert show_meta.image_url == "https://example.com/show_art.jpg"
        assert show_meta.total_episodes == 3

        assert len(episodes) == 3

        # Episode 101 with 4 transcript variants
        ep101 = episodes[0]
        assert ep101.episode_title == "Episode 101: The Future of Podcasting"
        assert ep101.show_title == "Podcasting 2.0 Showcase"
        assert ep101.episode_id == "pod-ep-101-guid"
        assert ep101.audio_url == "https://example.com/audio/ep101.mp3"
        assert ep101.duration_seconds == 4530.0
        assert ep101.published_date == "Mon, 04 Mar 2024 12:00:00 GMT"
        assert ep101.source_type == "rss"

        assert len(ep101.rss_transcripts) == 4
        assert ep101.rss_transcripts[0] == {
            "url": "https://example.com/transcripts/ep101.json",
            "type": "application/json",
            "language": "en",
            "rel": "captions",
        }
        assert ep101.rss_transcripts[1] == {
            "url": "https://example.com/transcripts/ep101.vtt",
            "type": "text/vtt",
            "language": "en",
        }
        assert ep101.rss_transcripts[3] == {
            "url": "https://example.com/transcripts/ep101_es.vtt",
            "type": "text/vtt",
            "language": "es",
        }

        # Episode 100 with 1 transcript
        ep100 = episodes[1]
        assert ep100.episode_title == "Episode 100: Retrospective"
        assert ep100.duration_seconds == 2720.0
        assert len(ep100.rss_transcripts) == 1
        assert ep100.rss_transcripts[0]["url"] == "https://example.com/transcripts/ep100.vtt"

        # Episode 99 with no transcript
        ep99 = episodes[2]
        assert ep99.episode_title == "Episode 99: No Transcripts Legacy"
        assert ep99.duration_seconds == 1800.0
        assert ep99.rss_transcripts == []

    @respx.mock
    def test_fetch_and_parse_feed(self) -> None:
        feed_url = "https://feeds.example.com/podcast.xml"
        respx.get(feed_url).mock(return_value=httpx.Response(200, text=SAMPLE_PODCASTING_20_FEED))

        show_meta, episodes = fetch_and_parse_feed(feed_url)
        assert show_meta.title == "Podcasting 2.0 Showcase"
        assert len(episodes) == 3

    def test_parse_empty_or_invalid_feed(self) -> None:
        show_meta, episodes = parse_feed_content("")
        assert show_meta.total_episodes == 0
        assert episodes == []

        show_meta2, episodes2 = parse_feed_content("Not valid XML <><>")
        assert episodes2 == []


# =============================================================================
# 4. YouTube Detection, Search & Inspection Tests
# =============================================================================


class TestYouTubeDiscovery:
    def test_is_youtube_url(self) -> None:
        assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True
        assert is_youtube_url("http://youtube.com/watch?v=dQw4w9WgXcQ&t=10s") is True
        assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True
        assert is_youtube_url("https://youtube.com/shorts/dQw4w9WgXcQ") is True
        assert is_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcQ") is True
        assert is_youtube_url("https://www.youtube.com/playlist?list=PL123456789") is True
        assert is_youtube_url("https://www.youtube.com/@hubermanlab") is True
        assert is_youtube_url("https://www.youtube.com/channel/UC2D2CMWXMOVWxXX134Z301g") is True
        assert is_youtube_url("dQw4w9WgXcQ") is True

        assert is_youtube_url("https://example.com/audio.mp3") is False
        assert is_youtube_url("not a url") is False
        assert is_youtube_url("") is False

    def test_extract_youtube_video_id(self) -> None:
        assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert extract_youtube_video_id("https://www.youtube.com/playlist?list=PL123") is None
        assert extract_youtube_video_id("invalid") is None

    def test_parse_youtube_url(self) -> None:
        # Video URL
        v_res = parse_youtube_url("https://youtu.be/dQw4w9WgXcQ")
        assert v_res["type"] == "video"
        assert v_res["id"] == "dQw4w9WgXcQ"
        assert v_res["normalized_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        # Playlist URL
        p_res = parse_youtube_url("https://www.youtube.com/playlist?list=PL123456789")
        assert p_res["type"] == "playlist"
        assert p_res["id"] == "PL123456789"

        # Channel URL
        c_res = parse_youtube_url("https://www.youtube.com/@hubermanlab")
        assert c_res["type"] == "channel"
        assert c_res["id"] == "@hubermanlab"

    def test_search_youtube_candidates_mocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_info = {
            "entries": [
                {
                    "id": "abc12345678",
                    "title": "Huberman Lab - Focus & Concentration",
                    "duration": 5400,
                    "channel": "Andrew Huberman",
                    "channel_id": "UCHuberman",
                    "upload_date": "20240101",
                    "view_count": 1500000,
                },
                {
                    "id": "xyz98765432",
                    "title": "Huberman Lab - Sleep Toolkit",
                    "duration": 4800,
                    "channel": "Andrew Huberman",
                    "channel_id": "UCHuberman",
                    "upload_date": "20240115",
                    "view_count": 2200000,
                },
            ]
        }

        class MockYoutubeDL:
            def __init__(self, opts: dict) -> None:
                pass

            def __enter__(self) -> "MockYoutubeDL":
                return self

            def __exit__(self, *args: object) -> None:
                pass

            def extract_info(self, url: str, download: bool = False) -> dict:
                return mock_info

        monkeypatch.setattr("yt_dlp.YoutubeDL", MockYoutubeDL)

        candidates = search_youtube_candidates("Huberman Lab Focus", max_results=2)
        assert len(candidates) == 2
        assert candidates[0]["id"] == "abc12345678"
        assert candidates[0]["title"] == "Huberman Lab - Focus & Concentration"
        assert candidates[0]["duration"] == 5400.0
        assert candidates[0]["url"] == "https://www.youtube.com/watch?v=abc12345678"
        assert candidates[0]["channel"] == "Andrew Huberman"

    def test_get_youtube_subtitles_metadata_mocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_video_info = {
            "id": "abc12345678",
            "title": "Mock Video",
            "channel": "Test Channel",
            "duration": 3600,
            "subtitles": {
                "en": [{"ext": "vtt", "url": "https://example.com/en.vtt"}],
                "es": [{"ext": "vtt", "url": "https://example.com/es.vtt"}],
            },
            "automatic_captions": {
                "en": [{"ext": "srv1", "url": "https://example.com/auto_en"}],
                "fr": [{"ext": "srv1", "url": "https://example.com/auto_fr"}],
            },
        }

        monkeypatch.setattr(
            "podcast_cli.discovery.youtube.get_youtube_video_info",
            lambda url, **kwargs: mock_video_info,
        )

        sub_meta = get_youtube_subtitles_metadata("https://www.youtube.com/watch?v=abc12345678")
        assert sub_meta["has_subtitles"] is True
        assert "en" in sub_meta["manual_languages"]
        assert "es" in sub_meta["manual_languages"]
        assert "fr" in sub_meta["auto_languages"]
        assert set(sub_meta["languages"]) == {"en", "es", "fr"}

    def test_youtube_video_to_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_video_info = {
            "id": "abc12345678",
            "title": "Deep Dive into AI",
            "channel": "Tech Insights",
            "channel_id": "UC12345",
            "webpage_url": "https://www.youtube.com/watch?v=abc12345678",
            "duration": 1800,
            "upload_date": "20240201",
        }

        monkeypatch.setattr(
            "podcast_cli.discovery.youtube.get_youtube_video_info",
            lambda url, **kwargs: mock_video_info,
        )

        ep_meta = youtube_video_to_metadata("https://www.youtube.com/watch?v=abc12345678")
        assert isinstance(ep_meta, EpisodeMetadata)
        assert ep_meta.show_title == "Tech Insights"
        assert ep_meta.episode_title == "Deep Dive into AI"
        assert ep_meta.episode_id == "abc12345678"
        assert ep_meta.audio_url == "https://www.youtube.com/watch?v=abc12345678"
        assert ep_meta.duration_seconds == 1800.0
        assert ep_meta.source_type == "youtube"


# =============================================================================
# 5. Local File Discovery Tests
# =============================================================================


class TestLocalFileDiscovery:
    def test_is_supported_audio_file(self) -> None:
        assert is_supported_audio_file("episode.mp3") is True
        assert is_supported_audio_file("track.m4a") is True
        assert is_supported_audio_file("audio.wav") is True
        assert is_supported_audio_file("sound.flac") is True
        assert is_supported_audio_file("stream.ogg") is True
        assert is_supported_audio_file("video.mp4") is True
        assert is_supported_audio_file("clip.opus") is True

        assert is_supported_audio_file("document.pdf") is False
        assert is_supported_audio_file("script.py") is False
        assert is_supported_audio_file("") is False

    def test_inspect_local_wav_file(self, tmp_path: Path) -> None:
        # Create a synthetic 1-second 44100Hz mono wav file
        wav_file = tmp_path / "test_episode.wav"
        n_channels = 1
        sampwidth = 2
        framerate = 44100
        n_frames = 44100  # 1.0 second

        with wave.open(str(wav_file), "w") as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(framerate)
            wf.writeframes(b"\x00" * (n_frames * n_channels * sampwidth))

        ep_meta = inspect_local_file(wav_file)
        assert isinstance(ep_meta, EpisodeMetadata)
        assert ep_meta.episode_title == "test_episode"
        assert ep_meta.duration_seconds == 1.0
        assert ep_meta.source_type == "local"
        assert ep_meta.episode_id.startswith("local_")
        assert Path(ep_meta.audio_url).resolve() == wav_file.resolve()

    def test_inspect_local_file_with_ffprobe_mock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mp3_file = tmp_path / "sample.mp3"
        mp3_file.write_bytes(b"fake mp3 data")

        mock_probe = {
            "format": {
                "duration": "245.50",
                "tags": {
                    "title": "Interview with Expert",
                    "artist": "Science Hour",
                    "album": "Season 2",
                    "date": "2024-02-15",
                },
            },
            "streams": [{"codec_type": "audio", "duration": "245.50"}],
        }

        def mock_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(mock_probe), stderr=""
            )

        monkeypatch.setattr("shutil.which", lambda bin_name: "/usr/bin/ffprobe")
        monkeypatch.setattr("subprocess.run", mock_run)

        ep_meta = inspect_local_file(mp3_file)
        assert ep_meta.episode_title == "Interview with Expert"
        assert ep_meta.show_title == "Science Hour"
        assert ep_meta.duration_seconds == 245.50
        assert ep_meta.published_date == "2024-02-15"
        assert ep_meta.source_type == "local"

    def test_inspect_local_file_errors(self, tmp_path: Path) -> None:
        # Non-existent file
        with pytest.raises(FileNotFoundError):
            inspect_local_file(tmp_path / "does_not_exist.mp3")

        # Directory instead of file
        with pytest.raises(ValueError, match="not a regular file"):
            inspect_local_file(tmp_path)

        # Unsupported file extension
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported media file format"):
            inspect_local_file(txt_file)


# =============================================================================
# 6. Unified Source Resolver Tests
# =============================================================================


class TestUnifiedResolver:
    def test_resolve_local_file(self, tmp_path: Path) -> None:
        wav_file = tmp_path / "recording.wav"
        with wave.open(str(wav_file), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(b"\x00" * 32000)  # 2.0 seconds (8000 frames * 1 chan * 2 bytes)

        resolved = resolve_input(str(wav_file))
        assert isinstance(resolved, ResolvedSource)
        assert resolved.source_type == "local"
        assert resolved.is_single_episode is True
        assert resolved.total_duration_seconds == 2.0
        assert resolved.episodes[0].episode_title == "recording"

    def test_resolve_youtube_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_video_info = {
            "id": "dQw4w9WgXcQ",
            "title": "Never Gonna Give You Up",
            "channel": "Rick Astley",
            "duration": 213,
            "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }
        monkeypatch.setattr(
            "podcast_cli.discovery.youtube.get_youtube_video_info",
            lambda url, **kwargs: mock_video_info,
        )

        resolved = resolve_input("https://youtu.be/dQw4w9WgXcQ")
        assert resolved.source_type == "youtube"
        assert resolved.is_single_episode is True
        assert resolved.episodes[0].episode_title == "Never Gonna Give You Up"
        assert resolved.episodes[0].duration_seconds == 213.0

    @respx.mock
    def test_resolve_rss_feed_url(self) -> None:
        feed_url = "https://feeds.example.com/podcast.xml"
        respx.get(feed_url).mock(return_value=httpx.Response(200, text=SAMPLE_PODCASTING_20_FEED))

        resolved = resolve_input(feed_url)
        assert resolved.source_type == "rss"
        assert resolved.show_metadata is not None
        assert resolved.show_metadata.title == "Podcasting 2.0 Showcase"
        assert len(resolved.episodes) == 3
        assert resolved.is_single_episode is False
        assert resolved.total_duration_seconds == (4530.0 + 2720.0 + 1800.0)

    @respx.mock
    def test_resolve_plain_text_search(self) -> None:
        respx.get(ITUNES_SEARCH_URL).mock(
            return_value=httpx.Response(200, json=SAMPLE_ITUNES_SEARCH_RESPONSE)
        )

        resolved = resolve_input("Huberman Lab", search_limit=2)
        assert resolved.source_type == "search"
        assert len(resolved.search_results) == 2
        assert resolved.search_results[0].title == "Huberman Lab"

    def test_resolve_empty_input(self) -> None:
        resolved = resolve_input("")
        assert resolved.source_type == "search"
        assert resolved.search_results == []

    def test_resolve_file_uri_prefix(self, tmp_path: Path) -> None:
        wav_file = tmp_path / "recording.wav"
        with wave.open(str(wav_file), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(b"\x00" * 16000)

        resolved = resolve_input(f"file://{wav_file}")
        assert resolved.source_type == "local"
        assert len(resolved.episodes) == 1

    def test_resolve_youtube_playlist_and_channel(self) -> None:
        p_res = resolve_input("https://www.youtube.com/playlist?list=PL123456789")
        assert p_res.source_type == "youtube"
        assert p_res.raw_data is not None
        assert p_res.raw_data["type"] == "playlist"
        assert p_res.raw_data["id"] == "PL123456789"

        c_res = resolve_input("https://www.youtube.com/@hubermanlab")
        assert c_res.source_type == "youtube"
        assert c_res.raw_data is not None
        assert c_res.raw_data["type"] == "channel"
        assert c_res.raw_data["id"] == "@hubermanlab"

    @respx.mock
    def test_resolve_rss_failure_returns_graceful_result(self) -> None:
        respx.get("https://bad.example.com/feed.xml").mock(return_value=httpx.Response(500))
        resolved = resolve_input("https://bad.example.com/feed.xml")
        assert resolved.source_type == "rss"
        assert resolved.episodes == []
        assert resolved.show_metadata is not None
        assert resolved.show_metadata.title == "Failed Feed"

