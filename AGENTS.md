# AGENTS.md — using podcast-ctl from an AI agent

Guide for AI agents with shell access (Codex, Claude Code, Hermes, and any
desktop or coding agent) on how to use `podcast-ctl` and its knowledge base
(KB). Plain Markdown, coupled to no AI provider.

The same guide ships as a skill at
[`skills/podcast-clt/SKILL.md`](skills/podcast-clt/SKILL.md) for skill-based
agent loaders. This file is the canonical version.

## What podcast-ctl is

A Python CLI that finds podcast episodes (RSS feeds, show titles, YouTube
links, local audio files) and transcribes them as cheaply and privately as
possible, then derives a searchable knowledge base from the transcripts. All
data stays on the local machine; cloud APIs are optional fallbacks, never a
requirement.

## Setup

```bash
git clone https://github.com/jose-oc/podcast-clt.git
cd podcast-clt
uv run podcast-ctl --help   # uv resolves and installs everything on first run
```

- Optional fully-local Whisper tier: `uv sync --extra whisper`
- Cloud transcription tiers need `GROQ_API_KEY` / `OPENAI_API_KEY` (both optional)
- The KB lives at `~/.local/share/podcast-ctl/kb/` (override: `PODCAST_CTL_KB_DIR`);
  the transcript cache lives in `~/.local/share/podcast-ctl/podcast_ctl.db`
  (override: `PODCAST_CTL_DB_PATH`)

## The four ways to use the KB with an LLM

1. **Fully local (Ollama)** — a small script pipes `kb search --json` chunks to
   a local model; nothing leaves the machine. Worked example in
   [docs/KNOWLEDGE_BASE.md](docs/KNOWLEDGE_BASE.md).
2. **Copy-paste** — `kb search --context` prints Markdown blocks to paste into
   any cloud chat (ChatGPT, Gemini, Claude, ...).
3. **NotebookLM** — upload `kb/episodes/<show>/*.md` as sources; NotebookLM
   does its own indexing, timestamps survive as plain text.
4. **Agent with shell access (you)** — run the CLI yourself. This path scales
   best: you decide what to search, the CLI does deterministic retrieval, and
   only the relevant chunks ever enter your context, however large the KB grows.

## Command map

| Command | Purpose | Notes for agents |
| :--- | :--- | :--- |
| `search <query>` | Find shows and feeds in the Apple Podcasts catalog | Pass `--no-interactive` when headless |
| `inspect <input>` | Pre-flight: episode list, total duration, disk usage, tier per episode | Always run before a large `transcribe`; it is free |
| `transcribe <input>` | Transcribe episodes into the local cache (and export files) | Interactive by design: pass `--yes` headless |
| `mapping` | Manage show ↔ YouTube channel links | Linking a show unlocks free Tier-2 captions |
| `cache` | Inspect or clean the transcript cache | `cache list` shows what is already transcribed |
| `kb build` | Build or incrementally update the KB from cached transcripts | Reads the cache, not exported files |
| `kb search <query>` | Search the chunk index with citations | `--json` is the machine interface; `--context` is for pasting |
| `kb status` | Show KB location, size, and index stats | |

Full flag-by-flag reference: [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).

## Recommended workflows

### Answer a question from the KB

```bash
podcast-ctl kb search "<keywords>" --json --limit 5
```

- Answer using only the returned chunks and keep the `[Episode @ mm:ss]`
  citation attached to each claim. If the chunks do not answer the question,
  say so and search again with different keywords.
- Search is **lexical** (SQLite FTS5, BM25 ranking), case- and
  diacritics-insensitive (`busqueda` matches `búsqueda`). Query with keywords,
  not full sentences. Terms are ANDed first; if nothing matches, the search
  retries with OR for recall.

### Add a new show to the KB

```bash
podcast-ctl search "Show Name" --no-interactive   # resolve the feed URL
podcast-ctl inspect "<feed-url>"                  # workload + tier preview (free)
podcast-ctl transcribe "<feed-url>" --latest 3 --yes
podcast-ctl kb build                              # incremental; unchanged episodes are skipped
podcast-ctl kb status
```

### Select episodes precisely

- `-e` / `--episode` targets the **published episode number** (feed-declared
  number or leading number in the title), a title substring, or a GUID — never
  the feed position. `-e 2894` selects the episode *numbered* 2894; `-e 1` is
  the newest only when no episode number matches.
- Multi-select: `--episodes 2890,2894,2901`, `--episodes 2890..2900`,
  `--match "<regex>"`, `--since/--until YYYY-MM-DD`, or `--pick` (interactive,
  needs a TTY). Filters compose as logical AND.
- Every selection shows a confirmation table (number, date, title, duration)
  before anything is transcribed; `--yes` auto-confirms for headless runs.

### Control cost and privacy: the 4-tier cascade

Each episode resolves to the cheapest available transcript source,
automatically:

1. **Tier 1** — official Podcasting 2.0 RSS transcript tags (instant, free)
2. **Tier 2** — YouTube captions via learned show ↔ channel mappings (instant, free)
3. **Tier 3** — local faster-whisper on GPU/CPU (private, free; needs the `whisper` extra)
4. **Tier 4** — Groq / OpenAI Whisper APIs (fast; interactive cost guardrails; needs API keys)

`inspect` shows the resolved tier per episode before any time or money is
spent. Finished transcripts are cached in SQLite, so work is never paid twice.

## Output contract

- `kb search` (default): table with `[Episode @ mm:ss]` citations and
  highlighted snippets.
- `kb search --context`: full chunks as Markdown blocks, ready to paste.
- `kb search --json`: array of objects with full chunk text and citation —
  the machine-readable interface for agents and scripts.
- `transcribe --format`: `markdown` (YAML frontmatter), `prose` (.txt),
  `srt`, `vtt`, `json`; `both` (default) or `all`, or comma-separated mixes.

## Common pitfalls

- **Interactive prompts block headless runs.** Pass `--yes` to `transcribe`
  and `--no-interactive` to `search`. `--pick` requires a TTY.
- **`kb build` reads the transcript cache, not exported files.** Run
  `transcribe` first; building right after cloning an empty machine yields an
  empty KB.
- **Tier 3 is skipped silently** when the `whisper` extra is not installed.
- **Tier 4 is unavailable** without `GROQ_API_KEY` / `OPENAI_API_KEY`.
- **Episode number vs feed position** — see "Select episodes precisely" above.
- **The KB is per-machine** (SQLite + Markdown under `PODCAST_CTL_KB_DIR`),
  not committed to the repository.
- **Nothing here talks to an AI provider.** Retrieval is deterministic; the
  choice of model happens entirely outside this tool.

## Provider independence

Hard requirement of the project: the KB is not coupled to any AI provider.
Plain Markdown and JSON come out; any LLM — local, cloud, or agentic — can
consume them, today and after any provider switch.
