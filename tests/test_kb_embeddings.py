"""Tests for phase 2c: embedding providers, vector storage, RRF hybrid search, CLI."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from podcast_ctl.cli.main import app
from podcast_ctl.kb.builder import KbBuilder
from podcast_ctl.kb.embed import embed_kb
from podcast_ctl.kb.embeddings import (
    ENV_EMBED_API_KEY,
    ENV_EMBED_BASE_URL,
    ENV_EMBED_MODEL,
    EmbeddingBackendUnavailable,
    EmbeddingIdentityMismatch,
    OpenAICompatibleProvider,
    get_embedding_provider,
    normalize_vector,
)
from podcast_ctl.kb.search import (
    hybrid_search_kb,
    rrf_fuse,
    vector_search_kb,
)
from podcast_ctl.kb.store import pack_vector, unpack_vector
from podcast_ctl.models.transcript import EpisodeMetadata, TranscriptResult, TranscriptSegment
from podcast_ctl.storage.repository import StorageRepository

runner = CliRunner(env={"COLUMNS": "250"})


class StubProvider:
    """Deterministic dependency-free provider for tests.

    Vectors are normalized bags of token hashes, so texts sharing tokens get
    high cosine similarity — enough to exercise ranking without real models.
    """

    def __init__(self, model: str = "stub-model", dims: int = 16) -> None:
        self._model = model
        self.dims = dims

    @property
    def provider(self) -> str:
        return "stub"

    @property
    def model(self) -> str:
        return self._model

    @property
    def version(self) -> str:
        return "v1"

    def identity(self) -> str:
        return f"stub:{self._model}@v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "little") % self.dims] += 1.0
        return normalize_vector(vector)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run every test against an isolated catalog DB and KB directory."""
    db_file = tmp_path / "test_podcast_ctl.db"
    monkeypatch.setenv("PODCAST_CTL_DB_PATH", str(db_file))
    monkeypatch.setenv("PODCAST_CTL_KB_DIR", str(tmp_path / "kb"))
    return tmp_path


def make_episode(episode_id: str, title: str, sentences: list[str]) -> TranscriptResult:
    """Synthetic single-show episode with one segment per sentence."""
    return TranscriptResult(
        metadata=EpisodeMetadata(
            show_title="Demo Show",
            episode_title=title,
            episode_id=episode_id,
            audio_url=f"https://example.com/{episode_id}.mp3",
            duration_seconds=600.0,
            published_date="2026-09-01",
        ),
        segments=[
            TranscriptSegment(start=i * 10.0, end=i * 10.0 + 8.0, text=sentence, speaker="Host")
            for i, sentence in enumerate(sentences)
        ],
        tier_used="rss",
    )


def seed_kb() -> KbBuilder:
    """Build a KB with two topically distinct episodes."""
    repo = StorageRepository()
    repo.save_transcript(
        make_episode(
            "ep-vectors",
            "Ep 1 — Vector talk",
            [
                "Vector databases store embeddings for similarity search.",
                "Cosine similarity ranks the closest embedding vectors.",
                "Hybrid retrieval fuses lexical and vector ranking.",
            ],
        )
    )
    repo.save_transcript(
        make_episode(
            "ep-cooking",
            "Ep 2 — Cooking talk",
            [
                "Today we cook a lentil stew with carrots and onions.",
                "Simmer the stew for forty minutes and season to taste.",
            ],
        )
    )
    builder = KbBuilder()
    builder.build()
    return builder


# =============================================================================
# Vector helpers and providers
# =============================================================================


def test_pack_unpack_vector_roundtrip() -> None:
    vector = [0.25, -0.5, 1.0, 0.0]
    assert unpack_vector(pack_vector(vector)) == pytest.approx(vector)


def test_normalize_vector_unit_norm_and_zero() -> None:
    normalized = normalize_vector([3.0, 4.0])
    assert math.sqrt(sum(x * x for x in normalized)) == pytest.approx(1.0)
    assert normalize_vector([0.0, 0.0]) == [0.0, 0.0]


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(EmbeddingBackendUnavailable, match="Unknown embedding provider"):
        get_embedding_provider("nonexistent")


def test_factory_openai_compatible_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (ENV_EMBED_BASE_URL, ENV_EMBED_API_KEY, ENV_EMBED_MODEL):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(EmbeddingBackendUnavailable, match=ENV_EMBED_BASE_URL):
        get_embedding_provider("openai-compatible")


@respx.mock
def test_openai_compatible_provider_embeds_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_EMBED_BASE_URL, "https://api.example.com/v1")
    monkeypatch.setenv(ENV_EMBED_API_KEY, "test-key")
    monkeypatch.setenv(ENV_EMBED_MODEL, "text-embedding-x")

    route = respx.post("https://api.example.com/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 2.0]},
                    {"index": 0, "embedding": [3.0, 4.0]},
                ]
            },
        )
    )

    provider = get_embedding_provider("openai-compatible")
    assert isinstance(provider, OpenAICompatibleProvider)
    vectors = provider.embed(["first text", "second text"])

    assert route.called
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-key"
    # Results come back sorted by index, one unit vector per input.
    assert vectors[0] == pytest.approx([0.6, 0.8])
    assert vectors[1] == pytest.approx([0.0, 1.0])
    assert provider.dims == 2
    assert provider.identity() == "openai-compatible:text-embedding-x@adapter-v1"


# =============================================================================
# Embedding index build
# =============================================================================


def test_embed_kb_builds_and_is_idempotent() -> None:
    builder = seed_kb()
    store = builder.store
    provider = StubProvider()

    report = embed_kb(store, provider)
    assert report.embedded == store.stats()["chunks"]
    assert report.embedded > 0
    assert store.embedding_identity() == "stub:stub-model@v1"

    second = embed_kb(store, provider)
    assert second.embedded == 0
    assert second.already_indexed == report.embedded


def test_embed_kb_refuses_to_mix_providers_then_reindexes() -> None:
    builder = seed_kb()
    store = builder.store
    embed_kb(store, StubProvider(model="stub-model"))

    with pytest.raises(EmbeddingIdentityMismatch, match="--reindex"):
        embed_kb(store, StubProvider(model="other-model"))

    report = embed_kb(store, StubProvider(model="other-model"), reindex=True)
    assert report.reindexed
    assert report.removed > 0
    assert report.embedded == store.stats()["chunks"]
    assert store.embedding_identity() == "stub:other-model@v1"


def test_embed_kb_incremental_after_episode_rebuild() -> None:
    builder = seed_kb()
    store = builder.store
    provider = StubProvider()
    embed_kb(store, provider)
    total = store.stats()["chunks"]

    # Re-transcribe one episode: kb build replaces its chunks, and the FK
    # cascade drops only their embeddings.
    repo = StorageRepository()
    repo.save_transcript(make_episode("ep-cooking", "Ep 2 — Cooking talk", ["A brand new stew recipe with chickpeas."]))
    builder.build()

    assert store.stats()["embeddings"] < total
    report = embed_kb(store, provider)
    assert report.embedded == store.stats()["chunks"] - store.stats()["embeddings"] + report.embedded
    assert store.stats()["embeddings"] == store.stats()["chunks"]


def test_embed_kb_scoped_to_show() -> None:
    builder = seed_kb()
    store = builder.store
    repo = StorageRepository()
    repo.save_transcript(
        TranscriptResult(
            metadata=EpisodeMetadata(
                show_title="Other Show",
                episode_title="Other Ep",
                episode_id="other-1",
                duration_seconds=60.0,
            ),
            segments=[TranscriptSegment(start=0.0, end=5.0, text="Completely different show content.", speaker=None)],
            tier_used="rss",
        )
    )
    builder.build()

    report = embed_kb(store, StubProvider(), show_id="Other Show")
    assert report.embedded == 1
    assert store.stats()["embeddings"] == 1
    assert store.stats()["chunks"] > 1


# =============================================================================
# Vector and hybrid search
# =============================================================================


def test_vector_search_ranks_by_token_overlap() -> None:
    builder = seed_kb()
    store = builder.store
    provider = StubProvider()
    embed_kb(store, provider)

    hits = vector_search_kb(store, provider, "embedding similarity vectors", limit=5)
    assert hits
    assert hits[0]["episode_id"] == "ep-vectors"
    assert all("cosine" in hit for hit in hits)
    # Cosine scores descend.
    scores = [float(hit["cosine"]) for hit in hits]
    assert scores == sorted(scores, reverse=True)


def test_vector_search_scoped_to_show() -> None:
    builder = seed_kb()
    store = builder.store
    provider = StubProvider()
    embed_kb(store, provider)

    hits = vector_search_kb(store, provider, "stew", limit=5, show_id="Other Show")
    assert hits == []


def test_rrf_fuse_merges_and_prefers_dual_source_hits() -> None:
    lexical = [
        {"chunk_id": "a", "rank": -1.0, "snippet": "snip a", "text": "text a"},
        {"chunk_id": "b", "rank": -2.0, "snippet": "snip b", "text": "text b"},
    ]
    vector = [
        {"chunk_id": "b", "cosine": 0.9, "text": "text b"},
        {"chunk_id": "c", "cosine": 0.8, "text": "text c"},
    ]
    fused = rrf_fuse(lexical, vector, limit=5)

    assert [hit["chunk_id"] for hit in fused] == ["b", "a", "c"]
    dual = fused[0]
    assert dual["sources"] == ["lexical", "vector"]
    assert dual["rrf_score"] == pytest.approx(1 / 62 + 1 / 61)
    assert dual["lexical_rank"] == 2 and dual["vector_rank"] == 1
    assert dual["bm25"] == -2.0 and dual["cosine"] == 0.9
    # Vector-only hits fall back to their text as snippet.
    assert fused[2]["snippet"] == "text c"


def test_hybrid_search_combines_lexical_and_vector() -> None:
    builder = seed_kb()
    store = builder.store
    provider = StubProvider()
    embed_kb(store, provider)

    # "embeddings" matches ep-vectors lexically; token overlap also makes it
    # win the vector side, so the top hit must come from both sources.
    hits = hybrid_search_kb(store, provider, "embeddings similarity", limit=5)
    assert hits
    top = hits[0]
    assert top["episode_id"] == "ep-vectors"
    assert "lexical" in top["sources"] and "vector" in top["sources"]
    assert top["rrf_score"] > 0


# =============================================================================
# CLI
# =============================================================================


def test_cli_embed_and_search_hybrid(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_kb()
    monkeypatch.setattr(
        "podcast_ctl.cli.commands.kb.get_embedding_provider",
        lambda name="local", model=None: StubProvider(),
    )

    result = runner.invoke(app, ["kb", "embed"])
    assert result.exit_code == 0, result.output
    assert "Embedded" in result.output

    # Auto mode resolves to hybrid once embeddings exist.
    result = runner.invoke(app, ["kb", "search", "embeddings similarity", "--json"])
    assert result.exit_code == 0, result.output
    payload = __import__("json").loads(result.output)
    assert payload
    assert payload[0]["mode"] == "hybrid"
    assert set(payload[0]["sources"]) == {"lexical", "vector"}

    result = runner.invoke(app, ["kb", "search", "embeddings", "--mode", "vector"])
    assert result.exit_code == 0, result.output
    assert "vector" in result.output

    result = runner.invoke(app, ["kb", "search", "embeddings", "--mode", "hybrid"])
    assert result.exit_code == 0, result.output
    assert "Sources" in result.output


def test_cli_search_auto_falls_back_without_embeddings() -> None:
    seed_kb()
    result = runner.invoke(app, ["kb", "search", "stew", "--json"])
    assert result.exit_code == 0, result.output
    payload = __import__("json").loads(result.output)
    assert payload
    assert "mode" not in payload[0]  # lexical payload shape unchanged


def test_cli_search_auto_degrades_when_provider_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = seed_kb()
    embed_kb(builder.store, StubProvider())

    def unavailable(name: str = "local", model: str | None = None) -> StubProvider:
        raise EmbeddingBackendUnavailable("no backend")

    monkeypatch.setattr("podcast_ctl.cli.commands.kb.get_embedding_provider", unavailable)
    result = runner.invoke(app, ["kb", "search", "stew"])
    assert result.exit_code == 0, result.output
    assert "falling back to lexical" in result.output.lower()

    # Explicit vector mode fails instead of degrading.
    result = runner.invoke(app, ["kb", "search", "stew", "--mode", "vector"])
    assert result.exit_code == 1


def test_cli_search_identity_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = seed_kb()
    embed_kb(builder.store, StubProvider(model="stub-model"))
    monkeypatch.setattr(
        "podcast_ctl.cli.commands.kb.get_embedding_provider",
        lambda name="local", model=None: StubProvider(model="other-model"),
    )

    # Auto degrades to lexical with a warning.
    result = runner.invoke(app, ["kb", "search", "stew"])
    assert result.exit_code == 0, result.output
    assert "reindex" in result.output.lower()

    # Explicit hybrid fails with the reindex hint.
    result = runner.invoke(app, ["kb", "search", "stew", "--mode", "hybrid"])
    assert result.exit_code == 1
    assert "reindex" in result.output.lower()


def test_cli_embed_requires_matching_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    builder = seed_kb()
    embed_kb(builder.store, StubProvider(model="stub-model"))
    monkeypatch.setattr(
        "podcast_ctl.cli.commands.kb.get_embedding_provider",
        lambda name="local", model=None: StubProvider(model="other-model"),
    )

    result = runner.invoke(app, ["kb", "embed"])
    assert result.exit_code == 1
    assert "--reindex" in result.output

    result = runner.invoke(app, ["kb", "embed", "--reindex"])
    assert result.exit_code == 0, result.output
    assert "Removed" in result.output


def test_cli_embed_missing_backend_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    seed_kb()

    def unavailable(name: str = "local", model: str | None = None) -> StubProvider:
        raise EmbeddingBackendUnavailable("Install it with: pip install 'podcast-ctl[embeddings]'")

    monkeypatch.setattr("podcast_ctl.cli.commands.kb.get_embedding_provider", unavailable)
    result = runner.invoke(app, ["kb", "embed"])
    assert result.exit_code == 1
    assert "pip install" in result.output


def test_cli_status_shows_embedding_identity() -> None:
    builder = seed_kb()
    embed_kb(builder.store, StubProvider())
    result = runner.invoke(app, ["kb", "status"])
    assert result.exit_code == 0, result.output
    assert "Embedded chunks" in result.output
    assert "stub:stub-model@v1" in result.output
