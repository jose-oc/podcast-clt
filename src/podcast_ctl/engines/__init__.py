"""Transcription engines package for podcast-ctl."""

from podcast_ctl.engines.base import (
    BaseTranscriptionEngine,
    EngineUnavailableError,
    TranscriptionEngineError,
    TranscriptNotFoundError,
)
from podcast_ctl.engines.cloud_engine import CloudTranscriptionEngine
from podcast_ctl.engines.dispatcher import TranscriptionDispatcher
from podcast_ctl.engines.rss_engine import (
    RSSTranscriptionEngine,
    parse_json_transcript,
    parse_plain_text,
    parse_srt_content,
    parse_timestamp_seconds,
    parse_vtt_content,
)
from podcast_ctl.engines.whisper_engine import (
    WhisperTranscriptionEngine,
    detect_optimal_device_and_compute_type,
)
from podcast_ctl.engines.youtube_engine import (
    YouTubeTranscriptionEngine,
    extract_youtube_video_id,
)

__all__ = [
    "BaseTranscriptionEngine",
    "CloudTranscriptionEngine",
    "EngineUnavailableError",
    "RSSTranscriptionEngine",
    "TranscriptNotFoundError",
    "TranscriptionDispatcher",
    "TranscriptionEngineError",
    "WhisperTranscriptionEngine",
    "YouTubeTranscriptionEngine",
    "detect_optimal_device_and_compute_type",
    "extract_youtube_video_id",
    "parse_json_transcript",
    "parse_plain_text",
    "parse_srt_content",
    "parse_timestamp_seconds",
    "parse_vtt_content",
]
