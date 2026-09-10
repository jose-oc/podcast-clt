#!/usr/bin/env python3
"""Reproducible offline demo of the Phase 2 knowledge base.

Seeds two synthetic episodes into an isolated catalog cache, builds the
knowledge base (raw snapshots, per-episode Markdown, INDEX.md, FTS5 chunk
index), runs a search, and prints the retrieved chunks with citations.

No network, API keys, or models required:

    uv run python examples/kb_quickstart.py

Optional final step — send the retrieved chunks to a local Ollama model
(requires `ollama serve` and the model pulled, e.g. `ollama pull qwen3`):

    uv run python examples/kb_quickstart.py --ollama qwen3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

# Isolate the demo: point the catalog DB and KB at a temp directory BEFORE
# importing podcast_ctl modules, which resolve paths from the environment.
_TMP = Path(tempfile.mkdtemp(prefix="podcast-ctl-kb-demo-"))
os.environ["PODCAST_CTL_DB_PATH"] = str(_TMP / "demo_catalog.db")
os.environ["PODCAST_CTL_KB_DIR"] = str(_TMP / "kb")

from podcast_ctl.kb.builder import KbBuilder  # noqa: E402
from podcast_ctl.kb.search import format_context_block, search_kb  # noqa: E402
from podcast_ctl.models.transcript import EpisodeMetadata, TranscriptResult, TranscriptSegment  # noqa: E402
from podcast_ctl.storage.repository import StorageRepository  # noqa: E402

QUESTION = "What did they say about vector databases?"


def seed_transcripts(repo: StorageRepository) -> None:
    """Write two synthetic episodes into the demo catalog cache."""
    ep1 = TranscriptResult(
        metadata=EpisodeMetadata(
            show_title="Demo Podcast",
            episode_title="Ep 1 — Search engines",
            episode_id="demo-ep-1",
            audio_url="https://example.com/demo/ep1.mp3",
            duration_seconds=120.0,
            published_date="2026-09-01",
        ),
        segments=[
            TranscriptSegment(start=0.0, end=6.0, text="Welcome to the demo episode about search.", speaker="Host"),
            TranscriptSegment(start=6.3, end=12.0, text="Vector databases store embeddings for similarity search.", speaker="Guest"),
            TranscriptSegment(start=12.4, end=18.0, text="They shine on paraphrases, while BM25 nails exact terms.", speaker="Guest"),
            TranscriptSegment(start=22.0, end=28.0, text="So hybrid search fuses both ranked lists.", speaker="Host"),
        ],
        tier_used="rss",
    )
    ep2 = TranscriptResult(
        metadata=EpisodeMetadata(
            show_title="Demo Podcast",
            episode_title="Ep 2 — Local models",
            episode_id="demo-ep-2",
            audio_url="https://example.com/demo/ep2.mp3",
            duration_seconds=90.0,
            published_date="2026-09-08",
        ),
        segments=[
            TranscriptSegment(start=0.0, end=5.0, text="Today we run everything locally.", speaker="Host"),
            TranscriptSegment(start=5.3, end=11.0, text="Local embeddings keep transcripts on your machine.", speaker="Guest"),
        ],
        tier_used="whisper",
    )
    repo.save_transcript(ep1)
    repo.save_transcript(ep2)


def ask_ollama(model: str, question: str, context: str) -> str:
    """Send the question plus retrieved chunks to a local Ollama model."""
    prompt = (
        "Answer the question using ONLY the context below. "
        "Cite sources as [Episode @ mm:ss]. If the context does not answer it, say so.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return str(json.loads(resp.read())["response"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", metavar="MODEL", help="Also ask a local Ollama model with the retrieved chunks.")
    args = parser.parse_args()

    print(f"Demo workspace: {_TMP}\n")

    print("1. Seeding two synthetic episodes into the demo catalog cache...")
    repo = StorageRepository()
    seed_transcripts(repo)

    print("2. Building the knowledge base (raw JSON, Markdown, INDEX.md, FTS5 chunks)...")
    builder = KbBuilder()
    report = builder.build()
    for label in report.built:
        print(f"   + {label}")
    print(f"   KB directory: {report.kb_dir}")
    print(f"   Catalog:      {report.index_path}")

    print(f"\n3. Searching: {QUESTION!r}")
    hits = search_kb(builder.store, QUESTION, limit=3)
    blocks = [format_context_block(hit) for hit in hits]
    print("\n\n".join(blocks))

    if args.ollama:
        print(f"\n4. Asking local Ollama model {args.ollama!r} with the chunks above...")
        print(ask_ollama(args.ollama, QUESTION, "\n\n".join(blocks)))
    else:
        print("\n4. Skipped LLM step (pass --ollama MODEL to try a local model).")
        print("   Or paste the blocks above into any chat: ChatGPT, Gemini, Claude, Z.ai...")

    print("\nDone. Everything above was derived from the raw snapshots; delete the KB and `kb build` rebuilds it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
