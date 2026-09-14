# podcast-ctl CLI Command Reference

Comprehensive command-line reference and usage guide for `podcast-ctl`.

---

## Global Options

```bash
podcast-ctl [OPTIONS] COMMAND [ARGS]...
```

| Flag         | Short | Description                                         |
|:-------------|:------|:----------------------------------------------------|
| `--version`  | `-v`  | Display `podcast-ctl` version and exit.             |
| `--verbose`  |       | Enable verbose debug logging output on the console. |
| `--debug`   |       | Print full Python tracebacks on errors.             |
| `--log-file` |       | Custom log file path (see [Logging](#logging)).     |
| `--help`     |       | Show help message and exit.                         |

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
* `--guids`, `-g` *(bool, default: False)*: Also print a plain, copyable list of episode GUIDs and titles. The episode table shows a truncated **Episode GUID** column; use this flag to get full GUIDs for `mapping add episode`.

#### Examples
```bash
# Inspect an RSS feed
podcast-ctl inspect "https://cuonda.com/monos-estocasticos/feed"

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
* `--youtube-delay` *(float, default: 2.0)*: Base seconds to wait between YouTube subtitle requests, randomized +/-50% (so 2.0 waits 1-3s). Set to `0` to disable pacing.

**YouTube rate limiting.** YouTube throttles IPs that fetch many captions in a row (HTTP 429 / IP-blocked errors), so the `youtube` engine paces itself with `--youtube-delay` and, on the first 429, is disabled for the rest of the batch instead of being retried episode by episode (which is what prolongs the block). The remaining episodes fall back to the other engines (e.g. local whisper), the batch summary reports the disabled engine, and re-running later resumes where it stopped because completed episodes are cached. Disablements and pacing waits are recorded in the [log file](#logging).

#### Examples
```bash
# Transcribe the latest episode of a show into Markdown and Text
podcast-ctl transcribe "https://cuonda.com/monos-estocasticos/feed"

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

`COMMAND` is what to manage: `list`, `add show|episode`, `remove show|episode`, or `sync`. The `add`/`remove` group help (`podcast-ctl mapping add --help`) shows copyable examples.

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

Without `--title`, the show title is resolved from the feed itself (needs network); if the feed cannot be fetched, the feed URL is stored as the title with a warning.

When a show has a channel mapping, transcription with the `youtube` engine (directly or via `auto`) works even without per-episode mappings: if no episode mapping matches, the channel's recent videos (up to 60) are searched for a title closely matching the episode title. Titles are normalized (lowercase, punctuation stripped) and compared by similarity ratio; a match is accepted at 0.75 or higher. Accepted matches are stored as auto-discovered (unconfirmed) episode mappings, so each episode is only searched once. If nothing matches, the error message reports how many videos were searched and the best similarity found.

The channel listing is cached for the duration of a batch run, so transcribing N episodes lists each channel only once (and a failed listing is not retried per episode). The fallback only sees the 60 most recent channel videos: for older episodes use `mapping sync` (below) or an explicit `mapping add episode`.

#### `mapping add episode`
Associate a specific podcast episode with a direct YouTube video URL.
```bash
podcast-ctl mapping add episode <show_id> <episode_id_or_title> <youtube_video_url>
```

* `<show_id>`: the show title exactly as it appears in the RSS feed (e.g. `"Huberman Lab"`) or the RSS feed URL.
* `<episode_id_or_title>`: the episode's **RSS GUID** or its exact title. A title is resolved to its GUID by fetching the feed (needs network); the transcription-time lookup is always `show title + GUID`, so a mapping stored under a raw title never matches.

Find an episode's GUID with `podcast-ctl inspect <show> --guids` (or the Episode GUID column in the inspect table, truncated in narrow terminals). If the feed cannot be fetched, the value is stored as provided with a warning, so explicit GUID mappings still work offline.

#### `mapping sync`
Match every episode of a show against its YouTube channel in one pass.
```bash
podcast-ctl mapping sync <show> [--channel <url>] [--threshold <0-1>] [--max-videos <n>] [--dry-run]
```

* `<show>`: the show title as in the RSS feed, an iTunes search term, or the RSS feed URL.
* `--channel`: YouTube channel URL. Defaults to the channel of the stored show mapping (`mapping add show`).
* `--threshold`: minimum normalized title similarity to accept a match (default: 0.75).
* `--max-videos`: search only the N most recent channel videos (default: the full channel catalog).
* `--dry-run`: report the matches without saving anything.

The feed and the channel catalog are each listed once and all titles are compared locally, so large back catalogs do not cost one request per episode. Accepted matches are stored as auto-discovered (unconfirmed) episode mappings; episodes that already have a mapping are left untouched. This is the way to make a whole back catalog transcribable with the `youtube` engine: the per-episode fallback during transcription only searches the 60 most recent channel videos.

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
* `--device auto|cpu|mps|cuda` (or `PODCAST_CTL_EMBED_DEVICE`) selects the
  torch device for the local backend; the device in use is printed.

#### `kb search`
Search the chunk index. Default mode is `auto`: hybrid retrieval (RRF k=60
over lexical BM25 + vector cosine) once embeddings exist, lexical before
that. Lexical matching is diacritics-insensitive (AND first, OR fallback).
```bash
podcast-ctl kb search <query> [--limit <N>] [--show <show_id>] [--mode auto|lexical|vector|hybrid] [--provider <name>] [--model <name>] [--json] [--context] [--kb-dir <path>]
```
* `--provider` is auto-detected by default: vector/hybrid searches use the
  provider identity recorded in the index by `kb embed`, so switching
  machines or shells never silently queries with the wrong model. Pass it
  explicitly to override (a mismatch with the index is refused).
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

## Logging

Every run appends INFO-level diagnostics (engine attempts, cache hits, channel searches, failures) to a rotating log file, so batch runs can be diagnosed afterwards:

* Default path: `~/.local/share/podcast-ctl/logs/podcast-ctl.log` (next to the SQLite catalog; honors `PODCAST_CTL_DB_PATH`).
* Rotation: 1 MB per file, 3 backups kept.
* Override the location with `--log-file <path>`; add `--verbose` to also see DEBUG output on the console.

---

## Error Messages

Expected failures (bad paths, missing databases, unreachable providers, invalid configuration) print a
short message saying what failed and how to fix it, and exit with code 1 - no Python traceback. Unexpected
errors print a one-line summary and write the full traceback to the log file (see [Logging](#logging)).

Pass `--debug` (or set `PODCAST_CTL_DEBUG=1`) to print the full traceback for unexpected errors when
troubleshooting. Expected errors keep their short message either way; their tracebacks are in the log file.

---

## Environment Variables

| Variable                     | Description                                                       | Default                                     |
|:-----------------------------|:------------------------------------------------------------------|:--------------------------------------------|
| `PODCAST_CTL_DB_PATH`        | Custom path to SQLite database file.                              | `~/.local/share/podcast-ctl/podcast_ctl.db` |
| `PODCAST_CTL_KB_DIR`         | Custom path to the knowledge base directory.                      | `kb/` next to the catalog DB                |
| `PODCAST_CTL_DEBUG`          | Print full Python tracebacks on errors (same as `--debug`).        | unset (friendly error messages)             |
| `PODCAST_CTL_EMBED_MODEL`    | KB embedding model (local provider default, or cloud model name). | `BAAI/bge-m3`                               |
| `PODCAST_CTL_EMBED_DEVICE`   | Device for the local embedding backend (auto, cpu, mps, cuda).    | `auto`                                      |
| `PODCAST_CTL_EMBED_BASE_URL` | Base URL of an OpenAI-compatible embeddings API.                  | None                                        |
| `PODCAST_CTL_EMBED_API_KEY`  | API key for the KB cloud embedding adapter.                       | None                                        |
| `GROQ_API_KEY`               | API key for Groq Cloud Whisper API.                               | None                                        |
| `OPENAI_API_KEY`             | API key for OpenAI Whisper API.                                   | None                                        |

---

## Exit Codes

| Code | Meaning                                                             |
|:-----|:--------------------------------------------------------------------|
| `0`  | Success / Normal exit / User cancelled gracefully.                  |
| `1`  | Error encountered (invalid arguments, transcription failure, etc.). |
