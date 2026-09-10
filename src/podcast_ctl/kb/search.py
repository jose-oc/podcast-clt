"""Search helpers: lexical, vector, and hybrid (RRF) retrieval with citations.

Three modes (docs/KNOWLEDGE_BASE_DESIGN.md):

- ``lexical``: SQLite FTS5 BM25 — exact matches (names, terms) with zero
  extra infrastructure.
- ``vector``: cosine similarity over chunk embeddings — paraphrase and
  concept queries.
- ``hybrid``: Reciprocal Rank Fusion (k=60) over both ranked lists, which
  outperforms either alone.
"""

from __future__ import annotations

from podcast_ctl.exporters.base import format_timestamp
from podcast_ctl.kb.embeddings import EmbeddingProvider, normalize_vector
from podcast_ctl.kb.store import KbStore

MODE_LEXICAL = "lexical"
MODE_VECTOR = "vector"
MODE_HYBRID = "hybrid"
SEARCH_MODES = (MODE_LEXICAL, MODE_VECTOR, MODE_HYBRID)

# Reciprocal Rank Fusion constant; k=60 is the standard value from the RRF
# paper and keeps head ranks dominant without zeroing the tail.
RRF_K = 60

# How many candidates each ranked list contributes to the fusion.
HYBRID_CANDIDATE_LIMIT = 100


def search_kb(store: KbStore, query: str, limit: int = 10, show_id: str | None = None) -> list[dict[str, object]]:
    """Run a lexical search over the KB index (see KbStore.search)."""
    return store.search(query, limit=limit, show_id=show_id)


def vector_search_kb(
    store: KbStore,
    provider: EmbeddingProvider,
    query: str,
    limit: int = 10,
    show_id: str | None = None,
) -> list[dict[str, object]]:
    """Run a vector search: embed the query and rank chunks by cosine."""
    query_vector = normalize_vector(provider.embed([query])[0])
    hits = store.vector_search(query_vector, limit=limit, show_id=show_id)
    for hit in hits:
        # Vector hits have no FTS snippet; the table/JSON fall back to text.
        hit.setdefault("snippet", hit.get("text", ""))
    return hits


def hybrid_search_kb(
    store: KbStore,
    provider: EmbeddingProvider,
    query: str,
    limit: int = 10,
    show_id: str | None = None,
    candidate_limit: int = HYBRID_CANDIDATE_LIMIT,
) -> list[dict[str, object]]:
    """Fuse lexical and vector ranked lists with Reciprocal Rank Fusion."""
    lexical_hits = store.search(query, limit=candidate_limit, show_id=show_id)
    vector_hits = vector_search_kb(store, provider, query, limit=candidate_limit, show_id=show_id)
    return rrf_fuse(lexical_hits, vector_hits, limit=limit)


def rrf_fuse(
    lexical_hits: list[dict[str, object]],
    vector_hits: list[dict[str, object]],
    limit: int = 10,
    k: int = RRF_K,
) -> list[dict[str, object]]:
    """Merge two ranked lists into one with Reciprocal Rank Fusion.

    Each hit keeps its provenance: which list(s) ranked it, the per-list
    positions, and the underlying BM25 / cosine scores. Ties break toward
    the best per-list rank, then chunk ID, so output is deterministic.
    """
    fused: dict[str, dict[str, object]] = {}

    for source, hits, score_key in (
        ("lexical", lexical_hits, "bm25"),
        ("vector", vector_hits, "cosine"),
    ):
        for position, hit in enumerate(hits, start=1):
            chunk_id = str(hit["chunk_id"])
            entry = fused.setdefault(
                chunk_id,
                {
                    key: hit.get(key)
                    for key in (
                        "chunk_id",
                        "show_id",
                        "episode_id",
                        "show_title",
                        "episode_title",
                        "chapter",
                        "position",
                        "start_s",
                        "end_s",
                        "text",
                    )
                },
            )
            previous = entry.get("rrf_score")
            entry["rrf_score"] = (float(previous) if isinstance(previous, (int, float)) else 0.0) + 1.0 / (k + position)
            entry.setdefault("sources", [])
            sources = entry["sources"]
            assert isinstance(sources, list)
            sources.append(source)
            entry[f"{source}_rank"] = position
            if source == "lexical":
                entry["bm25"] = hit.get("rank")
                entry["snippet"] = hit.get("snippet")
            else:
                entry["cosine"] = hit.get(score_key)

    def sort_key(item: dict[str, object]) -> tuple[float, float, str]:
        best_rank = min(rank for rank in (item.get("lexical_rank"), item.get("vector_rank")) if isinstance(rank, int))
        rrf = item["rrf_score"]
        return (-(float(rrf) if isinstance(rrf, (int, float)) else 0.0), float(best_rank), str(item["chunk_id"]))

    merged = sorted(fused.values(), key=sort_key)[:limit]
    for item in merged:
        item["rank"] = item["rrf_score"]
        # Vector-only hits have no FTS snippet; fall back to the text itself.
        if not item.get("snippet"):
            item["snippet"] = item.get("text", "")
    return merged


def format_citation(hit: dict[str, object]) -> str:
    """Render a hit as an ``[Episode @ mm:ss]`` citation."""
    start = hit.get("start_s")
    ts = format_timestamp(float(start), always_include_hours=False) if isinstance(start, (int, float)) else "00:00"
    return f"[{hit.get('episode_title', '')} @ {ts}]"


def format_context_block(hit: dict[str, object]) -> str:
    """Render a hit as a copy-pastable Markdown block for LLM prompts."""
    citation = format_citation(hit)
    return f"### {citation} — {hit.get('show_title', '')}\n\n{hit.get('text', '')}"
