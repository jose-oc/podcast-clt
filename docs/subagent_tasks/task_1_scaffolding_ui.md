# Task 1: Project Scaffolding & Rich UI Console

## Objective
Initialize the project structure with `uv`, configure `pyproject.toml` with dependencies and CLI entrypoints, and implement a centralized Rich console module that handles all colored, styled output to stdout and stderr.

## Context & Requirements
- Python 3.11+ using `uv`.
- Rich console setup:
  - Cyan / Blue for informational banners and progress status.
  - Green for success confirmations and saved paths.
  - Yellow for warnings and fallback notifications.
  - Red / Bright Red on stderr for errors and exceptions (enclosed in styled Rich Panels).
  - Magenta / Bold for interactive highlights.
- Provide helper methods: `console.info()`, `console.success()`, `console.warning()`, `console.error()`, `console.panel()`, `console.table()`, `console.status_spinner()`.
- Set up unit testing scaffold with `pytest`.

## Target Files
- `pyproject.toml`
- `src/podcast_ctl/__init__.py`
- `src/podcast_ctl/ui/__init__.py`
- `src/podcast_ctl/ui/console.py`
- `src/podcast_ctl/ui/theme.py`
- `tests/__init__.py`
- `tests/test_console.py`

## Verification & Acceptance Criteria
- Running `uv run pytest tests/test_console.py` must pass 100%.
- Terminal output to stderr uses proper error styling.
- `console.info`, `console.success`, etc., produce expected formatted text on captured console output.
