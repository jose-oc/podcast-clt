# Task 2: Domain Models & SQLite Knowledge Store

## Objective
Define the Pydantic v2 data models for transcript segments, episode metadata, and transcript results, along with the SQLite storage layer (using WAL mode) for caching transcripts, storing confirmed show/episode mappings, and saving user preferences.

## Context & Requirements
- **Pydantic v2 Models (`src/podcast_ctl/models/`):**
  - `TranscriptSegment`: `start: float`, `end: float`, `text: str`, `speaker: Optional[str] = None`, `confidence: Optional[float] = None`
  - `EpisodeMetadata`: `show_title: str`, `episode_title: str`, `episode_id: str`, `audio_url: Optional[str] = None`, `duration_seconds: Optional[float] = None`, `published_date: Optional[str] = None`, `rss_transcripts: list[dict] = []`, `source_type: str` ("rss", "youtube", "local", "direct")
  - `TranscriptResult`: `metadata: EpisodeMetadata`, `segments: list[TranscriptSegment]`, `tier_used: str` ("rss", "youtube", "whisper", "cloud"), `raw_text: str`, `created_at: str`
  - `ShowMapping`: `feed_url: str`, `show_title: str`, `youtube_channel_url: Optional[str] = None`, `custom_settings: dict = {}`
  - `EpisodeMapping`: `show_id: str`, `episode_id: str`, `youtube_video_url: str`, `confirmed_by_user: bool = True`
- **SQLite Storage & Repository (`src/podcast_ctl/storage/`):**
  - Schema initialization with `PRAGMA journal_mode=WAL;`
  - Tables: `shows`, `episodes`, `transcripts`, `knowledge_mappings`, `preferences`
  - Repository methods:
    - `save_show()`, `get_show()`
    - `save_episode_mapping()`, `get_episode_mapping(show_id, episode_id)`
    - `save_show_mapping()`, `get_show_mapping(feed_url)`
    - `save_transcript()`, `get_transcript(show_id, episode_id)`
    - `list_cached_transcripts()`, `clear_cache()`

## Target Files
- `src/podcast_ctl/models/__init__.py`
- `src/podcast_ctl/models/transcript.py`
- `src/podcast_ctl/models/knowledge.py`
- `src/podcast_ctl/storage/__init__.py`
- `src/podcast_ctl/storage/db.py`
- `src/podcast_ctl/storage/repository.py`
- `tests/test_storage.py`

## Verification & Acceptance Criteria
- Running `uv run pytest tests/test_storage.py` must pass with 100% success on in-memory SQLite and temporary disk databases.
- Models validate serialization to/from JSON accurately.
