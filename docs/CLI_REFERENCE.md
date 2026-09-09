# podcast-cli CLI Command Reference

Comprehensive command-line reference and usage guide for `podcast-cli`.

---

## Global Options

```bash
podcast-cli [OPTIONS] COMMAND [ARGS]...
```

| Flag | Short | Description |
| :--- | :--- | :--- |
| `--version` | `-v` | Display `podcast-cli` version and exit. |
| `--verbose` | | Enable verbose debug logging output. |
| `--help` | | Show help message and exit. |

---

## Commands

### 1. `search`

Search the Apple Podcasts / iTunes catalog for shows and feeds.

```bash
podcast-cli search <query> [OPTIONS]
```

#### Arguments
* `<query>` *(required)*: Podcast title, topic, or host name to search.

#### Options
* `--limit`, `-n` *(int, default: 10)*: Maximum number of search results to display.
* `--interactive / --no-interactive` *(bool, default: true)*: Enable interactive selection menu after displaying results.

#### Examples
```bash
# Search for shows matching "Latent Space"
podcast-cli search "Latent Space"

# Search with custom limit without interactive prompt
podcast-cli search "Huberman Lab" --limit 5 --no-interactive
```

---

### 2. `inspect`

Inspect an RSS feed, show title, YouTube video, or local audio file. Performs pre-flight workload estimation and tier analysis without downloading or transcribing.

```bash
podcast-cli inspect <input_source> [OPTIONS]
```

#### Arguments
* `<input_source>` *(required)*: RSS URL, show title / search term, YouTube URL, or local audio file path (`.mp3`, `.m4a`, `.wav`, etc.).

#### Options
* `--engine` *(string, default: "auto")*: Target transcription engine (`auto`, `rss`, `youtube`, `whisper`, `groq`, `openai`).
* `--limit`, `-n` *(int, default: 20)*: Maximum number of episodes to list in detailed table.

#### Examples
```bash
# Inspect an RSS feed
podcast-cli inspect "https://feeds.simplecast.com/82GLSDrl"

# Inspect by show title (auto-resolves via iTunes search)
podcast-cli inspect "All-In Podcast"

# Inspect a local audio recording
podcast-cli inspect ~/Recordings/interview.mp3
```

---

### 3. `transcribe`

Transcribe podcast episodes, YouTube videos, or local audio files with multi-tier fallback and multi-format export.

```bash
podcast-cli transcribe <input_source> [OPTIONS]
```

#### Arguments
* `<input_source>` *(required)*: Podcast RSS feed URL, Apple Podcasts search term, YouTube URL, or local audio file.

#### Options
* `--episode`, `-e` *(string, default: None)*: Target episode by:
  * 1-based index (e.g. `-e 1` for most recent episode)
  * Exact Episode ID / GUID (e.g. `-e 12345-abcde`)
  * Case-insensitive title substring (e.g. `-e "Sam Altman"`)
* `--latest`, `-l` *(int, default: 1)*: Transcribe latest N episodes (applied if `--all` or `--episode` is not specified).
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
podcast-cli transcribe "https://feeds.simplecast.com/82GLSDrl"

# Transcribe specific episode by title search using small Whisper model
podcast-cli transcribe "Latent Space" -e "Ilya Sutskever" --model-size small

# Transcribe latest 3 episodes and export all formats without interactive prompts
podcast-cli transcribe "Hardcore History" --latest 3 --format all --yes

# Transcribe a local audio recording directly
podcast-cli transcribe ./meeting.m4a -o ./notes -f markdown

# Transcribe a YouTube video
podcast-cli transcribe "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

---

### 4. `mapping`

Manage learned Show $\leftrightarrow$ YouTube Channel and Episode $\leftrightarrow$ YouTube Video associations.

```bash
podcast-cli mapping COMMAND [OPTIONS]
```

#### Subcommands

#### `mapping list`
List all stored mappings in formatted tables.
```bash
podcast-cli mapping list [--show <show_id>]
```

#### `mapping add show`
Associate a podcast RSS feed with a YouTube channel.
```bash
podcast-cli mapping add show <feed_url> <youtube_channel_url> [--title <title>]
```

#### `mapping add episode`
Associate a specific podcast episode with a direct YouTube video URL.
```bash
podcast-cli mapping add episode <show_id> <episode_id> <youtube_video_url>
```

#### `mapping remove show`
Delete a Show $\leftrightarrow$ YouTube Channel mapping.
```bash
podcast-cli mapping remove show <feed_url>
```

#### `mapping remove episode`
Delete an Episode $\leftrightarrow$ YouTube Video mapping.
```bash
podcast-cli mapping remove episode <show_id> <episode_id>
```

---

### 5. `cache`

Inspect, list, and manage SQLite cached transcripts and storage.

```bash
podcast-cli cache COMMAND [OPTIONS]
```

#### Subcommands

#### `cache stats`
Display database path, disk usage, and entity counts.
```bash
podcast-cli cache stats
```

#### `cache list`
List stored transcripts in cache.
```bash
podcast-cli cache list [--show <show_id>] [--limit <N>]
```

#### `cache clean`
Clear cached transcripts from SQLite.
```bash
podcast-cli cache clean [--show <show_id>] [--yes]
```

---

## Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `PODCAST_CLI_DB_PATH` | Custom path to SQLite database file. | `~/.local/share/podcast-cli/podcast_cli.db` |
| `GROQ_API_KEY` | API key for Groq Cloud Whisper API. | None |
| `OPENAI_API_KEY` | API key for OpenAI Whisper API. | None |

---

## Exit Codes

| Code | Meaning |
| :--- | :--- |
| `0` | Success / Normal exit / User cancelled gracefully. |
| `1` | Error encountered (invalid arguments, transcription failure, etc.). |
