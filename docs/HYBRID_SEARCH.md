# Hybrid Search, Explained

How `kb search` finds things, what the embeddings phase adds, and the design
choices behind it — in plain language, with commands you can run. For the
command reference see [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md); for the
rationale see [KNOWLEDGE_BASE_DESIGN.md](KNOWLEDGE_BASE_DESIGN.md).

## Two ways to find a needle

**Lexical search (what the KB started with).** `kb build` splits every
transcript into timestamped chunks and indexes them in SQLite FTS5 with BM25
ranking. It matches *literal words*: if you search `shoulder pain` and the
episode says "trapezius discomfort", it finds nothing — even when the episode
answers your question exactly.

**Semantic search (what `kb embed` adds).** An embedding model turns each
chunk into a vector — a numeric fingerprint of its *meaning*. Texts that talk
about the same thing get similar vectors, whatever words they use. With
embeddings, `shoulder pain` and "trapezius discomfort" land close together,
and the episode shows up.

```bash
# Literal words only (always available, zero setup)
podcast-ctl kb search "shoulder pain" --mode lexical

# Meaning only (needs embeddings)
podcast-ctl kb search "shoulder pain" --mode vector

# Both at once (recommended)
podcast-ctl kb search "shoulder pain" --mode hybrid
```

The default `--mode auto` uses hybrid once embeddings exist and plain lexical
before that, so the CLI just gets better after you embed — no flags needed.

## What `kb embed` does

```bash
uv sync --extra embeddings   # one-time: pulls sentence-transformers + torch
podcast-ctl kb embed         # embeds every chunk that doesn't have a vector yet
```

Like `kb build`, it is incremental and idempotent: only chunks without an
embedding are processed, so re-running it after new episodes is cheap. Every
stored vector records which backend, model, and version produced it; switching
model or provider requires `--reindex` so incompatible vectors never mix.

## Hybrid: why combining beats either alone

Lexical search is unbeatable for exact names, error codes, and rare terms.
Vector search is unbeatable for paraphrases and concepts. **Hybrid** runs both
and merges the two ranked lists with **Reciprocal Rank Fusion** (RRF, k=60) —
the standard, parameter-light way to combine rankings. Each retriever votes
with its ranks; chunks high on either list rise to the top. In the results
table, the Sources column shows which retriever(s) ranked each hit.

```
query ──► lexical (FTS5/BM25) ──► ranked list A ──┐
                                                  ├──► RRF fusion ──► results
query ──► vector (cosine) ──────► ranked list B ──┘
```

## Where the vectors come from

**Local, by default.** The default backend is
[`BAAI/bge-m3`](https://huggingface.co/BAAI/bge-m3) running through
sentence-transformers on your own machine. It is a strong multilingual
retrieval model (Spanish included), there is **no per-query cost**, and your
transcripts never leave the machine.

Costs to know about, all one-time or tiny:

- the optional `embeddings` extra pulls **torch** (the engine, a few hundred
  MB) and the **model itself (~2 GB)** downloads on first use;
- each chunk's vector is ~4 KB in `kb.sqlite` — thousands of chunks are a few
  MB.

Both the engine and the model are used only to *produce* vectors (chunks at
index time, your question at search time). Comparing vectors afterwards is
just arithmetic.

**Any provider, by env var.** An optional `openai-compatible` adapter points
at any OpenAI-style embeddings endpoint — OpenAI, a compatible gateway, or a
self-hosted server — configured entirely through environment variables, so no
vendor is baked into the knowledge base:

```bash
export PODCAST_CTL_EMBED_BASE_URL="https://api.example.com/v1"
export PODCAST_CTL_EMBED_API_KEY="..."
export PODCAST_CTL_EMBED_MODEL="text-embedding-x"
podcast-ctl kb embed --provider openai-compatible --reindex
```

## Why there is no vector database here

The vectors are stored as float32 **blobs in the same `kb.sqlite`** that
already holds the lexical index, and cosine similarity is computed in-process
over unit-normalized vectors (a dot product). Deliberately no vector database
and no native extension:

- **Exact, not approximate.** The in-process scan finds the *true* nearest
  chunks. Vector databases (Qdrant, pgvector, Pinecone, sqlite-vec) use
  approximate indexes like HNSW that trade a little recall for speed.
- **Fast enough at this scale.** For thousands of chunks the scan takes
  milliseconds. Vector databases start paying off at *millions* of vectors.
- **One less service.** No server to install, run, back up, and keep alive;
  the whole index stays a single portable SQLite file.

Vector databases are not obsolete — they solve a scale problem this project
does not have. If the KB ever grows into the millions of chunks, adopting an
ANN extension (e.g. sqlite-vec) is a pure performance change that can reuse
the same stored vectors.

## A complementary idea: a richer INDEX.md ("agentic retrieval")

There is a legitimate alternative to embeddings for finding the right
episodes: make `INDEX.md` richer — a short summary per episode and
timestamped topics (many podcasts publish chapters already; otherwise an LLM
can generate them) — and let an agent with shell access (Codex, Claude Code,
…, see [AGENTS.md](../AGENTS.md)) read the index, spot promising episodes, and
open the per-episode Markdown to answer. This pattern has a name: *agentic
retrieval*.

Its tradeoffs, honestly:

- **Strengths.** Zero extra infrastructure, instant orientation, and the
  agent reads only what it needs.
- **Weaknesses.** The rich index has to be generated and maintained (an LLM
  pass per new episode — cost and freshness), and a summary or label may not
  say "trapezius" even when the episode discusses your shoulder. Embeddings
  catch what labels miss.

The two compose well rather than compete: a curated index for coarse
navigation, embeddings for fine semantic recall. The KB's phases 2a–2c give
you both pieces — `INDEX.md` + per-episode Markdown for navigation, hybrid
search for recall — so you can compare them on your own corpus.

## Try it in two minutes

```bash
podcast-ctl kb build                                   # index your transcripts
uv sync --extra embeddings && podcast-ctl kb embed     # add meaning vectors
podcast-ctl kb search "dolor de hombro"                # finds "molestias en el trapecio"
podcast-ctl kb search "dolor de hombro" --mode lexical # same query, literal words only
```

Run the last two and compare — that difference is the whole point of this
document.
