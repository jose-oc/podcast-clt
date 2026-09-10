# Task 3: Discovery & Ingestion Engine

## Objective
Implement feed and source discovery, including Apple Podcasts (iTunes Search API) lookup, Podcasting 2.0 RSS parsing (extracting `<podcast:transcript>` tags and audio enclosures), YouTube URL and channel detection, and local audio file validation.

## Context & Requirements
- **Apple Podcasts Lookup (`src/podcast_ctl/discovery/itunes.py`):**
  - Search iTunes API endpoint (`https://itunes.apple.com/search?term=...&media=podcast`)
  - Return clean list of candidates (title, author, feed_url, episode_count, artwork_url).
- **RSS & Podcasting 2.0 Parser (`src/podcast_ctl/discovery/rss.py`):**
  - Fetch and parse RSS/Atom feeds using `httpx` and `feedparser` / `defusedxml`.
  - Extract episode list, audio enclosure URL, duration, publish date, and `<podcast:transcript>` tags (extracting `url`, `type`, `language`, `rel`).
- **YouTube Metadata Resolver (`src/podcast_ctl/discovery/youtube.py`):**
  - Identify YouTube video, playlist, or channel URLs.
  - Search YouTube for candidate videos given podcast episode title & show title using `yt-dlp` / `urllib`.
  - Extract available subtitles / auto-caption track metadata without downloading media.
- **Local Audio Inspector (`src/podcast_ctl/discovery/local_file.py`):**
  - Validate local audio paths (`.mp3`, `.m4a`, `.wav`, `.aac`, `.flac`, `.ogg`).
  - Extract duration and stream info via `ffmpeg` / `ffprobe` wrapper.

## Target Files
- `src/podcast_ctl/discovery/__init__.py`
- `src/podcast_ctl/discovery/itunes.py`
- `src/podcast_ctl/discovery/rss.py`
- `src/podcast_ctl/discovery/youtube.py`
- `src/podcast_ctl/discovery/local_file.py`
- `tests/test_discovery.py`

## Verification & Acceptance Criteria
- Running `uv run pytest tests/test_discovery.py` passes 100% with mocked HTTP responses (using `respx` / `pytest-mock`).
- Correctly parses Podcasting 2.0 transcripts from sample XML feed fixtures.
