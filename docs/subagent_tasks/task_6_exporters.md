# Task 6: Multi-Format Exporters

## Objective
Implement modular exporters to generate clean output formats from normalized `TranscriptResult`: Markdown (timestamped with frontmatter metadata), continuous Prose (`.txt`), standard Subtitles (`.srt`, `.vtt`), and structured Intermediate JSON (`.json`).

## Context & Requirements
- **Markdown Exporter (`src/podcast_ctl/exporters/markdown.py`):**
  - YAML frontmatter with title, show, duration, publish date, source tier.
  - Formatted timestamped blocks: `**[00:14:23]** Speaker: Text` or `[00:14:23] Text`.
  - Group segments by natural speech breaks / time intervals.
- **Prose Exporter (`src/podcast_ctl/exporters/prose.py`):**
  - Continuous reading paragraphs without timecodes.
  - Sentence boundary smoothing (joining split segments, paragraph breaks after pauses > 3s or speaker changes).
- **Subtitle Exporters (`src/podcast_ctl/exporters/subtitles.py`):**
  - Standard compliant SRT (`00:00:01,000 --> 00:00:04,500`) and WebVTT (`00:00:01.000 --> 00:00:04.500`).
- **JSON Exporter (`src/podcast_ctl/exporters/json_exporter.py`):**
  - Full structured JSON dump for downstream processing or programmatic use.
- **Export Coordinator (`src/podcast_ctl/exporters/manager.py`):**
  - Handles `--format [markdown|prose|srt|vtt|json|all|both]` and output directory templating (`./transcripts/{show_slug}/{episode_slug}.{ext}`).

## Target Files
- `src/podcast_ctl/exporters/__init__.py`
- `src/podcast_ctl/exporters/base.py`
- `src/podcast_ctl/exporters/markdown.py`
- `src/podcast_ctl/exporters/prose.py`
- `src/podcast_ctl/exporters/subtitles.py`
- `src/podcast_ctl/exporters/json_exporter.py`
- `src/podcast_ctl/exporters/manager.py`
- `tests/test_exporters.py`

## Verification & Acceptance Criteria
- Running `uv run pytest tests/test_exporters.py` passes 100%.
- Generated SRT and VTT conform to standard subtitle format specifications.
- Markdown frontmatter parses as valid YAML.
