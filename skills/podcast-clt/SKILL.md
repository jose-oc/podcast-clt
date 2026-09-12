---
name: podcast-clt
description: Use the podcast-ctl CLI to transcribe podcast episodes and query the local knowledge base with [Episode @ mm:ss] citations. Use when a task involves searching podcast transcripts, adding shows to the KB, or feeding podcast content to an LLM.
---

# podcast-ctl

CLI that transcribes podcast episodes (4-tier cascade: RSS tags → YouTube
captions → local Whisper → cloud APIs) and builds a local, provider-agnostic
knowledge base (per-episode Markdown + FTS5 search index).

**Canonical guide: [AGENTS.md](../../AGENTS.md)** at the repository root —
read it for full workflows, the output contract, and pitfalls. This skill is
the same guide in condensed form; update AGENTS.md first and keep this file
in sync.

## Quick reference

```bash
uv run podcast-ctl --help                          # setup: uv handles everything
podcast-ctl inspect "<feed-or-show>"               # pre-flight, free — run before transcribing
podcast-ctl transcribe "<feed-or-show>" --latest 3 --yes
podcast-ctl transcribe "<show>" --episodes 2890..2900 --match "regex" --yes
podcast-ctl kb build                               # incremental, from the transcript cache
podcast-ctl kb search "<keywords>" --json --limit 5   # machine-readable chunks + citations
podcast-ctl kb search "<keywords>" --context       # Markdown blocks for pasting into a chat
podcast-ctl kb status
```

## Rules of thumb

- Headless: always pass `--yes` (transcribe) / `--no-interactive` (search).
- `--episode N` matches the **published episode number**, not the feed position.
- `kb build` reads the transcript **cache** — transcribe first.
- Answer from `kb search --json` chunks only, and preserve every
  `[Episode @ mm:ss]` citation. Search with keywords, not sentences; the index
  is lexical (FTS5 + BM25, diacritics-insensitive).
- No AI provider is required or configured anywhere in this tool.
