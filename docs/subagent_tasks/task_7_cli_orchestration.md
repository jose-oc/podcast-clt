# Task 7: CLI Interface, Documentation & Integration

## Objective
Wire all modules into a cohesive Typer CLI interface with vibrant Rich output styling, comprehensive documentation, and end-to-end integration tests.

## Context & Requirements
- **Typer Commands (`src/podcast_ctl/cli/`):**
  - `podcast-ctl search <query>`: Search Apple Podcasts / iTunes API, show results table, let user pick.
  - `podcast-ctl inspect <input>`: Inspect feed/video/file, run pre-flight gatekeeper analysis, print summary without transcribing.
  - `podcast-ctl transcribe <input>`:
    - Flags: `--episode <id/title/index>`, `--all`, `--latest <N>`, `--engine <auto|rss|youtube|whisper|groq>`, `--format <both|markdown|prose|srt|vtt|json|all>`, `--output-dir <path>`, `--yes` / `-y`, `--model-size <base|small|medium|large-v3>`.
  - `podcast-ctl mapping [list|add|remove]`: Manage learned Show $\leftrightarrow$ YouTube mappings.
  - `podcast-ctl cache [list|clean|stats]`: Manage SQLite cached transcripts.
- **Documentation (`docs/` & `README.md`):**
  - `README.md`: Quickstart, installation via `uv`, command examples, screenshots/rich UI preview.
  - `docs/ARCHITECTURE.md`: Pipeline architecture diagram, component overview, storage schema.
  - `docs/POST_PROCESSING_DESIGN.md`: Phase 2 LLM post-processing specification (Diarization, Chapters, Summarization, Ollama/LiteLLM).
  - `docs/CLI_REFERENCE.md`: Complete CLI flag and command reference.
- **Integration Tests:**
  - Mocked end-to-end test exercising discovery $\rightarrow$ gatekeeper $\rightarrow$ dispatcher $\rightarrow$ exporter.

## Target Files
- `src/podcast_ctl/cli/__init__.py`
- `src/podcast_ctl/cli/main.py`
- `src/podcast_ctl/cli/commands/transcribe.py`
- `src/podcast_ctl/cli/commands/inspect.py`
- `src/podcast_ctl/cli/commands/search.py`
- `src/podcast_ctl/cli/commands/mapping.py`
- `src/podcast_ctl/cli/commands/cache.py`
- `docs/ARCHITECTURE.md`
- `docs/POST_PROCESSING_DESIGN.md`
- `docs/CLI_REFERENCE.md`
- `README.md`
- `tests/test_cli.py`

## Verification & Acceptance Criteria
- Running `uv run pytest` passes all tests across all modules.
- Running `podcast-ctl --help` displays colored command documentation.
