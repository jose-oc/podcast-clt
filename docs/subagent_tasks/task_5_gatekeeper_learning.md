# Task 5: Pre-Flight Gatekeeper & Interactive Learning

## Objective
Implement the pre-flight inspection gate and interactive human-in-the-loop decision system that prompts users for YouTube video candidate validation and cloud expenditure permissions, persisting confirmed knowledge in SQLite for future automatic runs.

## Context & Requirements
- **Pre-Flight Inspector (`src/podcast_ctl/gatekeeper/inspector.py`):**
  - Summarizes batch workload: total episodes, total hours/minutes, estimated cache footprint, and tier availability (e.g. `2 available via RSS, 3 via YouTube, 5 require Local Whisper`).
- **Interactive Prompts (`src/podcast_ctl/gatekeeper/prompts.py`):**
  - **YouTube Validation Prompt:** When a podcast episode has no known YouTube mapping but YouTube search finds a candidate:
    - Display candidate title, channel, video length, confidence score.
    - Ask: `Use this YouTube video for captions? [Y/n/custom url/skip]`.
  - **Cloud Cost Guardrail Prompt:** When falling back to paid cloud API (Groq/OpenAI):
    - Calculate estimated cost based on audio duration (e.g. `$0.006 / min`).
    - Ask: `Transcribe via Groq Whisper API (Est. cost: ~$0.03)? [y/N/always for this show]`.
  - **Pre-Flight Confirmation:** Display summary table and ask `Proceed? [Y/n]`. (Bypassed if `--yes` / `-y` or non-interactive TTY).
- **Knowledge Learning (`src/podcast_ctl/gatekeeper/learning.py`):**
  - Automatically persist user-confirmed Show $\leftrightarrow$ YouTube Channel and Episode $\leftrightarrow$ YouTube Video mappings to the SQLite knowledge repository.

## Target Files
- `src/podcast_ctl/gatekeeper/__init__.py`
- `src/podcast_ctl/gatekeeper/inspector.py`
- `src/podcast_ctl/gatekeeper/prompts.py`
- `src/podcast_ctl/gatekeeper/learning.py`
- `tests/test_gatekeeper.py`

## Verification & Acceptance Criteria
- Running `uv run pytest tests/test_gatekeeper.py` passes 100%.
- Interactive prompts return expected actions and persist approved mappings to the test database.
- Non-interactive mode (when `sys.stdin.isatty()` is False) falls back to safe defaults or honours `--yes`.
