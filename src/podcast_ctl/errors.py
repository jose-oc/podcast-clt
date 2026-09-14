"""User-facing error types and the debug-mode switch.

Expected failures (bad paths, missing databases, unreachable providers,
invalid configuration) raise :class:`PodcastCtlError`, which the CLI entry
point prints as a short, actionable message instead of a Python traceback.
The full traceback is always available behind ``--debug`` or the
``PODCAST_CTL_DEBUG`` environment variable, and is written to the log file.
"""

from __future__ import annotations

import os

_DEBUG = False

# Values of PODCAST_CTL_DEBUG that enable debug mode.
_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}


def set_debug(enabled: bool) -> None:
    """Enable or disable debug mode (full tracebacks on unexpected errors)."""
    global _DEBUG
    _DEBUG = enabled


def debug_enabled() -> bool:
    """Whether debug mode is on, via the ``--debug`` flag or ``PODCAST_CTL_DEBUG``."""
    if _DEBUG:
        return True
    return os.environ.get("PODCAST_CTL_DEBUG", "").strip().lower() in _TRUE_VALUES


class PodcastCtlError(Exception):
    """An expected, user-facing failure.

    ``message`` says what failed and why; the optional ``hint`` says how to
    fix it. The CLI entry point prints both without a traceback and exits
    with code 1.
    """

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
