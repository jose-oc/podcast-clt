"""SQLite storage for the knowledge base index (separate from the catalog DB).

``kb.sqlite`` holds the episode manifest, the chunk table, an FTS5 lexical
index (BM25) kept in sync by triggers, and an ``embeddings`` table with one
unit-normalized vector per chunk (phase 2c). Every derived row records the
pipeline version and model metadata that produced it, so the index can be
rebuilt cleanly when the pipeline or the embedding provider changes.

Vectors are stored as float32 BLOBs and compared with an in-process cosine
(dot product over unit vectors) instead of a native SQLite extension: the
index stays portable (no extension loading, no architecture-specific
binaries), and KB-scale corpora scan in milliseconds. A native ANN index
(sqlite-vec or similar) can be adopted later as a pure performance change;
the stored vectors and their provenance metadata would not need rebuilding.
"""

from __future__ import annotations

import sqlite3
import struct
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from podcast_ctl.kb.models import Chunk

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS kb_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS kb_episodes (
    show_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    show_title TEXT NOT NULL,
    episode_title TEXT NOT NULL,
    published_date TEXT,
    duration_s REAL,
    tier_used TEXT,
    episode_url TEXT,
    content_hash TEXT NOT NULL,
    pipeline_version INTEGER NOT NULL,
    md_path TEXT,
    raw_path TEXT,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    built_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (show_id, episode_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    show_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    show_title TEXT NOT NULL,
    episode_title TEXT NOT NULL,
    chapter TEXT NOT NULL,
    position INTEGER NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    text TEXT NOT NULL,
    segment_start INTEGER NOT NULL,
    segment_end INTEGER NOT NULL,
    pipeline_version INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_episode ON chunks(show_id, episode_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    show_title,
    episode_title,
    chapter,
    content='chunks',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, show_title, episode_title, chapter)
    VALUES (new.rowid, new.text, new.show_title, new.episode_title, new.chapter);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, show_title, episode_title, chapter)
    VALUES ('delete', old.rowid, old.text, old.show_title, old.episode_title, old.chapter);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, show_title, episode_title, chapter)
    VALUES ('delete', old.rowid, old.text, old.show_title, old.episode_title, old.chapter);
    INSERT INTO chunks_fts(rowid, text, show_title, episode_title, chapter)
    VALUES (new.rowid, new.text, new.show_title, new.episode_title, new.chapter);
END;

-- One embedding per chunk, always tagged with the model that produced it so
-- a provider switch triggers a detectable reindex instead of silently mixing
-- incompatible vectors. Vectors are float32 little-endian BLOBs, unit-norm.
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id TEXT PRIMARY KEY REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vector BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _query_terms(raw_query: str) -> list[str]:
    """Split a free-text query into safe FTS5 terms (quotes stripped)."""
    terms = []
    for part in raw_query.split():
        cleaned = part.replace('"', " ").strip()
        if cleaned:
            terms.append(cleaned)
    return terms


def pack_vector(vector: list[float]) -> bytes:
    """Serialize a float vector as little-endian float32 bytes."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes) -> list[float]:
    """Deserialize little-endian float32 bytes into a float vector."""
    dims = len(blob) // 4
    return list(struct.unpack(f"<{dims}f", blob))


class KbStore:
    """Storage layer over the knowledge base SQLite index."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a WAL-mode connection, committing on success."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Episode manifest
    # ------------------------------------------------------------------

    def get_episode_hash(self, show_id: str, episode_id: str) -> str | None:
        """Return the stored content hash for an episode, or None if absent."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT content_hash FROM kb_episodes WHERE show_id = ? AND episode_id = ?",
                (show_id, episode_id),
            ).fetchone()
        return str(row["content_hash"]) if row else None

    def upsert_episode(self, manifest: dict[str, object], chunks: list[Chunk]) -> None:
        """Replace an episode's manifest row and chunks in one transaction."""
        show_id = str(manifest["show_id"])
        episode_id = str(manifest["episode_id"])
        with self.connection() as conn:
            conn.execute("DELETE FROM chunks WHERE show_id = ? AND episode_id = ?", (show_id, episode_id))
            conn.execute(
                """
                INSERT INTO kb_episodes (
                    show_id, episode_id, show_title, episode_title, published_date,
                    duration_s, tier_used, episode_url, content_hash, pipeline_version,
                    md_path, raw_path, chunk_count, built_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(show_id, episode_id) DO UPDATE SET
                    show_title = excluded.show_title,
                    episode_title = excluded.episode_title,
                    published_date = excluded.published_date,
                    duration_s = excluded.duration_s,
                    tier_used = excluded.tier_used,
                    episode_url = excluded.episode_url,
                    content_hash = excluded.content_hash,
                    pipeline_version = excluded.pipeline_version,
                    md_path = excluded.md_path,
                    raw_path = excluded.raw_path,
                    chunk_count = excluded.chunk_count,
                    built_at = CURRENT_TIMESTAMP
                """,
                (
                    show_id,
                    episode_id,
                    manifest["show_title"],
                    manifest["episode_title"],
                    manifest["published_date"],
                    manifest["duration_s"],
                    manifest["tier_used"],
                    manifest["episode_url"],
                    manifest["content_hash"],
                    manifest["pipeline_version"],
                    manifest["md_path"],
                    manifest["raw_path"],
                    len(chunks),
                ),
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO chunks (
                    chunk_id, show_id, episode_id, show_title, episode_title, chapter,
                    position, start_s, end_s, text, segment_start, segment_end, pipeline_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c.chunk_id,
                        c.show_id,
                        c.episode_id,
                        c.show_title,
                        c.episode_title,
                        c.chapter,
                        c.position,
                        c.start_s,
                        c.end_s,
                        c.text,
                        c.segment_start,
                        c.segment_end,
                        manifest["pipeline_version"],
                    )
                    for c in chunks
                ],
            )

    def delete_episode(self, show_id: str, episode_id: str) -> None:
        """Remove an episode and all of its chunks from the index."""
        with self.connection() as conn:
            conn.execute("DELETE FROM chunks WHERE show_id = ? AND episode_id = ?", (show_id, episode_id))
            conn.execute("DELETE FROM kb_episodes WHERE show_id = ? AND episode_id = ?", (show_id, episode_id))

    def list_episodes(self) -> list[dict[str, object]]:
        """List indexed episodes ordered by show, then newest first."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT show_id, episode_id, show_title, episode_title, published_date,
                       duration_s, tier_used, episode_url, content_hash, pipeline_version,
                       md_path, raw_path, chunk_count, built_at
                FROM kb_episodes
                ORDER BY show_title COLLATE NOCASE, published_date DESC, episode_title COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        """Return aggregate counts for the index."""
        with self.connection() as conn:
            episodes = conn.execute("SELECT COUNT(*) AS n FROM kb_episodes").fetchone()["n"]
            chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
            vectors = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"]
        return {"episodes": int(episodes), "chunks": int(chunks), "embeddings": int(vectors)}

    def count_chunks(self, show_id: str | None = None) -> int:
        """Count indexed chunks, optionally scoped to one show."""
        sql = "SELECT COUNT(*) AS n FROM chunks"
        params: list[object] = []
        if show_id is not None:
            sql += " WHERE show_id = ?"
            params.append(show_id)
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------
    # KB metadata (provenance key/value store)
    # ------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        """Return a kb_meta value, or None when unset."""
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM kb_meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        """Upsert a kb_meta value."""
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO kb_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------------
    # Embeddings (vector phase 2c)
    # ------------------------------------------------------------------

    def embedding_identity(self) -> str | None:
        """Identity (provider:model@version) of the vectors in the index."""
        return self.get_meta("embedding_identity")

    def delete_embeddings(self) -> int:
        """Drop every stored embedding (full reindex). Returns the count."""
        with self.connection() as conn:
            count = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()["n"]
            conn.execute("DELETE FROM embeddings")
            conn.execute("DELETE FROM kb_meta WHERE key IN ('embedding_identity', 'embedding_dims')")
        return int(count)

    def chunks_missing_embeddings(self, show_id: str | None = None) -> list[dict[str, object]]:
        """Return chunks that have no embedding row yet (id and text only)."""
        sql = """
            SELECT c.chunk_id, c.text
            FROM chunks c
            LEFT JOIN embeddings e ON e.chunk_id = c.chunk_id
            WHERE e.chunk_id IS NULL
        """
        params: list[object] = []
        if show_id is not None:
            sql += " AND c.show_id = ?"
            params.append(show_id)
        sql += " ORDER BY c.show_id, c.episode_id, c.position"
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def upsert_embeddings(
        self,
        rows: list[tuple[str, str, str, int, bytes]],
        identity: str,
    ) -> None:
        """Insert or replace embedding rows and record the provider identity.

        Each row is ``(chunk_id, model, model_version, dims, vector_blob)``;
        vectors must already be unit-normalized so cosine is a dot product.
        """
        if not rows:
            return
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO embeddings (chunk_id, model, model_version, dims, vector, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                rows,
            )
            conn.execute(
                "INSERT INTO kb_meta (key, value) VALUES ('embedding_identity', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (identity,),
            )
            conn.execute(
                "INSERT INTO kb_meta (key, value) VALUES ('embedding_dims', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(rows[0][3]),),
            )

    def vector_search(
        self,
        query_vector: list[float],
        limit: int = 10,
        show_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Rank chunks by cosine similarity against a unit-norm query vector.

        In-process scan over float32 BLOBs (dot product, since every stored
        vector is unit-normalized). Rows whose dimensionality differs from
        the query vector are skipped — they belong to an incompatible model.
        Each hit carries ``cosine`` (higher is better) in ``rank``.
        """
        sql = """
            SELECT c.chunk_id, c.show_id, c.episode_id, c.show_title, c.episode_title,
                   c.chapter, c.position, c.start_s, c.end_s, c.text,
                   e.dims, e.vector
            FROM embeddings e
            JOIN chunks c ON c.chunk_id = e.chunk_id
        """
        params: list[object] = []
        if show_id is not None:
            sql += " WHERE c.show_id = ?"
            params.append(show_id)

        query_dims = len(query_vector)
        scored: list[tuple[float, dict[str, object]]] = []
        with self.connection() as conn:
            for row in conn.execute(sql, params):
                if int(row["dims"]) != query_dims:
                    continue
                candidate = unpack_vector(row["vector"])
                score = sum(q * v for q, v in zip(query_vector, candidate, strict=True))
                hit = {key: row[key] for key in row.keys() if key not in ("dims", "vector")}
                scored.append((score, hit))

        scored.sort(key=lambda item: (-item[0], str(item[1]["chunk_id"])))
        hits = []
        for score, hit in scored[:limit]:
            hit["rank"] = score
            hit["cosine"] = score
            hits.append(hit)
        return hits

    # ------------------------------------------------------------------
    # Lexical search (FTS5 / BM25)
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 10, show_id: str | None = None) -> list[dict[str, object]]:
        """Search chunks with BM25 ranking.

        Terms are ANDed first for precision; when nothing matches and the
        query has several terms, it falls back to OR for recall. Matching is
        case- and diacritics-insensitive (``unicode61 remove_diacritics 2``).
        """
        terms = _query_terms(query)
        if not terms:
            return []

        operators = ("AND", "OR") if len(terms) > 1 else ("AND",)
        for op in operators:
            fts_query = f" {op} ".join(f'"{term}"' for term in terms)
            rows = self._run_match(fts_query, limit=limit, show_id=show_id)
            if rows or op == "OR":
                return rows
        return []

    def _run_match(self, fts_query: str, limit: int, show_id: str | None) -> list[dict[str, object]]:
        sql = """
            SELECT c.chunk_id, c.show_id, c.episode_id, c.show_title, c.episode_title,
                   c.chapter, c.position, c.start_s, c.end_s, c.text,
                   snippet(chunks_fts, 0, '**', '**', ' … ', 40) AS snippet,
                   bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
        """
        params: list[object] = [fts_query]
        if show_id is not None:
            sql += " AND c.show_id = ?"
            params.append(show_id)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
