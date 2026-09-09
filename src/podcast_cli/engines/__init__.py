"""Transcription engines package for podcast-cli."""

from podcast_cli.engines.base import (
    BaseTranscriptionEngine,
    EngineUnavailableError,
    TranscriptNotFoundError,
    TranscriptionEngineError,
)
from podcast_cli.engines.cloud_engine import CloudTranscriptionEngine
from podcast_cli.engines.dispatcher import TranscriptionDispatcher
from podcast_cli.engines.rss_engine import (
    RSSTranscriptionEngine,
    parse_json_transcript,
    parse_plain_text,
    parse_srt_content,
    parse_timestamp_seconds,
    parse_vtt_content,
)
from podcast_cli.engines.whisper_engine import (
    WhisperTranscriptionEngine,
    detect_optimal_device_and_compute_type,
)
from podcast_cli.engines.youtube_engine import (
    YouTubeTranscriptionEngine,
    extract_youtube_video_id,
)

__all__ = [
    "BaseTranscriptionEngine",
    "TranscriptionEngineError",
    "EngineUnavailableError",
    "TranscriptNotFoundError",
    "RSSTranscriptionEngine",
    "YouTubeTranscriptionEngine",
    "WhisperTranscriptionEngine",
    "CloudTranscriptionEngine",
    "TranscriptionDispatcher",
    "parse_timestamp_seconds",
    "parse_vtt_content",
    "parse_srt_content",
    "parse_json_transcript",
    "parse_plain_text",
    "extract_youtube_video_id",
    "detect_optimal_device_and_compute_type",
]
