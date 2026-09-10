"""Knowledge base configuration: filesystem layout and pipeline constants."""

from __future__ import annotations

import os
from pathlib import Path

from podcast_ctl.storage.db import DEFAULT_DB_DIR, get_default_db_path

# Bump whenever the derivation pipeline (Markdown rendering, chunking rules,
# index schema) changes in a way that requires re-deriving artifacts. Episodes
# whose stored pipeline_version differs are rebuilt on the next `kb build`.
PIPELINE_VERSION = 1

# Chunk sizing (characters). Chunks group whole speaker turns toward the
# target, never splitting a turn mid-way; turns longer than the max are split
# beforehand at sentence boundaries.
CHUNK_TARGET_CHARS = 1200
CHUNK_MAX_CHARS = 1500
CHUNK_OVERLAP_CHARS = 180

# Pause (seconds) that separates two speaker turns when the source has no
# speaker labels. Mirrors the Markdown exporter default.
MAX_PAUSE_SECONDS = 3.0

# Chapter label used until the post-processing chaptering step exists.
DEFAULT_CHAPTER = "Full episode"


def get_default_kb_dir() -> Path:
    """Return the knowledge base root directory.

    Resolution order:
    1. ``PODCAST_CTL_KB_DIR`` environment variable (explicit override).
    2. ``kb/`` next to the catalog database when ``PODCAST_CTL_DB_PATH`` is set.
    3. ``~/.local/share/podcast-ctl/kb``.
    """
    env_kb = os.environ.get("PODCAST_CTL_KB_DIR")
    if env_kb:
        return Path(env_kb)
    if os.environ.get("PODCAST_CTL_DB_PATH"):
        return get_default_db_path().parent / "kb"
    return DEFAULT_DB_DIR / "kb"


def kb_raw_dir(kb_dir: Path) -> Path:
    """Directory holding write-once raw transcript snapshots."""
    return kb_dir / "raw"


def kb_episodes_dir(kb_dir: Path) -> Path:
    """Directory holding derived per-episode Markdown documents."""
    return kb_dir / "episodes"


def kb_db_path(kb_dir: Path) -> Path:
    """Path of the knowledge base SQLite index (separate from the catalog DB)."""
    return kb_dir / "db" / "kb.sqlite"


def kb_index_path(kb_dir: Path) -> Path:
    """Path of the browsable INDEX.md catalog."""
    return kb_dir / "INDEX.md"
