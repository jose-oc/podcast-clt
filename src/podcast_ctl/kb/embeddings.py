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
# with `kb embed --model` or PODCAST_CTL_EMBED_MODEL.
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

    def __init__(self, model: str = DEFAULT_EMBEDDING_MODEL) -> None:
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
        self._st = SentenceTransformer(model)
        self._dims = int(self._st.get_sentence_embedding_dimension() or 0)

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
    ``PODCAST_CTL_EMBED_MODEL``), so the knowledge base stays decoupled from
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


def get_embedding_provider(name: str = PROVIDER_LOCAL, model: str | None = None) -> EmbeddingProvider:
    """Build an embedding provider by name.

    ``local`` (default) runs sentence-transformers on the user's machine;
    ``openai-compatible`` is the optional cloud adapter configured through
    environment variables. Raises ``EmbeddingBackendUnavailable`` with a
    setup hint when the backend cannot be used.
    """
    if name == PROVIDER_LOCAL:
        return SentenceTransformerProvider(model or os.environ.get(ENV_EMBED_MODEL) or DEFAULT_EMBEDDING_MODEL)
    if name == PROVIDER_OPENAI_COMPATIBLE:
        base_url = os.environ.get(ENV_EMBED_BASE_URL, "").strip()
        api_key = os.environ.get(ENV_EMBED_API_KEY, "").strip()
        model_name = (model or os.environ.get(ENV_EMBED_MODEL) or "").strip()
        missing = [
            var
            for var, value in (
                (ENV_EMBED_BASE_URL, base_url),
                (ENV_EMBED_API_KEY, api_key),
                (ENV_EMBED_MODEL, model_name),
            )
            if not value
        ]
        if missing:
            raise EmbeddingBackendUnavailable(
                "The openai-compatible provider needs these environment variables: " + ", ".join(missing)
            )
        return OpenAICompatibleProvider(base_url=base_url, api_key=api_key, model=model_name)
    raise EmbeddingBackendUnavailable(
        f"Unknown embedding provider '{name}'. Available: {PROVIDER_LOCAL}, {PROVIDER_OPENAI_COMPATIBLE}."
    )
