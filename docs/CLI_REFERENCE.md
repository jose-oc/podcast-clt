# podcast-ctl CLI Command Reference

Comprehensive command-line reference and usage guide for `podcast-ctl`.

---

## Global Options

```bash
podcast-ctl [OPTIONS] COMMAND [ARGS]...
```

| Flag | Short | Description |
| :--- | :--- | :--- |
| `--version` | `-v` | Display `podcast-ctl` version and exit. |
| `--verbose` | | Enable verbose debug logging output. |
| `--help` | | Show help message and exit. |

---

## Commands

### 1. `search`

Search the Apple Podcasts / iTunes catalog for shows and feeds.

```bash
podcast-ctl search <query> [OPTIONS]
```

#### Arguments
* `<query>` *(required)*: Podcast title, topic, or host name to search.

#### Options
* `--limit`, `-n` *(int, default: 10)*: Maximum number of search results to display.
* `--interactive / --no-interactive` *(bool, default: true)*: Enable interactive selection menu after displaying results.

#### Examples
```bash
# Search for shows matching "Latent Space"
podcast-ctl search "Latent Space"

# Search with custom limit without interactive prompt
podcast-ctl search "Huberman Lab" --limit 5 --no-interactive
```

---

### 2. `inspect`

Inspect an RSS feed, show title, YouTube video, or local audio file. Performs pre-flight workload estimation and tier analysis without downloading or transcribing.

```bash
podcast-ctl inspect <input_source> [OPTIONS]
```

#### Arguments
* `<input_source>` *(required)*: RSS URL, show title / search term, YouTube URL, or local audio file path (`.mp3`, `.m4a`, `.wav`, etc.).

#### Options
* `--engine` *(string, default: "auto")*: Target transcription engine (`auto`, `rss`, `youtube`, `whisper`, `groq`, `openai`).
* `--limit`, `-n` *(int, default: 20)*: Maximum number of episodes to list in detailed table.

#### Examples
```bash
# Inspect an RSS feed
podcast-ctl inspect "https://feeds.simplecast.com/82GLSDrl"

# Inspect by show title (auto-resolves via iTunes search)
podcast-ctl inspect "All-In Podcast"

# Inspect a local audio recording
podcast-ctl inspect ~/Recordings/interview.mp3
```

---

### 3. `transcribe`

Transcribe podcast episodes, YouTube videos, or local audio files with multi-tier fallback and multi-format export.

```bash
podcast-ctl transcribe <input_source> [OPTIONS]
```

#### Arguments
* `<input_source>` *(required)*: Podcast RSS feed URL, Apple Podcasts search term, YouTube URL, or local audio file.

#### Options
* `--episode`, `-e` *(string, default: None)*: Target episode by:
  * Episode number (e.g. `-e 2894` selects the episode numbered 2894). Numeric filters match the feed-declared number (`itunes:episode`) first, then a leading number in the title (e.g. `2894. Title` or `#2894 - Title`).
  * 1-based positional index in feed order, newest first (e.g. `-e 1` for the most recent episode). Used only when no episode number matches.
  * Exact Episode ID / GUID (e.g. `-e 12345-abcde`)
  * Case-insensitive title substring (e.g. `-e "Sam Altman"`)

  The selected episode(s) - number, title, ID and publication date - are always shown before the confirmation prompt. `--episode` targets one exact episode and cannot be combined with the multi-select options below.
* `--episodes` *(string, default: None)*: Select multiple episodes by their own number (feed-declared number or leading number in the title - never the feed position). Accepts a comma-separated list and/or inclusive ranges:
  * `--episodes 2890,2894,2901` - a scattered list, transcribed in the given order.
  * `--episodes 2890..2900` - an inclusive range, transcribed in ascending numeric order.
  * `--episodes 2894,2890..2892` - lists and ranges can be mixed; duplicates are removed.
  * Numbers with no matching episode are reported as a warning; the command fails only if nothing matches.
* `--match` *(string, default: None)*: Select episodes whose title matches a case-insensitive regular expression (e.g. `--match "Kubernetes|Talos"`). Results are in feed order, newest first.
* `--since` *(string, default: None)*: Select episodes published on or after this date (`YYYY-MM-DD`).
* `--until` *(string, default: None)*: Select episodes published on or before this date (`YYYY-MM-DD`).
* `--pick` *(bool, default: False)*: Interactively pick episodes from a multi-select list showing number, title, date and duration. Requires an interactive terminal; long lists ask for a title filter first.

  The multi-select options compose as a logical AND: `--episodes 2890..2900 --match "SEO"` selects the SEO-titled episodes within that number range, and `--pick` narrows whatever the other filters selected. They cannot be combined with `--episode` or `--all`. Episodes without a parseable publication date are excluded (and reported) when a date filter is used. Every selection is shown - number, date, title and duration - before the confirmation prompt.
* `--latest`, `-l` *(int, default: 1)*: Transcribe latest N episodes (ignored when `--all`, `--episode` or any multi-select option is specified).
* `--all`, `-a` *(bool, default: False)*: Transcribe all available episodes in the feed.
* `--engine` *(string, default: "auto")*: Transcription engine strategy (`auto`, `rss`, `youtube`, `whisper`, `groq`, `openai`).
* `--model-size` *(string, default: "base")*: Faster-Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`).
* `--format`, `-f` *(string, default: "both")*: Output formats:
  * `both`: Markdown (`.md`) and Prose (`.txt`)
  * `all`: Markdown (`.md`), Prose (`.txt`), SRT (`.srt`), VTT (`.vtt`), JSON (`.json`)
  * Individual: `markdown`, `prose`, `srt`, `vtt`, `json`
  * Comma-separated: `markdown,srt,json`
* `--output-dir`, `-o` *(path, default: "./transcripts")*: Destination directory for exported files.
* `--yes`, `-y` *(bool, default: False)*: Auto-confirm pre-flight inspection and guardrail prompts.
* `--force` *(bool, default: False)*: Force re-transcription bypassing SQLite cache.
* `--keep-audio` *(bool, default: False)*: Preserve downloaded audio files in the cache.

#### Examples
```bash
# Transcribe the latest episode of a show into Markdown and Text
podcast-ctl transcribe "https://feeds.simplecast.com/82GLSDrl"

# Transcribe specific episode by title search using small Whisper model
podcast-ctl transcribe "Latent Space" -e "Ilya Sutskever" --model-size small

# Transcribe latest 3 episodes and export all formats without interactive prompts
podcast-ctl transcribe "Hardcore History" --latest 3 --format all --yes

# Transcribe a scattered list of episodes by number
podcast-ctl transcribe "Marketing Online" --episodes 2890,2894,2901

# Transcribe a consecutive range of episodes by number
podcast-ctl transcribe "Marketing Online" --episodes 2890..2900

# Transcribe every episode whose title matches a pattern
podcast-ctl transcribe "Marketing Online" --match "Kubernetes|Talos"

# Transcribe episodes published within a date range
podcast-ctl transcribe "Marketing Online" --since 2026-01-01 --until 2026-03-31

# Combine filters (AND) and/or pick episodes interactively
podcast-ctl transcribe "Marketing Online" --episodes 2800..2900 --match "SEO"
podcast-ctl transcribe "Marketing Online" --match "SEO" --pick

# Transcribe a local audio recording directly
podcast-ctl transcribe ./meeting.m4a -o ./notes -f markdown

# Transcribe a YouTube video
podcast-ctl transcribe "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

---

### 4. `mapping`

Manage learned Show $\leftrightarrow$ YouTube Channel and Episode $\leftrightarrow$ YouTube Video associations.

```bash
podcast-ctl mapping COMMAND [OPTIONS]
```

#### Subcommands

#### `mapping list`
List all stored mappings in formatted tables.
```bash
podcast-ctl mapping list [--show <show_id>]
```

#### `mapping add show`
Associate a podcast RSS feed with a YouTube channel.
```bash
podcast-ctl mapping add show <feed_url> <youtube_channel_url> [--title <title>]
```

#### `mapping add episode`
Associate a specific podcast episode with a direct YouTube video URL.
```bash
podcast-ctl mapping add episode <show_id> <episode_id> <youtube_video_url>
```

#### `mapping remove show`
Delete a Show $\leftrightarrow$ YouTube Channel mapping.
```bash
podcast-ctl mapping remove show <feed_url>
```

#### `mapping remove episode`
Delete an Episode $\leftrightarrow$ YouTube Video mapping.
```bash
podcast-ctl mapping remove episode <show_id> <episode_id>
```

---

### 5. `cache`

Inspect, list, and manage SQLite cached transcripts and storage.

```bash
podcast-ctl cache COMMAND [OPTIONS]
```

#### Subcommands

#### `cache stats`
Display database path, disk usage, and entity counts.
```bash
podcast-ctl cache stats
```

#### `cache list`
List stored transcripts in cache.
```bash
podcast-ctl cache list [--show <show_id>] [--limit <N>]
```

#### `cache clean`
Clear cached transcripts from SQLite.
```bash
podcast-ctl cache clean [--show <show_id>] [--yes]
```

### 6. `kb`

Build and query the knowledge base (KB) derived from cached transcripts:
per-episode Markdown, an `INDEX.md` catalog, and a chunked FTS5 search index
with `[Episode @ mm:ss]` citations. See the
[Knowledge Base Guide](KNOWLEDGE_BASE.md) for the full end-to-end flow.

AI agents with shell access can drive these commands directly — `kb search
--json` is the machine-readable interface. The full agent guide lives in
[AGENTS.md](../AGENTS.md) (also shipped as `skills/podcast-clt/SKILL.md`).

#### `kb build`
Build (or incrementally update) the KB from cached transcripts.
```bash
podcast-ctl kb build [--show <show_id>] [--kb-dir <path>]
```
Unchanged episodes are skipped; episodes removed from the cache are pruned.

#### `kb embed`
Embed indexed chunks for vector/hybrid search (phase 2c). Incremental and
idempotent; every vector records model/version/dimension provenance.
```bash
podcast-ctl kb embed [--provider local|openai-compatible] [--model <name>] [--show <show_id>] [--reindex] [--batch-size <N>] [--kb-dir <path>]
```
* Default backend is local sentence-transformers (`BAAI/bge-m3`), installed
  via the optional `podcast-ctl[embeddings]` extra.
* `openai-compatible` is a thin cloud adapter configured through
  `PODCAST_CTL_EMBED_BASE_URL` / `PODCAST_CTL_EMBED_API_KEY` /
  `PODCAST_CTL_EMBED_MODEL`.
* `--reindex` is required when switching providers/models: stored vectors
  from an incompatible model are dropped and rebuilt, never mixed.

#### `kb search`
Search the chunk index. Default mode is `auto`: hybrid retrieval (RRF k=60
over lexical BM25 + vector cosine) once embeddings exist, lexical before
that. Lexical matching is diacritics-insensitive (AND first, OR fallback).
```bash
podcast-ctl kb search <query> [--limit <N>] [--show <show_id>] [--mode auto|lexical|vector|hybrid] [--provider <name>] [--model <name>] [--json] [--context] [--kb-dir <path>]
```
* `--json`: machine-readable chunks for scripting (adds `mode`, `sources`,
  `bm25`, `cosine` fields for vector/hybrid results).
* `--context`: full chunks as Markdown blocks, ready to paste into an LLM.

#### `kb status`
Show KB location, size, and index statistics.
```bash
podcast-ctl kb status [--kb-dir <path>]
```

---

---

## Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `PODCAST_CTL_DB_PATH` | Custom path to SQLite database file. | `~/.local/share/podcast-ctl/podcast_ctl.db` |
| `PODCAST_CTL_KB_DIR` | Custom path to the knowledge base directory. | `kb/` next to the catalog DB |
| `PODCAST_CTL_EMBED_MODEL` | KB embedding model (local provider default, or cloud model name). | `BAAI/bge-m3` |
| `PODCAST_CTL_EMBED_BASE_URL` | Base URL of an OpenAI-compatible embeddings API. | None |
| `PODCAST_CTL_EMBED_API_KEY` | API key for the KB cloud embedding adapter. | None |
| `GROQ_API_KEY` | API key for Groq Cloud Whisper API. | None |
| `OPENAI_API_KEY` | API key for OpenAI Whisper API. | None |

---

## Exit Codes

| Code | Meaning |
| :--- | :--- |
| `0` | Success / Normal exit / User cancelled gracefully. |
| `1` | Error encountered (invalid arguments, transcription failure, etc.). |
