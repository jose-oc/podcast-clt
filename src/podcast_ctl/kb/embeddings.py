"""Embedding providers for the knowledge base vector phase (2c).

Provider independence is a hard constraint (docs/KNOWLEDGE_BASE_DESIGN.md):

- Embedding backends sit behind a small interface (``embed(texts) -> vectors``).
- Local models are the default; hosted APIs are optional adapters configured
  through environment variables, never required.
- Every stored vector records the provider identity (backend, model, version,
  dimensions) that produced it, so switching providers or models triggers a
  clean, detectable reindex instead of silently mixing incompatible vectors.

Vectors are stored unit-normalized, so cosine similarity is a dot product.
"""

from __future__ import annotations

import math
import os
from typing import Protocol, runtime_checkable

import httpx

# Default local embedding model: strong multilingual retrieval (including
# Spanish), no per-query cost, transcripts never leave the machine. Override
# with `kb embed --model` or PODCAST_CTL_LOCAL_MODEL / PODCAST_CTL_EMBED_MODEL.
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"

# Available provider names for `--provider`.
PROVIDER_LOCAL = "local"
PROVIDER_OPENAI_COMPATIBLE = "openai-compatible"

# Environment variables configuring the optional cloud adapter. The adapter
# talks to any OpenAI-compatible embeddings endpoint, so no vendor name is
# baked into the knowledge base.
ENV_EMBED_BASE_URL = "PODCAST_CTL_EMBED_BASE_URL"
ENV_EMBED_API_KEY = "PODCAST_CTL_EMBED_API_KEY"
ENV_EMBED_MODEL = "PODCAST_CTL_EMBED_MODEL"
# Provider-specific model overrides. Each provider resolves its model as:
# --model flag > its own variable below > PODCAST_CTL_EMBED_MODEL (generic)
# > the built-in default. The openai-compatible variable is endpoint-agnostic:
# it names the model at whatever OpenAI-compatible endpoint is configured
# (Ollama, LM Studio, a hosted API - nothing here is tied to one vendor).
ENV_LOCAL_MODEL = "PODCAST_CTL_LOCAL_MODEL"
ENV_OPENAI_MODEL = "PODCAST_CTL_OPENAI_MODEL"
# Optional device override for the local backend (cpu / mps / cuda). When
# unset, sentence-transformers auto-selects the best available device.
ENV_EMBED_DEVICE = "PODCAST_CTL_EMBED_DEVICE"


class EmbeddingBackendUnavailable(RuntimeError):
    """Raised when the selected embedding backend cannot be used (missing

    optional dependency or missing configuration). The message carries the
    install/setup hint to show the user.
    """


class EmbeddingIdentityMismatch(RuntimeError):
    """Raised when the index holds embeddings from a different provider/model.

    Mixing vectors from incompatible models would silently corrupt search
    results, so the caller must reindex (or use the original provider).
    """


def normalize_vector(vector: list[float]) -> list[float]:
    """Return the unit-norm copy of a vector (zero vectors pass through)."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return list(vector)
    return [x / norm for x in vector]


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Minimal embedding backend interface.

    Implementations return one float vector per input text. ``version``
    records whatever provenance the backend can offer (package version,
    adapter revision) so stored vectors stay traceable.
    """

    @property
    def provider(self) -> str:
        """Backend family, e.g. ``local`` or ``openai-compatible``."""
        ...

    @property
    def model(self) -> str:
        """Model name as selected by the user."""
        ...

    @property
    def version(self) -> str:
        """Backend/model version recorded for provenance."""
        ...

    @property
    def dims(self) -> int:
        """Vector dimensionality (0 until the first embed call reveals it)."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, one vector per input."""
        ...

    def identity(self) -> str:
        """Stable identity string recorded next to every stored vector."""
        return f"{self.provider}:{self.model}@{self.version}"


class SentenceTransformerProvider:
    """Local embeddings via sentence-transformers (the default backend).

    The dependency is optional (``pip install 'podcast-ctl[embeddings]'``)
    and imported lazily so the rest of the CLI never pays for torch.
    """

    def __init__(self, model: str = DEFAULT_EMBEDDING_MODEL, device: str | None = None) -> None:
        try:
            import sentence_transformers
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingBackendUnavailable(
                "Local embeddings require the optional dependency sentence-transformers.\n"
                "Install it with: pip install 'podcast-ctl[embeddings]'"
            ) from exc
        self._model_name = model
        self._version = sentence_transformers.__version__
        requested = device or os.environ.get(ENV_EMBED_DEVICE) or None
        # None lets sentence-transformers auto-select (cuda/mps when
        # available, cpu otherwise); an explicit value is passed through.
        self._st = SentenceTransformer(model, device=requested)
        self._device = str(self._st.device)
        # sentence-transformers 6.x renamed get_sentence_embedding_dimension
        # to get_embedding_dimension; use whichever the installed version has.
        get_dims = getattr(self._st, "get_embedding_dimension", None)
        if get_dims is None:  # sentence-transformers < 6
            get_dims = self._st.get_sentence_embedding_dimension
        self._dims = int(get_dims() or 0)

    @property
    def device(self) -> str:
        """Torch device the model runs on, e.g. ``cpu``, ``mps`` or ``cuda``."""
        return self._device

    @property
    def provider(self) -> str:
        return PROVIDER_LOCAL

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def version(self) -> str:
        return f"sentence-transformers {self._version}"

    @property
    def dims(self) -> int:
        return self._dims

    def identity(self) -> str:
        return f"{self.provider}:{self.model}@{self.version}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._st.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in row] for row in vectors]


class OpenAICompatibleProvider:
    """Optional cloud adapter for any OpenAI-compatible embeddings endpoint.

    Configured entirely through environment variables
    (``PODCAST_CTL_EMBED_BASE_URL`` / ``PODCAST_CTL_EMBED_API_KEY`` /
    ``PODCAST_CTL_OPENAI_MODEL``), so the knowledge base stays decoupled from
    any specific vendor: point it at OpenAI, a Gemini/OpenAI-compatible
    gateway, a self-hosted server, or any other compatible API.
    """

    ADAPTER_VERSION = "adapter-v1"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/embeddings"
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._dims = 0

    @property
    def device(self) -> str:
        """Where the vectors are computed: on the remote endpoint, not locally."""
        return "remote (API endpoint)"

    @property
    def provider(self) -> str:
        return PROVIDER_OPENAI_COMPATIBLE

    @property
    def model(self) -> str:
        return self._model

    @property
    def version(self) -> str:
        return self.ADAPTER_VERSION

    @property
    def dims(self) -> int:
        return self._dims

    def identity(self) -> str:
        return f"{self.provider}:{self.model}@{self.version}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = httpx.post(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": list(texts)},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        if len(data) != len(texts):
            raise EmbeddingBackendUnavailable(
                f"Embeddings endpoint returned {len(data)} vectors for {len(texts)} inputs."
            )
        vectors = [normalize_vector([float(x) for x in item["embedding"]]) for item in data]
        if vectors:
            self._dims = len(vectors[0])
        return vectors


def parse_embedding_identity(identity: str) -> tuple[str, str]:
    """Split a stored identity (``provider:model@version``) into ``(provider, model)``.

    Returns empty strings for the parts it cannot parse; callers decide how
    to handle an identity they do not recognize.
    """
    provider, _, rest = identity.partition(":")
    model, _, _version = rest.rpartition("@")
    return provider, model


def get_embedding_provider(
    name: str = PROVIDER_LOCAL,
    model: str | None = None,
    device: str | None = None,
) -> EmbeddingProvider:
    """Build an embedding provider by name.

    ``local`` (default) runs sentence-transformers on the user's machine;
    ``openai-compatible`` is the optional cloud adapter configured through
    environment variables. ``device`` (cpu / mps / cuda) applies to the local
    backend only. Raises ``EmbeddingBackendUnavailable`` with a setup hint
    when the backend cannot be used.
    """
    if name == PROVIDER_LOCAL:
        local_model = (
            model or os.environ.get(ENV_LOCAL_MODEL) or os.environ.get(ENV_EMBED_MODEL)
        )
        return SentenceTransformerProvider(local_model or DEFAULT_EMBEDDING_MODEL, device=device)
    if name == PROVIDER_OPENAI_COMPATIBLE:
        base_url = os.environ.get(ENV_EMBED_BASE_URL, "").strip()
        api_key = os.environ.get(ENV_EMBED_API_KEY, "").strip()
        model_name = (
            model or os.environ.get(ENV_OPENAI_MODEL) or os.environ.get(ENV_EMBED_MODEL) or ""
        ).strip()
        missing = [
            var
            for var, value in (
                (ENV_EMBED_BASE_URL, base_url),
                (ENV_EMBED_API_KEY, api_key),
                (f"{ENV_OPENAI_MODEL} (or {ENV_EMBED_MODEL})", model_name),
            )
            if not value
        ]
        if missing:
            raise EmbeddingBackendUnavailable(
                "The openai-compatible provider needs these environment variables: " + ", ".join(missing) + ".\n"
                "Set them and retry, e.g. export PODCAST_CTL_EMBED_BASE_URL=http://localhost:11434/v1 "
                "(see docs/KNOWLEDGE_BASE.md)."
            )
        return OpenAICompatibleProvider(base_url=base_url, api_key=api_key, model=model_name)
    raise EmbeddingBackendUnavailable(
        f"Unknown embedding provider '{name}'. Available: {PROVIDER_LOCAL}, {PROVIDER_OPENAI_COMPATIBLE}. "
        "Pass one of them to --provider, or omit it for the default local backend."
    )
