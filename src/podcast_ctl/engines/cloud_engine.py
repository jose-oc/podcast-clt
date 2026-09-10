"""Tier 4: Cloud API Transcription Engine.

Provides ultra-fast cloud inference via OpenAI-compatible Whisper endpoints
(Groq Whisper API, OpenAI Whisper API, or custom endpoints).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Literal, Optional

import httpx

from podcast_ctl.engines.base import (
    BaseTranscriptionEngine,
    EngineUnavailableError,
    TranscriptionEngineError,
)
from podcast_ctl.models.transcript import (
    EpisodeMetadata,
    TranscriptResult,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
OPENAI_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"


class CloudTranscriptionEngine(BaseTranscriptionEngine):
    """Tier 4: Cloud API transcription engine (Groq, OpenAI, or custom endpoint)."""

    name: str = "cloud"
    tier: str = "cloud"

    def __init__(
        self,
        provider: Literal["groq", "openai", "custom"] | str = "groq",
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 300.0,
    ) -> None:
        self.provider = provider.lower()
        self._explicit_api_key = api_key
        self._explicit_model = model
        self._explicit_base_url = base_url
        self.timeout = timeout

    @property
    def api_key(self) -> Optional[str]:
        """Resolve API key from explicit value or environment variables."""
        if self._explicit_api_key:
            return self._explicit_api_key

        if self.provider == "groq":
            return os.environ.get("GROQ_API_KEY")
        elif self.provider == "openai":
            return os.environ.get("OPENAI_API_KEY")
        return os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY")

    @property
    def endpoint_url(self) -> str:
        """Resolve endpoint URL based on provider."""
        if self._explicit_base_url:
            url = self._explicit_base_url.rstrip("/")
            if not url.endswith("/audio/transcriptions"):
                url = f"{url}/audio/transcriptions"
            return url

        if self.provider == "openai":
            return OPENAI_ENDPOINT
        return GROQ_ENDPOINT

    @property
    def default_model(self) -> str:
        """Resolve default model based on provider."""
        if self._explicit_model:
            return self._explicit_model

        if self.provider == "openai":
            return "whisper-1"
        return "whisper-large-v3"

    def is_available(self) -> bool:
        """Check if an API key is configured for the cloud provider."""
        return bool(self.api_key)

    async def _download_audio(self, url: str, target_path: Path) -> None:
        """Download remote audio to a local path."""
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(target_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

    async def transcribe(
        self,
        episode: EpisodeMetadata,
        client: Optional[httpx.AsyncClient] = None,
        **kwargs: Any,
    ) -> TranscriptResult:
        """Send audio to cloud transcription API and parse verbose_json segments."""
        api_key = kwargs.get("api_key") or self.api_key
        if not api_key:
            raise EngineUnavailableError(
                f"Cloud transcription requires an API key. Set GROQ_API_KEY or OPENAI_API_KEY env var."
            )

        model = kwargs.get("model") or self.default_model
        endpoint = kwargs.get("endpoint_url") or self.endpoint_url
        language = kwargs.get("language")
        temperature = kwargs.get("temperature", 0.0)
        prompt = kwargs.get("prompt")
        keep_audio = kwargs.get("keep_audio", False)

        # Audio file resolution
        local_path_arg = kwargs.get("audio_path") or kwargs.get("local_path")
        temp_dir: Optional[str] = None
        audio_file_path: Optional[Path] = None

        try:
            if local_path_arg and Path(local_path_arg).exists():
                audio_file_path = Path(local_path_arg)
            elif episode.audio_url and (
                episode.audio_url.startswith("http://") or episode.audio_url.startswith("https://")
            ):
                temp_dir = tempfile.mkdtemp(prefix="podcast_cloud_")
                ext = ".mp3"
                url_clean = episode.audio_url.split("?")[0].lower()
                for known_ext in (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"):
                    if url_clean.endswith(known_ext):
                        ext = known_ext
                        break

                audio_file_path = Path(temp_dir) / f"audio{ext}"
                logger.info(f"Downloading audio from {episode.audio_url} for cloud transcription...")
                await self._download_audio(episode.audio_url, audio_file_path)
            elif episode.audio_url and Path(episode.audio_url).exists():
                audio_file_path = Path(episode.audio_url)
            else:
                raise TranscriptionEngineError(
                    f"No valid audio source found for episode '{episode.episode_title}'."
                )

            filename = audio_file_path.name
            mime_type = "audio/mpeg"
            if filename.endswith(".wav"):
                mime_type = "audio/wav"
            elif filename.endswith(".m4a"):
                mime_type = "audio/m4a"
            elif filename.endswith(".ogg"):
                mime_type = "audio/ogg"

            headers = {
                "Authorization": f"Bearer {api_key}",
            }

            data: dict[str, Any] = {
                "model": model,
                "response_format": "verbose_json",
                "temperature": str(temperature),
            }
            if language:
                data["language"] = language
            if prompt:
                data["prompt"] = prompt

            async def _send_request(http_client: httpx.AsyncClient) -> TranscriptResult:
                assert audio_file_path is not None
                with open(audio_file_path, "rb") as f:
                    file_bytes = f.read()

                files = {
                    "file": (filename, file_bytes, mime_type),
                }

                logger.info(f"Sending audio to cloud endpoint '{endpoint}' with model '{model}'...")
                resp = await http_client.post(
                    endpoint,
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=self.timeout,
                )

                if resp.status_code >= 400:
                    raise TranscriptionEngineError(
                        f"Cloud API request failed ({resp.status_code}): {resp.text}"
                    )

                result_json = resp.json()
                raw_text = str(result_json.get("text", "")).strip()

                segments: list[TranscriptSegment] = []
                for s in result_json.get("segments", []):
                    start = round(float(s.get("start", 0.0)), 3)
                    end = round(float(s.get("end", 0.0)), 3)
                    text = str(s.get("text", "")).strip()
                    confidence = None
                    if "avg_logprob" in s and s["avg_logprob"] is not None:
                        try:
                            import math
                            confidence = round(max(0.0, min(1.0, math.exp(float(s["avg_logprob"])))), 3)
                        except Exception:
                            pass

                    if text:
                        segments.append(
                            TranscriptSegment(
                                start=start,
                                end=max(start, end),
                                text=text,
                                confidence=confidence,
                            )
                        )

                # If no segments array was returned, build single segment from raw_text
                if not segments and raw_text:
                    segments.append(
                        TranscriptSegment(
                            start=0.0,
                            end=round(float(result_json.get("duration", episode.duration_seconds or 0.0)), 3),
                            text=raw_text,
                        )
                    )

                return TranscriptResult(
                    metadata=episode,
                    segments=segments,
                    tier_used="cloud",
                    raw_text=raw_text,
                )

            if client is not None:
                return await _send_request(client)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as http_client:
                    return await _send_request(http_client)

        finally:
            if not keep_audio and temp_dir is not None and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as exc:
                    logger.warning(f"Failed to clean up temporary audio directory {temp_dir}: {exc}")
