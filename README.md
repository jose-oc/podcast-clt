# podcast-ctl 🎙️

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![uv](https://img.shields.io/badge/managed_by-uv-261230.svg)](https://github.com/astral-sh/uv)

Fast, modular CLI to discover, inspect, and transcribe podcast episodes, YouTube shows, and local audio files using a smart 4-tier fallback hierarchy (**Direct RSS → YouTube Captions → Local Whisper → Cloud API**).

---

## Key Features

- 🔍 **Universal Source Resolution**: Pass an RSS URL, show title, YouTube video/channel link, or local `.mp3`/`.m4a`/`.wav` file.
- ⚡ **4-Tier Cost-Optimal Fallback Hierarchy**:
  1. **Tier 1 (Instant & Free)**: Podcasting 2.0 `<podcast:transcript>` official tags (SRT, VTT, JSON, HTML, Text).
  2. **Tier 2 (Instant & Free)**: YouTube subtitles extracted via video/channel mappings.
  3. **Tier 3 (Local & Private)**: Local `faster-whisper` (CTranslate2) on GPU/CPU with configurable model sizes.
  4. **Tier 4 (Cloud Speed)**: Groq / OpenAI Whisper APIs with interactive cost guardrails.
- 🛡️ **Gatekeeper & Workload Estimator**: Inspect feeds before running, preview total duration, estimated disk usage, and auto-resolved tiers.
- 🧠 **Persistent Knowledge Learning**: Learns and remembers confirmed Show $\leftrightarrow$ YouTube Channel mappings and episode associations in a local SQLite database (WAL mode).
- 📦 **Multi-Format Exporters**: Output to styled **Markdown** with YAML frontmatter, clean readable **Prose**, **SubRip (.srt)**, **WebVTT (.vtt)**, and structured **JSON**.
- 🎨 **Rich Terminal UI**: Vibrant tables, progress spinners, interactive selection menus, and clear visual hierarchy.

---

## Installation

Using [`uv`](https://github.com/astral-sh/uv) (recommended):

```bash
# Clone the repository
git clone https://github.com/jose-oc/podcast-ctl.git
cd podcast-ctl

# Run directly with uv
uv run podcast-ctl --help
```

Or install in editable mode:
```bash
uv pip install -e .
```

---

## Quickstart

### 1. Discover Shows
Search Apple Podcasts / iTunes directory directly from your terminal:
```bash
podcast-ctl search "Latent Space"
```

### 2. Inspect a Feed (Pre-Flight Analysis)
Preview episodes, duration, cache storage requirements, and tier resolutions without transcribing:
```bash
podcast-ctl inspect "https://feeds.simplecast.com/82GLSDrl"
```

### 3. Transcribe Episodes
Transcribe the latest episode to Markdown (`.md`) and plain text (`.txt`):
```bash
podcast-ctl transcribe "https://feeds.simplecast.com/82GLSDrl"
```

Transcribe a specific episode using local Whisper `small` model:
```bash
podcast-ctl transcribe "Latent Space" -e "Ilya Sutskever" --model-size small
```

Transcribe a local recording to all formats:
```bash
podcast-ctl transcribe ./meeting.m4a -o ./transcripts --format all
```

---

## CLI Overview

| Command | Usage | Description |
| :--- | :--- | :--- |
| `search` | `podcast-ctl search <query>` | Search Apple Podcasts catalog for shows and feeds. |
| `inspect` | `podcast-ctl inspect <input>` | Pre-flight inspection & tier breakdown without transcribing. |
| `transcribe` | `podcast-ctl transcribe <input>` | Transcribe episodes with multi-tier fallback and multi-format export. |
| `mapping` | `podcast-ctl mapping [list\|add\|remove]` | Manage learned Show $\leftrightarrow$ YouTube associations. |
| `cache` | `podcast-ctl cache [stats\|list\|clean]` | Inspect and manage SQLite database and transcript cache. |

For detailed documentation on flags, options, and advanced configurations, see the [CLI Reference](docs/CLI_REFERENCE.md).

---

## Architecture & Design

For deep dives into the system design, fallback logic, and database schemas, check out:
- [System Architecture](docs/ARCHITECTURE.md)
- [CLI Reference Guide](docs/CLI_REFERENCE.md)
- [Phase 2 AI Post-Processing Design](docs/POST_PROCESSING_DESIGN.md)

---

## License

MIT License © 2026 Jose OC
