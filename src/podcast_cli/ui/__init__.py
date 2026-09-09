"""UI module for podcast-cli."""

from podcast_cli.ui.console import (
    UIConsole,
    console,
    error,
    info,
    panel,
    print,
    print_error,
    rule,
    status_spinner,
    success,
    table,
    warning,
)
from podcast_cli.ui.theme import THEME_STYLES, custom_theme

__all__ = [
    "UIConsole",
    "console",
    "custom_theme",
    "THEME_STYLES",
    "info",
    "success",
    "warning",
    "error",
    "panel",
    "table",
    "status_spinner",
    "print",
    "print_error",
    "rule",
]
