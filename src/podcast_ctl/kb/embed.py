"""Embedding index builder: derives and maintains chunk embeddings (phase 2c).

Mirrors the incremental, idempotent behavior of ``kb build``: chunks without
an embedding are embedded in batches, everything else is skipped, and the
provider identity (backend, model, version, dimensions) is recorded so a
provider or model switch triggers a clean, detectable reindex instead of
silently mixing incompatible vectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from podcast_ctl.kb.embeddings import EmbeddingIdentityMismatch, EmbeddingProvider, normalize_vector
from podcast_ctl.kb.store import KbStore, pack_vector

DEFAULT_BATCH_SIZE = 32


@dataclass
class EmbedReport:
    """Summary of one ``kb embed`` run."""

    provider_identity: str
    embedded: int = 0
    already_indexed: int = 0
    removed: int = 0
    reindexed: bool = False
    batch_sizes: list[int] = field(default_factory=list)


def embed_kb(
    store: KbStore,
    provider: EmbeddingProvider,
    show_id: str | None = None,
    reindex: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> EmbedReport:
    """Embed every indexed chunk that lacks a vector for the current provider.

    When the index already holds vectors from a different provider identity,
    refuses to mix them: pass ``reindex=True`` to drop the old vectors and
    rebuild from scratch (a reproducible reindex, since raw snapshots and
    chunks are unchanged).
    """
    report = EmbedReport(provider_identity=provider.identity())

    existing = store.embedding_identity()
    if existing and existing != provider.identity():
        if not reindex:
            raise EmbeddingIdentityMismatch(
                f"The index holds embeddings from '{existing}', but the selected provider is "
                f"'{provider.identity()}'. Mixing vectors from different models breaks similarity "
                "search. Re-run with --reindex to rebuild all embeddings with the new provider "
                "(chunks and raw snapshots are untouched), or select the original provider."
            )
        report.removed = store.delete_embeddings()
        report.reindexed = True

    missing = store.chunks_missing_embeddings(show_id=show_id)
    scoped_total = store.count_chunks(show_id=show_id)
    report.already_indexed = 0 if report.reindexed else scoped_total - len(missing)

    for offset in range(0, len(missing), batch_size):
        batch = missing[offset : offset + batch_size]
        texts = [str(row["text"]) for row in batch]
        vectors = provider.embed(texts)
        if len(vectors) != len(batch):
            raise RuntimeError(f"Embedding provider returned {len(vectors)} vectors for {len(texts)} texts.")
        rows = [
            (
                str(row["chunk_id"]),
                provider.model,
                provider.version,
                len(vector),
                pack_vector(normalize_vector(vector)),
            )
            for row, vector in zip(batch, vectors, strict=True)
        ]
        store.upsert_embeddings(rows, identity=provider.identity())
        report.embedded += len(rows)
        report.batch_sizes.append(len(rows))

    return report
