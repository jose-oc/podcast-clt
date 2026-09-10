"""UI Theme and styling definitions for podcast-ctl."""

from rich.theme import Theme

# Theme color mappings
THEME_STYLES = {
    # Informational and banners (Cyan / Blue)
    "info": "cyan",
    "info.bold": "bold cyan",
    "banner": "bold blue",
    "progress": "cyan",
    "dim": "dim",
    
    # Success confirmations & saved paths (Green)
    "success": "green",
    "success.bold": "bold green",
    "path": "bold green",
    
    # Warnings & fallback notifications (Yellow)
    "warning": "yellow",
    "warning.bold": "bold yellow",
    "fallback": "yellow italic",
    
    # Errors & exceptions (Red / Bright Red)
    "error": "bold red",
    "error.bright": "bold bright_red",
    "error_panel": "bright_red",
    "critical": "bold white on red",
    
    # Interactive highlights & key UI accents (Magenta / Bold)
    "highlight": "bold magenta",
    "prompt": "magenta",
    "accent": "bold magenta",
    
    # Table headers and borders
    "table.header": "bold cyan",
    "table.border": "dim blue",
}

custom_theme = Theme(THEME_STYLES)
