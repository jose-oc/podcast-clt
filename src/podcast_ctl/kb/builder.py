"""Knowledge base builder: derives Markdown, chunks, and the FTS5 index.

The builder mirrors the catalog transcript cache into the knowledge base:

1. Write-once raw JSON snapshots under ``raw/<show>/<episode>.json``.
2. Derived per-episode Markdown under ``episodes/<show>/<episode>.md``.
3. Retrieval chunks + FTS5 rows in ``db/kb.sqlite``.
4. A regenerated ``INDEX.md`` catalog.

Builds are idempotent: an episode whose content hash (and pipeline version)
is unchanged is skipped; a changed episode re-derives only its own artifacts
and index rows; episodes removed from the cache are pruned from the KB.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from podcast_ctl.exporters.base import format_duration
from podcast_ctl.kb.chunking import chunk_episode
from podcast_ctl.kb.config import (
    PIPELINE_VERSION,
    get_default_kb_dir,
    kb_db_path,
    kb_episodes_dir,
    kb_index_path,
    kb_raw_dir,
)
from podcast_ctl.kb.markdown import normalize_date, render_episode_markdown
from podcast_ctl.kb.store import KbStore
from podcast_ctl.models.transcript import TranscriptResult
from podcast_ctl.storage.repository import StorageRepository


def slugify(value: str, max_len: int = 80) -> str:
    """Filesystem-safe slug for show and episode identifiers.

    Diacritics are folded, non-alphanumerics collapse to dashes. Over-long
    values keep a short content hash suffix so distinct sources still map to
    distinct files.
    """
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "untitled"
    if len(slug) > max_len:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[:max_len].rstrip('-')}-{digest}"
    return slug


def content_hash_of(result: TranscriptResult) -> str:
    """Stable content hash of a transcript's canonical JSON serialization."""
    return hashlib.sha256(result.model_dump_json().encode("utf-8")).hexdigest()


@dataclass
class BuildReport:
    """Summary of one `kb build` run."""

    kb_dir: Path
    index_path: Path
    built: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)

    @property
    def total_indexed(self) -> int:
        return len(self.built) + len(self.skipped)


class KbBuilder:
    """Derives and maintains the knowledge base from the transcript cache."""

    def __init__(self, repo: StorageRepository | None = None, kb_dir: Path | None = None) -> None:
        self.repo = repo or StorageRepository()
        self.kb_dir = Path(kb_dir) if kb_dir else get_default_kb_dir()
        self.store = KbStore(kb_db_path(self.kb_dir))

    def build(self, show_id: str | None = None) -> BuildReport:
        """Rebuild the KB for every cached transcript (or one show)."""
        transcripts = self.repo.list_transcripts(show_id)
        seen: set[tuple[str, str]] = set()
        built: list[str] = []
        skipped: list[str] = []

        for result in transcripts:
            meta = result.metadata
            sid, eid = meta.effective_show_id, meta.episode_id
            seen.add((sid, eid))
            label = f"{meta.show_title} — {meta.episode_title}"

            content_hash = content_hash_of(result)
            if self.store.get_episode_hash(sid, eid) == f"v{PIPELINE_VERSION}:{content_hash}":
                skipped.append(label)
                continue

            raw_rel = self._write_raw(result, sid, eid)
            md_rel = self._write_markdown(result, content_hash, sid, eid)
            chunks = chunk_episode(result)

            manifest: dict[str, object] = {
                "show_id": sid,
                "episode_id": eid,
                "show_title": meta.show_title,
                "episode_title": meta.episode_title,
                "published_date": normalize_date(meta.published_date),
                "duration_s": meta.duration_seconds,
                "tier_used": str(result.tier_used),
                "episode_url": meta.audio_url,
                "content_hash": f"v{PIPELINE_VERSION}:{content_hash}",
                "pipeline_version": PIPELINE_VERSION,
                "md_path": md_rel,
                "raw_path": raw_rel,
            }
            self.store.upsert_episode(manifest, chunks)
            built.append(label)

        pruned = self._prune(seen, show_id)
        index_path = self._write_index()
        return BuildReport(kb_dir=self.kb_dir, index_path=index_path, built=built, skipped=skipped, pruned=pruned)

    # ------------------------------------------------------------------
    # Artifact writers
    # ------------------------------------------------------------------

    def _write_raw(self, result: TranscriptResult, show_id: str, episode_id: str) -> str:
        """Write the immutable raw JSON snapshot; returns the KB-relative path."""
        rel = Path(slugify(show_id)) / f"{slugify(episode_id)}.json"
        path = kb_raw_dir(self.kb_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return str(Path("raw") / rel)

    def _write_markdown(self, result: TranscriptResult, content_hash: str, show_id: str, episode_id: str) -> str:
        """Write the derived per-episode Markdown; returns the KB-relative path."""
        rel = Path(slugify(show_id)) / f"{slugify(episode_id)}.md"
        path = kb_episodes_dir(self.kb_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_episode_markdown(result, content_hash), encoding="utf-8")
        return str(Path("episodes") / rel)

    def _write_index(self) -> Path:
        """Regenerate INDEX.md from the current manifest."""
        episodes = self.store.list_episodes()
        shows = {str(row["show_title"]) for row in episodes}

        lines = [
            "# Knowledge Base Index",
            "",
            f"{len(episodes)} episodes across {len(shows)} shows. "
            "Regenerated by `podcast-ctl kb build`; do not edit by hand.",
            "",
            "| Show | Episode | Date | Duration | Chunks |",
            "| :--- | :--- | :--- | :--- | ---: |",
        ]
        for row in episodes:
            md_path = str(row["md_path"] or "")
            title = str(row["episode_title"])
            link = f"[{title}]({md_path})" if md_path else title
            lines.append(
                "| {show} | {episode} | {date} | {duration} | {chunks} |".format(
                    show=str(row["show_title"]),
                    episode=link,
                    date=str(row["published_date"] or ""),
                    duration=format_duration(row["duration_s"] if isinstance(row["duration_s"], (int, float)) else None),
                    chunks=row["chunk_count"],
                )
            )

        path = kb_index_path(self.kb_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def _prune(self, seen: set[tuple[str, str]], show_id: str | None) -> list[str]:
        """Drop KB episodes whose source transcript left the cache."""
        pruned: list[str] = []
        for row in self.store.list_episodes():
            sid = str(row["show_id"])
            eid = str(row["episode_id"])
            if show_id is not None and sid != show_id:
                continue
            if (sid, eid) in seen:
                continue
            self.store.delete_episode(sid, eid)
            for key in ("md_path", "raw_path"):
                rel = row.get(key)
                if rel:
                    artifact = self.kb_dir / str(rel)
                    artifact.unlink(missing_ok=True)
            pruned.append(f"{row['show_title']} — {row['episode_title']}")
        return pruned
