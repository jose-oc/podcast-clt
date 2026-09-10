# Phase 2 — Podcast Knowledge Base for LLM Retrieval

Design proposal (research + architecture, implementation pending).
Prepared 2026-09-10. Confirmed by Jose the same day.

## TL;DR

Keep raw transcriptions immutable, derive a clean per-episode Markdown, and
maintain an index — plus **retrieval-ready chunk indexes** (lexical + vector)
built from those Markdown files, with stable chunk IDs, timestamps, and
traceability back to the raw audio. A plain "MD per episode + one index file"
is good for browsing and for pasting into a chat, but an LLM retrieving
answers from 100+ hours of audio needs chunked, metadata-tagged, searchable
storage.

**Hard constraint (confirmed): the knowledge base must not be coupled to any
AI provider.** Local embeddings are the default; any hosted API is an
optional adapter behind a provider interface, and every derived artifact
records model/version/chunking metadata so the index can be rebuilt with a
different provider at any time.

## What current practice says (research summary)

- **Chunking is the highest-leverage decision.** A 1600-query 2026 evaluation
  found splitting on document structure (headers), semantically merging
  same-topic paragraphs, and prefixing every chunk with its title chain
  ([Show > Episode > Chapter]) lifted retrieval MRR@5 ~24% over naive
  splitting — with no extra LLM cost (arxiv.org/html/2608.00824v1).
  Anthropic's "Contextual Retrieval" does the same with an LLM-written
  context sentence per chunk; the header-chain version gets most of the gain
  for free.
- **Hybrid retrieval beats either alone.** BM25 nails exact matches (names,
  book titles, terms); embeddings nail paraphrase. Fusing with Reciprocal
  Rank Fusion (k=60) outperforms either alone; a cross-encoder rerank of the
  top ~100 adds more.
- **Working podcast-RAG systems converge on the same shape.** The closest
  public analogue (derek-rikke/podcast-search-rag) uses SQLite FTS5/BM25,
  speaker-aware chunks that never cross speaker turns, and answers cited as
  [Episode @ hh:mm:ss] — and its measured weak spot (completeness) is exactly
  what vector/hybrid search fixes. RAPTOR-style rollups (per-chunk leaves,
  episode summaries, topic index) help questions like "what do they keep
  saying about X" without full transcripts in context.
- **Transcript format:** Markdown with `**Speaker** (mm:ss)` turns survives
  chunking and gives free citations ("Speaker, around 12:34, says…").
  ~1000–1500 char chunks with 150–200 overlap is the common starting point.
- **Evaluation:** build a small golden query set from the corpus itself
  (facts, paraphrases, cross-episode, unanswerable) and track faithfulness +
  context recall (RAGAS-style) so every pipeline change is measured, not
  vibes.

## Provider independence (confirmed constraint)

The KB must stay usable and rebuildable regardless of which AI provider (if
any) produced its derived artifacts:

- **Local-first embeddings.** Default embedding backend runs locally (e.g.
  `sentence-transformers` with BGE-M3 or multilingual-e5 — both strong on
  Spanish). No per-query cost, no transcripts leaving the machine.
- **Provider interface.** Embedding/summarization backends sit behind a small
  interface (`embed(texts) -> vectors`, `summarize(text) -> str`). Local
  models are the default implementation; hosted APIs (OpenAI, Cohere, Voyage,
  …) are optional adapters, never required.
- **Recorded provenance.** Every chunk/vector/summary stores the model name,
  model version, and chunking/pipeline version that produced it. Switching
  providers or models triggers a clean, detectable reindex of the affected
  artifacts — not a silent mix of incompatible vectors.
- **Portable storage.** The index lives in a separate `kb.sqlite` inside the
  existing data directory (not coupled to the catalog DB); the Markdown layer
  is plain files. Both can be moved, rebuilt, or deleted independently.

## Proposed architecture (fits the existing repo)

Builds on what Phase 1 already has: SQLite (WAL) store, normalized
TranscriptResult JSON with timed segments, MD exporter with frontmatter, and
the Phase 2 post-processing design (cleanup, diarization, chaptering,
summaries).

```
kb/
  raw/<show-slug>/<episode-id>.json     # IMMUTABLE source of truth: segments, timestamps, engine, hash
  episodes/<show-slug>/<episode-id>.md  # derived per-episode document (below)
  INDEX.md                              # catalog: one row per episode (title, date, duration, 2-line summary)
  db/kb.sqlite                          # chunks + FTS5 + sqlite-vec embeddings (separate from the catalog DB)
```

### Per-episode Markdown format

```markdown
---
show: "Monos Estocásticos"
episode: "Ep 42 — Title"
date: 2026-09-01
duration_s: 3720
language: es
source_tier: rss | youtube | whisper | cloud
episode_url: https://...
content_hash: sha256:...
pipeline_version: 1
---

# Ep 42 — Title
> 2-line summary (from post-processing reduce step)

## 00:00 Intro
**Host** (00:03): text…
**Guest** (01:12): text…

## 14:32 Main topic
…
```

- YAML frontmatter: show, episode, date, duration, language, source tier,
  URL, content hash, pipeline version.
- Chapters (H2 + timestamp) come from the post-processing chaptering step;
  speaker turns stay as `**Name** (mm:ss)` so chunks carry attribution and
  timestamps survive into retrieval.

### Retrieval layer

- **Chunking:** split on chapter (H2) boundaries, never across speaker turns;
  merge short turns toward ~1000–1500 chars with small overlap; prefix every
  chunk with `[Show > Episode > Chapter]`. Stable chunk IDs =
  hash(show, episode, chapter, position, text) — re-running the pipeline
  never changes an unchanged chunk's ID.
- **Lexical:** SQLite FTS5 (BM25) over chunk text — exact matches (names,
  books, terms) work out of the box, zero new infra (the repo already runs
  SQLite).
- **Vector:** sqlite-vec (same KB database file) with one embedding per
  chunk; local model by default, provider-selected via the interface above.
- **Fusion:** RRF (k=60) over the two ranked lists; optional cross-encoder /
  LLM rerank of the top ~20 as a later toggle.
- **Traceability:** every chunk stores episode_id, chapter, start/end
  timestamps, and raw segment IDs — every answer can cite [Episode @ mm:ss]
  and jump back to the raw transcript.

### Update & idempotency

- Raw JSON is write-once, content-hashed; everything else derives from it.
- `kb build` is idempotent: unchanged episode → no-op; changed/new episode →
  re-derive MD, re-chunk, replace only that episode's index rows. Safe to run
  on a cron.

### Evaluation (built in from the start)

- Hand-label ~50 golden queries over the actual corpus: fact lookup,
  paraphrase, cross-episode synthesis, unanswerable (must refuse).
- Track retrieval MRR@5 plus RAGAS-style faithfulness/context recall on a
  fixed harness; every pipeline change re-runs it.

## Confirmed decisions (Jose, 2026-09-10)

1. **Interface:** CLI only at first (`kb build`, `kb search`); no web UI for
   now.
2. **Embeddings:** local by default; hosted APIs only as optional adapters
   (see "Provider independence").
3. **Storage:** separate `kb.sqlite` inside the project data directory —
   decoupled from the catalog DB, easy to move or rebuild.

## Incremental delivery plan

| Phase | Ships | Value |
|---|---|---|
| 2a | Post-processing → per-episode MD + INDEX.md | Browsable KB, paste-into-chat usable |
| 2b | `kb build` chunking + FTS5 lexical search | "What did they say about X?" with [Episode @ mm:ss] citations |
| 2c | sqlite-vec embeddings (local) + RRF hybrid | Paraphrase/concept queries work |
| 2d | Golden-query eval harness + CI regression gate | Changes are measured, not vibes |

Recommendation: implement 2a+2b together (they are small, and 2b is where the
KB becomes actually useful), then 2c, then 2d alongside.
