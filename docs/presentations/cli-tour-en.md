---
marp: true
theme: default
paginate: true
size: 16:9
title: podcast-ctl — CLI Tour
description: Visual slide deck introducing the podcast-ctl CLI (English)
---

<style>
section {
  background: #0d1117;
  color: #e6edf3;
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  padding: 60px 70px;
  font-size: 30px;
  line-height: 1.45;
}
h1 { color: #58a6ff; font-size: 60px; letter-spacing: -1px; }
h2 { color: #58a6ff; font-size: 46px; margin-bottom: 18px; }
h3 { color: #7ee787; }
strong { color: #ffa657; }
code { background: #161b22; color: #7ee787; border-radius: 6px; padding: 2px 8px; }
pre { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 22px 26px; }
pre code { background: none; padding: 0; font-size: 26px; }
a { color: #58a6ff; }
table { font-size: 26px; background: transparent; }
th, td { background: #161b22; color: #e6edf3; }
th { background: #1c2530; }
th { color: #58a6ff; }
td, th { border-color: #30363d !important; }
section.lead { text-align: center; }
section.lead h1 { font-size: 84px; }
section.lead p { color: #9da7b3; font-size: 34px; }
section::after { color: #6e7681; font-size: 20px; }
.flow { display: flex; align-items: stretch; gap: 12px; margin: 24px 0; }
.flow .step {
  flex: 1; background: #161b22; border: 2px solid #30363d; border-radius: 14px;
  padding: 18px 14px; text-align: center; font-size: 25px;
}
.flow .step b { display: block; color: #58a6ff; font-size: 28px; margin-bottom: 6px; }
.flow .arrow { align-self: center; color: #ffa657; font-size: 40px; }
.tier { border-left: 6px solid; border-radius: 10px; background: #161b22;
  padding: 12px 20px; margin: 10px 0; font-size: 26px; }
.tier b { font-size: 28px; }
.t1 { border-color: #7ee787; } .t1 b { color: #7ee787; }
.t2 { border-color: #58a6ff; } .t2 b { color: #58a6ff; }
.t3 { border-color: #d2a8ff; } .t3 b { color: #d2a8ff; }
.t4 { border-color: #ffa657; } .t4 b { color: #ffa657; }
.cols { display: flex; gap: 40px; }
.cols > div { flex: 1; }
.small { font-size: 24px; color: #9da7b3; }
.tag { display: inline-block; background: #1f6feb33; border: 1px solid #1f6feb;
  color: #58a6ff; border-radius: 999px; padding: 2px 16px; font-size: 22px; margin-right: 8px; }
</style>

<!-- _class: lead -->

# 🎙️ podcast-ctl

**Your podcasts, transcribed and searchable**

From episode audio to an LLM-ready knowledge base — with one CLI.

<!--
Talk track: this is the tool we're presenting. One sentence: it finds podcast
episodes, transcribes them as cheaply and privately as possible, and turns
them into a knowledge base you can query or feed to any LLM.
-->

---

## The problem

- Great content is **locked inside audio** — hours of it
- No search, no quotes, no way to ask *"what did they say about X?"*
- Cloud transcription gets **expensive** fast
- Sending everything to a cloud API isn't great for **privacy** either

---

## What podcast-ctl does

<div class="flow">
  <div class="step"><b>🔍 Discover</b>Search the Apple Podcasts catalog</div>
  <div class="arrow">→</div>
  <div class="step"><b>Inspect</b>Pre-flight: workload & cost preview</div>
  <div class="arrow">→</div>
  <div class="step"><b>Transcribe</b>4-tier fallback, cheapest first</div>
  <div class="arrow">→</div>
  <div class="step"><b>Knowledge base</b>Markdown + full-text search</div>
  <div class="arrow">→</div>
  <div class="step"><b>Ask</b>Any LLM — local or cloud</div>
</div>

One input can be an **RSS feed**, a **show title**, a **YouTube link**, or a **local audio file**.

---

## Install & run

```bash
git clone https://github.com/jose-oc/podcast-ctl.git
cd podcast-ctl
uv run podcast-ctl --help
```

- Managed with **uv** — no manual environment setup
- Optional local Whisper tier: `uv sync --extra whisper`
- Cloud tiers need `GROQ_API_KEY` / `OPENAI_API_KEY`

---

## Six commands

| Command | What it does |
| :--- | :--- |
| `search` | Find shows in the Apple Podcasts catalog |
| `inspect` | Pre-flight analysis — before spending anything |
| `transcribe` | Transcribe episodes, videos, or local files |
| `mapping` | Teach show ↔ YouTube channel links |
| `cache` | Manage the local transcript cache |
| `kb` | Build & query the knowledge base |

---

## 1 · Discover

```bash
podcast-ctl search "Latent Space"
```

- Interactive picker from the Apple Podcasts / iTunes catalog
- Or skip discovery: pass a **feed URL**, **show title**, **YouTube URL** or **file path** straight to the other commands

<p class="small">podcast-ctl search "Huberman Lab" --limit 5 --no-interactive</p>

---

## 2 · Inspect: look before you leap

```bash
podcast-ctl inspect "https://feeds.simplecast.com/82GLSDrl"
```

The **gatekeeper** answers, *before* you transcribe anything:

- How many episodes, how much audio, how much disk
- Which **tier** each episode resolves to
- What it will cost — in time and money

---

## 3 · Transcribe

```bash
# Latest episode of a show
podcast-ctl transcribe "Latent Space"

# A specific episode, fully local
podcast-ctl transcribe "Latent Space" -e "Ilya Sutskever" --model-size small

# A local recording, all formats
podcast-ctl transcribe ./meeting.m4a -o ./notes --format all
```

`-e` matches the **published episode number**, a title substring, an ID — or `-e 1` for the newest.

---

## Pick exactly the episodes you want

```bash
podcast-ctl transcribe "Marketing Online" --episodes 2890,2894,2901
podcast-ctl transcribe "Marketing Online" --episodes 2890..2900
podcast-ctl transcribe "Marketing Online" --match "Kubernetes|Talos"
podcast-ctl transcribe "Marketing Online" --since 2026-01-01 --until 2026-03-31
podcast-ctl transcribe "Marketing Online" --pick
```

- Filters **compose** (AND): `--episodes 2800..2900 --match "SEO"`
- Every selection shows a **confirmation table** — number, date, title, duration — *before* anything is transcribed

---

## The heart: a 4-tier fallback

<div class="tier t1"><b>Tier 1 · RSS transcript tags</b> — official Podcasting 2.0 transcripts. Instant & free.</div>
<div class="tier t2"><b>Tier 2 · YouTube captions</b> — via learned show ↔ channel mappings. Instant & free.</div>
<div class="tier t3"><b>Tier 3 · Local Whisper</b> — faster-whisper on your GPU/CPU. Private & free.</div>
<div class="tier t4"><b>Tier 4 · Cloud APIs</b> — Groq / OpenAI Whisper. Fast, with interactive cost guardrails.</div>

**Cheapest and most private source wins — automatically.** Finished transcripts are cached in SQLite, so you never pay twice.

---

## Output formats for every use

```bash
podcast-ctl transcribe "Hardcore History" --latest 3 --format all --yes
```

<div class="cols">
<div>

- **Markdown** — styled, YAML frontmatter
- **Prose** — clean readable `.txt`
- **SRT / VTT** — subtitle files

</div>
<div>

- **JSON** — structured data
- `--format both` (default): `.md` + `.txt`
- Mix your own: `--format markdown,srt,json`

</div>
</div>

---

## Cache & mappings: it learns

<div class="cols">
<div>

### `cache`
```bash
podcast-ctl cache stats
podcast-ctl cache list
podcast-ctl cache clean --yes
```
Every transcript is stored locally — re-runs are instant.

</div>
<div>

### `mapping`
```bash
podcast-ctl mapping list
podcast-ctl mapping add show <feed_url> <youtube_channel_url>
```
Linking a show to its YouTube channel unlocks **free Tier 2 captions**.

</div>
</div>

---

## 4 · Build the knowledge base

```bash
podcast-ctl kb build
```

```
kb/
  raw/<show>/<episode>.json      # write-once source snapshots
  episodes/<show>/<episode>.md   # clean per-episode Markdown
  INDEX.md                       # browsable catalog
  db/kb.sqlite                   # chunked FTS5 search index
```

**Incremental**: unchanged episodes are skipped. **Reproducible**: everything derives from `raw/` — delete and rebuild anytime.

---

## Search it — with citations

```bash
podcast-ctl kb search "vector databases" --limit 5
podcast-ctl kb search "búsqueda semántica" --context
podcast-ctl kb search "pricing" --json
```

- SQLite **FTS5 + BM25** ranking, case- and diacritics-insensitive
- Every hit cites **`[Episode @ mm:ss]`** — jump straight back to the audio
- `--context` prints Markdown blocks ready to paste into an LLM; `--json` is for scripts

---

## 5 · Ask an LLM — *your* LLM

The KB never locks you to a provider:

<div class="cols">
<div>

### 🏠 Fully local
`kb search --json` → pipe the chunks to **Ollama**. Nothing leaves your machine.

</div>
<div>

### ☁️ Any cloud chat
`kb search --context` → paste into ChatGPT, Claude, Gemini… unchanged.

</div>
<div>

### NotebookLM
Upload `episodes/*.md` as sources. Timestamps survive as plain text.

</div>
</div>

---

## 5b · The fourth path: an agent with a shell

Desktop AI agents (Codex, Claude Code, Hermes…) don't need copy-paste — they run the CLI themselves:

- The repo ships **`AGENTS.md`** and **`skills/podcast-clt/SKILL.md`**: plain Markdown that teaches any agent the commands
- The agent runs `kb search --json` and gets **only the relevant chunks**, with citations — no matter how big the KB grows
- Deterministic retrieval, **any provider**: the model stays your choice

```bash
podcast-ctl kb search "vector databases" --json --limit 5
```

<!--
Talk track: copy-paste and NotebookLM don't scale, and Ollama needs a script.
An agent with shell access runs the retrieval loop itself: search, read the
chunks, search again if the answer isn't there. AGENTS.md is the convention
most coding agents read when they enter a repo; the SKILL.md is the same
guide in skill format. Zero coupling — it's plain Markdown.
-->

---

## Design principles

<span class="tag">Cost first</span> <span class="tag">Privacy first</span> <span class="tag">Provider-agnostic</span>

- Always show the workload **before** asking to confirm
- Cheapest transcript source wins; cache prevents duplicate work
- Local Whisper and local LLMs keep everything on your machine
- Plain Markdown and JSON out — **no lock-in**, ever

---

<!-- _class: lead -->

# Try it

```bash
uv run podcast-ctl --help
```

**github.com/jose-oc/podcast-clt** · MIT License

Docs: `README.md` · `AGENTS.md` · `docs/CLI_REFERENCE.md` · `docs/KNOWLEDGE_BASE.md`

<!--
Talk track: clone it, transcribe one episode, build a KB, and ask it a
question. The quickstart takes minutes with uv.
-->
