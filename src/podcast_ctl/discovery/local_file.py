"""Local media file validation and metadata extraction."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import shutil
import subprocess
from typing import Any, Optional, Union
import wave

from podcast_ctl.models.transcript import EpisodeMetadata

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = frozenset({
    ".mp3",
    ".m4a",
    ".wav",
    ".aac",
    ".flac",
    ".ogg",
    ".mp4",
    ".m4v",
    ".wma",
    ".opus",
    ".webm",
    ".aiff",
    ".alac",
})


def is_supported_audio_file(path: Union[str, Path]) -> bool:
    """Check whether a given path has a supported audio or media file extension.

    Args:
        path: Path or filename string.

    Returns:
        True if the file extension is supported, False otherwise.
    """
    if not path:
        return False
    ext = Path(path).suffix.lower()
    return ext in SUPPORTED_AUDIO_EXTENSIONS


def probe_media_file(path: Union[str, Path]) -> dict[str, Any]:
    """Inspect local media file metadata and stream properties using ffprobe.

    Falls back to basic standard library inspection (e.g., wave for .wav files)
    if ffprobe is not installed on the system.

    Args:
        path: Path to the media file.

    Returns:
        Dictionary containing extracted metadata (duration, format, tags, size).
    """
    resolved = Path(path).expanduser().resolve()
    result: dict[str, Any] = {
        "path": str(resolved),
        "filename": resolved.name,
        "extension": resolved.suffix.lower(),
        "size_bytes": resolved.stat().st_size if resolved.exists() else 0,
        "duration_seconds": None,
        "tags": {},
    }

    if not resolved.exists():
        return result

    # Try ffprobe if available
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        try:
            cmd = [
                ffprobe_bin,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(resolved),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            probe_data = json.loads(proc.stdout)

            fmt = probe_data.get("format", {})
            if "duration" in fmt:
                try:
                    result["duration_seconds"] = float(fmt["duration"])
                except (ValueError, TypeError):
                    pass

            tags = fmt.get("tags", {})
            # Normalize tag keys to lowercase
            result["tags"] = {k.lower(): str(v) for k, v in tags.items()}

            # Check audio streams for duration if format didn't have it
            if result["duration_seconds"] is None:
                for stream in probe_data.get("streams", []):
                    if stream.get("codec_type") == "audio" and "duration" in stream:
                        try:
                            result["duration_seconds"] = float(stream["duration"])
                            break
                        except (ValueError, TypeError):
                            pass

            return result
        except Exception as exc:
            logger.debug("ffprobe execution failed for %r: %s", resolved, exc)

    # Standard library fallback for .wav files
    if resolved.suffix.lower() == ".wav":
        try:
            with wave.open(str(resolved), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    result["duration_seconds"] = float(frames) / float(rate)
        except Exception as exc:
            logger.debug("Wave file inspection fallback failed for %r: %s", resolved, exc)

    return result


def inspect_local_file(path: Union[str, Path]) -> EpisodeMetadata:
    """Validate a local media file and return its normalized EpisodeMetadata.

    Args:
        path: Path to the local audio/video file.

    Returns:
        EpisodeMetadata object describing the local file.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the path is a directory or has an unsupported extension.
    """
    resolved = Path(path).expanduser().resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Local media file not found: {resolved}")

    if not resolved.is_file():
        raise ValueError(f"Path is not a regular file: {resolved}")

    if not is_supported_audio_file(resolved):
        raise ValueError(
            f"Unsupported media file format '{resolved.suffix}'. Supported extensions: {', '.join(sorted(SUPPORTED_AUDIO_EXTENSIONS))}"
        )

    info = probe_media_file(resolved)
    tags = info.get("tags", {})

    # Extract title, artist/show
    episode_title = tags.get("title") or resolved.stem
    show_title = (
        tags.get("artist")
        or tags.get("album_artist")
        or tags.get("album")
        or (resolved.parent.name if resolved.parent.name else "Local Media")
    )

    # Generate stable unique episode_id based on file path hash
    path_hash = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    episode_id = f"local_{path_hash}"

    # Determine publication / creation date
    pub_date: Optional[str] = tags.get("date") or tags.get("creation_time")
    if not pub_date:
        try:
            mtime = resolved.stat().st_mtime
            pub_date = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
        except Exception:
            pub_date = None

    duration_sec = info.get("duration_seconds")

    return EpisodeMetadata(
        show_title=show_title,
        episode_title=episode_title,
        episode_id=episode_id,
        show_id=show_title,
        audio_url=str(resolved),
        duration_seconds=duration_sec,
        published_date=pub_date,
        rss_transcripts=[],
        source_type="local",
    )
