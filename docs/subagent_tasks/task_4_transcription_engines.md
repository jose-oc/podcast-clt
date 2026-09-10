# Task 4: Transcription Engines & Dispatcher

## Objective
Implement the 4-tier transcription hierarchy and dispatcher that tries lowest cost to highest compute, normalizing all outputs into standard `TranscriptResult` and `TranscriptSegment` models.

## Context & Requirements
- **Base Engine Interface (`src/podcast_ctl/engines/base.py`):**
  - Abstract class with `transcribe(episode: EpisodeMetadata, **kwargs) -> TranscriptResult`
- **Tier 1: RSS Transcript Engine (`src/podcast_ctl/engines/rss_engine.py`):**
  - Downloads `.vtt`, `.srt`, or `.json` transcript referenced in `<podcast:transcript>`.
  - Parses VTT/SRT timestamps into standard segments.
- **Tier 2: YouTube Subtitle Engine (`src/podcast_ctl/engines/youtube_engine.py`):**
  - Uses `youtube-transcript-api` or `yt-dlp` to fetch native/auto subtitles as timed segments.
- **Tier 3: Local Whisper Engine (`src/podcast_ctl/engines/whisper_engine.py`):**
  - Downloads audio temporarily via streaming/`httpx` $\rightarrow$ normalizes to 16kHz mono `.wav` via `ffmpeg`.
  - Runs `faster-whisper` (`WhisperModel`) with device auto-detection (`cpu`, `cuda`, `mps`/Apple Silicon CPU optimization).
  - Purges temporary audio file immediately after transcription.
- **Tier 4: Cloud Engine (`src/podcast_ctl/engines/cloud_engine.py`):**
  - Client for Groq Whisper API / OpenAI Whisper API for fast cloud inference when enabled.
- **Dispatcher (`src/podcast_ctl/engines/dispatcher.py`):**
  - Evaluates available strategies in order: RSS $\rightarrow$ YouTube $\rightarrow$ Local Whisper $\rightarrow$ Cloud.
  - Supports `--engine` override (`rss`, `youtube`, `whisper`, `groq`, `openai`, `auto`).

## Target Files
- `src/podcast_ctl/engines/__init__.py`
- `src/podcast_ctl/engines/base.py`
- `src/podcast_ctl/engines/rss_engine.py`
- `src/podcast_ctl/engines/youtube_engine.py`
- `src/podcast_ctl/engines/whisper_engine.py`
- `src/podcast_ctl/engines/cloud_engine.py`
- `src/podcast_ctl/engines/dispatcher.py`
- `tests/test_engines.py`

## Verification & Acceptance Criteria
- Running `uv run pytest tests/test_engines.py` passes 100%.
- Tier 1 and Tier 2 parsers correctly convert sample VTT, SRT, and JSON into `TranscriptResult`.
- Dispatcher respects engine preferences and handles fallbacks gracefully.
