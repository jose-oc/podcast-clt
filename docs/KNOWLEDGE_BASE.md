# Knowledge Base Guide (Phase 2)

The knowledge base (KB) turns your cached transcripts into a browsable,
searchable, LLM-ready corpus. It implements phases **2a** (derived per-episode
Markdown + catalog), **2b** (chunk index + FTS5 lexical search), and **2c**
(local embeddings + hybrid lexical/vector search) of
[KNOWLEDGE_BASE_DESIGN.md](KNOWLEDGE_BASE_DESIGN.md). The evaluation harness
(2d) comes next; the index schema already records the provenance it needs.

## Layout

Everything lives under one KB directory (default
`~/.local/share/podcast-ctl/kb/`):

```
kb/
  raw/<show>/<episode>.json        # write-once snapshot of the source transcript
  episodes/<show>/<episode>.md     # derived per-episode Markdown document
  INDEX.md                         # browsable catalog (regenerated on every build)
  db/kb.sqlite                     # chunk index + FTS5 + embeddings (separate from the catalog DB)
```

- **Raw is the source of truth.** `raw/` snapshots are content-hashed and
  never edited; every other artifact derives from them and can be deleted and
  rebuilt at any time.
- **The Markdown layer is plain files.** Move it, zip it, sync it, or paste
  it anywhere — nothing depends on a database to read it.
- **The index is disposable.** `kb.sqlite` is separate from the catalog
  database (`podcast_ctl.db`). Delete it and `kb build` recreates it.

## Commands

```bash
# Build (or incrementally update) the KB from all cached transcripts
podcast-ctl kb build

# Build only one show
podcast-ctl kb build --show "Monos Estocásticos"

# Embed chunks for vector/hybrid search (local model, runs on your machine)
podcast-ctl kb embed

# Search: table with [Episode @ mm:ss] citations and highlighted snippets
podcast-ctl kb search "búsqueda semántica"

# Search: full chunks as Markdown blocks, ready to paste into an LLM
podcast-ctl kb search "búsqueda semántica" --context

# Search: JSON for scripting (includes full chunk text and citation)
podcast-ctl kb search "búsqueda semántica" --json --limit 5

# Where everything lives and how big it is
podcast-ctl kb status
```

Search defaults to `--mode auto`: hybrid retrieval once embeddings exist,
plain lexical before that. Force a mode with `--mode lexical|vector|hybrid`.

- **lexical**: SQLite FTS5, BM25 ranking, case- and diacritics-insensitive
  (`busqueda` matches `búsqueda`). Terms are ANDed first; if nothing
  matches, the search retries with OR for recall.
- **vector**: cosine similarity over chunk embeddings — paraphrase and
  concept queries that lexical search misses.
- **hybrid**: Reciprocal Rank Fusion (k=60) over both ranked lists, which
  outperforms either alone. The table adds a Sources column showing which
  retriever(s) ranked each hit.

## Embeddings and hybrid search (phase 2c)

`kb embed` derives one vector per chunk so vector and hybrid search work.
Like `kb build`, it is incremental and idempotent: only chunks without an
embedding are processed, and re-running it after `kb build` picks up exactly
the chunks a rebuild replaced.

```bash
# Local embeddings (default). First install pulls the optional extra:
#   pip install 'podcast-ctl[embeddings]'
podcast-ctl kb embed

# Different local model
podcast-ctl kb embed --model intfloat/multilingual-e5-base --reindex

# Optional cloud adapter: any OpenAI-compatible embeddings endpoint,
# configured entirely through environment variables (no vendor coupling)
export PODCAST_CTL_EMBED_BASE_URL="https://api.example.com/v1"
export PODCAST_CTL_EMBED_API_KEY="..."
export PODCAST_CTL_EMBED_MODEL="text-embedding-x"
podcast-ctl kb embed --provider openai-compatible --reindex
```

Provider independence is enforced, not aspirational:

- **Local by default.** The default backend is sentence-transformers with
  `BAAI/bge-m3` (strong multilingual retrieval, including Spanish). No
  per-query cost; transcripts never leave your machine.
- **Cloud only as an adapter.** The `openai-compatible` provider is a thin
  HTTP adapter over `httpx` (already a dependency) configured via env vars —
  point it at OpenAI, a compatible gateway, or a self-hosted server. Nothing
  in the KB depends on a specific vendor.
- **Recorded provenance.** Every vector stores the model name, backend
  version, and dimensions that produced it; the index also records the
  provider identity (`provider:model@version`) in `kb_meta`.
- **Detectable reindex.** Searching or embedding with a provider that does
  not match the indexed identity refuses to mix incompatible vectors:
  `kb embed --reindex` drops the old vectors and rebuilds from the unchanged
  raw snapshots and chunks — a reproducible reindex. (`kb search --mode auto`
  degrades to lexical with a warning instead of failing.)
- **Portable storage.** Vectors live as float32 BLOBs in `kb.sqlite` and are
  compared with an in-process cosine over unit-normalized vectors — no
  native SQLite extension to load, so the index file stays portable across
  machines. At KB scale the scan is milliseconds; adopting an ANN extension
  (e.g. sqlite-vec) later would be a pure performance change that reuses the
  same stored vectors.

## End-to-end example: podcast → transcript → KB → LLM answer

### 1. Transcribe episodes (populates the cache)

```bash
podcast-ctl transcribe "https://feeds.example.com/my-show"
```

Repeat for every show you want in the KB. Transcripts land in the local
catalog cache (SQLite) — that cache is what `kb build` reads.

### 2. Build the knowledge base

```bash
podcast-ctl kb build
```

This writes the raw snapshots, the per-episode Markdown files, `INDEX.md`,
and the chunk index. Re-running it is cheap: unchanged episodes are skipped.

### 3. Browse or search

Open `INDEX.md` for the catalog, jump into any episode Markdown, or ask a
question:

```bash
podcast-ctl kb search "what did they say about vector databases" --limit 5
```

Every hit cites `[Episode @ mm:ss]`, so you can jump back to the source audio.

### 4. Ask an LLM with the retrieved chunks

The KB never talks to an AI provider itself — it emits plain Markdown/JSON,
and **you** (or a small script) hand the chunks to whatever model you like.

#### Option A — fully local with Ollama

With [Ollama](https://ollama.com) installed and a model pulled
(`ollama pull qwen3`), glue search and prompt together with any language —
here in Python, no extra dependencies:

```python
import json, subprocess, urllib.request

question = "What did they say about vector databases?"
hits = json.loads(subprocess.run(
    ["podcast-ctl", "kb", "search", question, "--json", "--limit", "5"],
    capture_output=True, text=True, check=True).stdout)

context = "\n\n".join(f"{h['citation']}\n{h['text']}" for h in hits)
prompt = (
    "Answer the question using ONLY the context below. "
    "Cite sources as [Episode @ mm:ss]. If the context does not answer it, say so.\n\n"
    f"Context:\n{context}\n\nQuestion: {question}"
)

req = urllib.request.Request(
    "http://localhost:11434/api/generate",
    data=json.dumps({"model": "qwen3", "prompt": prompt, "stream": False}).encode(),
    headers={"Content-Type": "application/json"},
)
print(json.loads(urllib.request.urlopen(req).read())["response"])
```

Everything stays on your machine: transcripts, index, chunks, and the model.

#### Option B — any cloud provider (ChatGPT, Gemini, Claude, Z.ai, ...)

```bash
podcast-ctl kb search "what did they say about vector databases" --context
```

Copy the printed Markdown blocks into the chat of your choice, with a short
instruction like *"Answer using only this context and cite [Episode @ mm:ss]"*.
The same blocks work unchanged against any chat completion API — the KB
output carries no provider-specific coupling.

#### Option C — NotebookLM

NotebookLM uses a similar retrieve-then-answer approach internally, but it
does its **own** indexing: it cannot ingest `kb.sqlite`, the FTS5 index, or
chunk IDs. What it **can** ingest as sources
([Google's current list](https://support.google.com/gemininotebook/answer/16215270),
checked 2026-09-10) includes exactly what phase 2a produces:

- **Markdown files (`.md`)** — upload `kb/episodes/<show>/*.md` directly as
  sources. Timestamps (`**Speaker** (mm:ss)`) survive as plain text, so
  NotebookLM answers can still point at moments in the episode.
- **Audio files** (MP3/M4A/WAV, ...) — NotebookLM transcribes them at import
  time itself (you would lose our tier pipeline and turn timestamps).
- **Pasted text, web URLs, YouTube URLs, PDF, DOCX, TXT, CSV, PPTX, ePub,**
  Google Docs/Slides/Sheets, images.

Current limits to plan around (same source):

- Up to **500,000 words or 200 MB per source**.
- Up to **50 sources per notebook on the free tier** — with many episodes,
  concatenate several `episodes/*.md` into one larger `.md` per show or
  topic before uploading.
- Programmatic ingestion is **not** available in the consumer web app; an
  official API exists only for the paid *Gemini Notebook Enterprise* edition
  on Google Cloud
  ([docs](https://docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/api-notebooks)).

So the NotebookLM-compatible flow is: `kb build` → upload the per-episode
Markdown (optionally merged) as sources → ask questions inside NotebookLM.

#### Option D — an AI agent with shell access

Desktop AI agents (Codex, Claude Code, Hermes, ...) don't need you to copy
chunks around: point them at the repository and they can run the CLI
themselves — `kb build` to index, `kb search --json` to retrieve only the
relevant chunks with their citations, however large the KB grows. The repo
ships an agent guide for exactly this: [AGENTS.md](../AGENTS.md), also exposed
as a skill at `skills/podcast-clt/SKILL.md`. Retrieval stays deterministic
and provider-agnostic; which model the agent uses remains your choice.

## Reproducible offline demo

No network, API keys, or models needed — the script seeds two synthetic
episodes, builds a KB in a temp directory, and runs a search end to end:

```bash
uv run python examples/kb_quickstart.py
```

Add `--ollama qwen3` to also send the retrieved chunks to a local Ollama
model (requires `ollama serve` running and the model pulled).

## Rebuilds, idempotency, and provenance

- `kb build` compares a content hash of each cached transcript plus the
  pipeline version (`pipeline_version` in frontmatter and `kb_meta`);
  unchanged episodes are skipped, changed ones re-derive only their own
  artifacts and index rows, and episodes deleted from the cache are pruned.
- Chunk IDs are stable content hashes: unchanged episodes keep identical
  chunk IDs across rebuilds.
- Every chunk records show/episode, chapter, start/end timestamps, and the
  raw segment range it came from — full traceability back to the raw audio.
- The `embeddings` table stores model name, backend version, and
  dimensions per vector, and `kb_meta` records the provider identity — a
  provider or model switch triggers a clean, detectable reindex instead of
  silently mixing incompatible vectors (see "Embeddings and hybrid search").

## Configuration

| Variable | Description | Default |
| :--- | :--- | :--- |
| `PODCAST_CTL_KB_DIR` | Knowledge base root directory. | `kb/` next to the catalog DB, or `~/.local/share/podcast-ctl/kb` |
| `PODCAST_CTL_DB_PATH` | Catalog DB the KB reads transcripts from. | `~/.local/share/podcast-ctl/podcast_ctl.db` |
| `PODCAST_CTL_EMBED_MODEL` | Embedding model for the local provider, or the model name the cloud adapter sends. | `BAAI/bge-m3` |
| `PODCAST_CTL_EMBED_BASE_URL` | Base URL of an OpenAI-compatible embeddings API (cloud adapter). | — |
| `PODCAST_CTL_EMBED_API_KEY` | API key for the cloud adapter. | — |
