"""Tier 3: Local Whisper Transcription Engine.

Uses `faster-whisper` for on-device inference with automatic hardware detection
(CUDA, Apple Silicon ARM, CPU) and temporary audio normalization via ffmpeg.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from pathlib import Path
import platform
import shutil
import tempfile
from typing import Any, Optional

import httpx

from podcast_cli.engines.base import (
    BaseTranscriptionEngine,
    EngineUnavailableError,
    TranscriptionEngineError,
)
from podcast_cli.models.transcript import (
    EpisodeMetadata,
    TranscriptResult,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)


def detect_optimal_device_and_compute_type() -> tuple[str, str]:
    """Auto-detect optimal device ('cuda' vs 'cpu') and compute_type for faster-whisper."""
    # Check for CUDA
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass

    # Check for Apple Silicon / macOS ARM64
    is_apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"
    if is_apple_silicon:
        # On Apple Silicon ARM64, CTranslate2 CPU execution with int8 or default runs with Accelerate
        return "cpu", "int8"

    # Default CPU fallback
    return "cpu", "int8"


class WhisperTranscriptionEngine(BaseTranscriptionEngine):
    """Tier 3: Local Whisper engine using faster-whisper (CTranslate2)."""

    name: str = "whisper"
    tier: str = "whisper"

    def __init__(
        self,
        default_model_size: str = "base",
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        download_timeout: float = 300.0,
    ) -> None:
        self.default_model_size = default_model_size
        self._custom_device = device
        self._custom_compute_type = compute_type
        self.download_timeout = download_timeout
        self._model_cache: dict[str, Any] = {}

    def is_available(self) -> bool:
        """Check if faster-whisper is installed."""
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def get_model(self, model_size: str, device: str, compute_type: str) -> Any:
        """Load or retrieve cached WhisperModel instance."""
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise EngineUnavailableError("faster-whisper is not installed.") from exc

        cache_key = f"{model_size}::{device}::{compute_type}"
        if cache_key not in self._model_cache:
            logger.info(f"Loading faster-whisper model '{model_size}' (device={device}, compute_type={compute_type})...")
            self._model_cache[cache_key] = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
        return self._model_cache[cache_key]

    async def _download_audio(self, url: str, target_path: Path) -> None:
        """Stream download audio enclosure to a local file."""
        async with httpx.AsyncClient(timeout=self.download_timeout, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(target_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

    async def _convert_to_wav(self, input_path: Path, output_wav_path: Path) -> bool:
        """Convert audio file to 16kHz mono PCM 16-bit WAV using ffmpeg if installed."""
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            logger.debug("ffmpeg not found on PATH; using raw audio directly with PyAV.")
            return False

        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(input_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_wav_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"ffmpeg conversion failed (code {proc.returncode}): {stderr.decode('utf-8', errors='replace')}")
            return False
        return True

    def _run_transcription(
        self,
        audio_file_path: str,
        model_size: str,
        device: str,
        compute_type: str,
        language: Optional[str] = None,
        beam_size: int = 5,
        vad_filter: bool = True,
        **whisper_kwargs: Any,
    ) -> list[TranscriptSegment]:
        """Execute faster-whisper transcription in a worker thread."""
        model = self.get_model(model_size, device, compute_type)

        segments_iter, _info = model.transcribe(
            audio_file_path,
            beam_size=beam_size,
            language=language,
            vad_filter=vad_filter,
            **whisper_kwargs,
        )

        segments: list[TranscriptSegment] = []
        for seg in segments_iter:
            confidence = None
            if hasattr(seg, "avg_logprob") and seg.avg_logprob is not None:
                try:
                    confidence = round(max(0.0, min(1.0, math.exp(seg.avg_logprob))), 3)
                except OverflowError:
                    confidence = 1.0

            text = seg.text.strip()
            if text:
                segments.append(
                    TranscriptSegment(
                        start=round(seg.start, 3),
                        end=round(seg.end, 3),
                        text=text,
                        confidence=confidence,
                    )
                )

        return segments

    async def transcribe(
        self,
        episode: EpisodeMetadata,
        **kwargs: Any,
    ) -> TranscriptResult:
        """Download audio, convert to 16kHz WAV, and run local Whisper transcription."""
        if not self.is_available():
            raise EngineUnavailableError(
                "Local Whisper engine is not available. Ensure `faster-whisper` is installed."
            )

        # Device & compute type resolution
        detected_device, detected_compute = detect_optimal_device_and_compute_type()
        device = kwargs.get("device") or self._custom_device or detected_device
        compute_type = kwargs.get("compute_type") or self._custom_compute_type or detected_compute
        model_size = kwargs.get("model_size") or self.default_model_size
        language = kwargs.get("language")
        beam_size = kwargs.get("beam_size", 5)
        keep_audio = kwargs.get("keep_audio", False)

        # Audio source resolution
        local_path_arg = kwargs.get("audio_path") or kwargs.get("local_path")
        temp_dir: Optional[str] = None
        temp_raw_file: Optional[Path] = None
        temp_wav_file: Optional[Path] = None
        transcribe_target_file: Optional[str] = None

        try:
            if local_path_arg and Path(local_path_arg).exists():
                audio_input = Path(local_path_arg)
            elif episode.audio_url and (
                episode.audio_url.startswith("http://") or episode.audio_url.startswith("https://")
            ):
                temp_dir = tempfile.mkdtemp(prefix="podcast_whisper_")
                # Determine file extension hint
                ext = ".mp3"
                url_path = episode.audio_url.split("?")[0].lower()
                for known_ext in (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"):
                    if url_path.endswith(known_ext):
                        ext = known_ext
                        break

                temp_raw_file = Path(temp_dir) / f"input_audio{ext}"
                logger.info(f"Downloading episode audio from {episode.audio_url}...")
                await self._download_audio(episode.audio_url, temp_raw_file)
                audio_input = temp_raw_file
            elif episode.audio_url and Path(episode.audio_url).exists():
                audio_input = Path(episode.audio_url)
            else:
                raise TranscriptionEngineError(
                    f"No valid audio URL or local audio path found for episode '{episode.episode_title}'."
                )

            # Convert to 16kHz WAV
            if temp_dir is None:
                temp_dir = tempfile.mkdtemp(prefix="podcast_whisper_")
            temp_wav_file = Path(temp_dir) / "converted_16k.wav"

            converted = await self._convert_to_wav(audio_input, temp_wav_file)
            if converted and temp_wav_file.exists():
                transcribe_target_file = str(temp_wav_file)
            else:
                transcribe_target_file = str(audio_input)

            logger.info(f"Transcribing '{episode.episode_title}' with model '{model_size}'...")
            segments = await asyncio.to_thread(
                self._run_transcription,
                transcribe_target_file,
                model_size,
                device,
                compute_type,
                language=language,
                beam_size=beam_size,
            )

            return TranscriptResult(
                metadata=episode,
                segments=segments,
                tier_used="whisper",
            )

        finally:
            if not keep_audio and temp_dir is not None and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as exc:
                    logger.warning(f"Failed to clean up temporary audio directory {temp_dir}: {exc}")
