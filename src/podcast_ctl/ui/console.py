"""Centralized Rich console and UI helper module for podcast-ctl."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator, Sequence

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.status import Status
from rich.table import Table
from rich.text import Text

from podcast_ctl.ui.theme import custom_theme


class UIConsole:
    """Centralized Console wrapper managing stylized stdout and stderr output."""

    def __init__(
        self,
        stdout_console: Console | None = None,
        stderr_console: Console | None = None,
        record: bool = False,
        **kwargs: Any,
    ) -> None:
        self.stdout_console = stdout_console or Console(
            theme=custom_theme,
            record=record,
            **kwargs,
        )
        self.stderr_console = stderr_console or Console(
            stderr=True,
            theme=custom_theme,
            record=record,
            **kwargs,
        )

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Print to standard output."""
        self.stdout_console.print(*args, **kwargs)

    def print_error(self, *args: Any, **kwargs: Any) -> None:
        """Print to standard error."""
        self.stderr_console.print(*args, **kwargs)

    def info(
        self,
        message: RenderableType | Any,
        *,
        title: str | None = None,
        prefix: str = "ℹ ",
    ) -> None:
        """Print an informational message in cyan/blue."""
        if isinstance(message, str):
            prefix_styled = f"[bold cyan]{prefix}[/bold cyan]" if prefix else ""
            title_styled = f"[bold cyan]{title}:[/bold cyan] " if title else ""
            self.stdout_console.print(f"{prefix_styled}{title_styled}[cyan]{message}[/cyan]")
        else:
            if title:
                self.stdout_console.print(f"[bold cyan]{title}[/bold cyan]")
            self.stdout_console.print(message)

    def success(
        self,
        message: RenderableType | Any,
        *,
        title: str | None = None,
        prefix: str = "✔ ",
    ) -> None:
        """Print a success confirmation message in green."""
        if isinstance(message, str):
            prefix_styled = f"[bold green]{prefix}[/bold green]" if prefix else ""
            title_styled = f"[bold green]{title}:[/bold green] " if title else ""
            self.stdout_console.print(f"{prefix_styled}{title_styled}[green]{message}[/green]")
        else:
            if title:
                self.stdout_console.print(f"[bold green]{title}[/bold green]")
            self.stdout_console.print(message)

    def warning(
        self,
        message: RenderableType | Any,
        *,
        title: str | None = None,
        prefix: str = "⚠ ",
    ) -> None:
        """Print a warning or fallback notification message in yellow."""
        if isinstance(message, str):
            prefix_styled = f"[bold yellow]{prefix}[/bold yellow]" if prefix else ""
            title_styled = f"[bold yellow]{title}:[/bold yellow] " if title else ""
            self.stdout_console.print(f"{prefix_styled}{title_styled}[yellow]{message}[/yellow]")
        else:
            if title:
                self.stdout_console.print(f"[bold yellow]{title}[/bold yellow]")
            self.stdout_console.print(message)

    def error(
        self,
        message: RenderableType | Any,
        *,
        title: str = "Error",
        exception: Exception | None = None,
        panel: bool = True,
    ) -> None:
        """Print an error message to stderr in red/bright red, optionally wrapped in a Panel."""
        err_text: str | RenderableType
        if isinstance(message, str):
            msg_body = f"[bold red]{message}[/bold red]"
            if exception is not None:
                exc_detail = f"\n[dim red]{type(exception).__name__}: {exception}[/dim red]"
                msg_body += exc_detail
            err_text = msg_body
        elif isinstance(message, Exception):
            err_text = f"[bold red]{type(message).__name__}: {message}[/bold red]"
        else:
            err_text = message

        if panel:
            p = Panel(
                err_text,
                title=f"[bold bright_red]{title}[/bold bright_red]",
                title_align="left",
                border_style="bright_red",
                expand=False,
                padding=(0, 1),
            )
            self.stderr_console.print(p)
        else:
            prefix_styled = "[bold bright_red]✖ [/bold bright_red]"
            if isinstance(err_text, str):
                self.stderr_console.print(f"{prefix_styled}{err_text}")
            else:
                self.stderr_console.print(prefix_styled, err_text)

    def panel(
        self,
        renderable: RenderableType | Any,
        *,
        title: str | None = None,
        subtitle: str | None = None,
        border_style: str = "cyan",
        expand: bool = False,
        print_out: bool = True,
        **kwargs: Any,
    ) -> Panel:
        """Create and optionally display a styled Rich Panel."""
        p = Panel(
            renderable,
            title=f"[bold {border_style}]{title}[/bold {border_style}]" if title else None,
            subtitle=subtitle,
            border_style=border_style,
            expand=expand,
            **kwargs,
        )
        if print_out:
            self.stdout_console.print(p)
        return p

    def table(
        self,
        *,
        title: str | None = None,
        columns: Sequence[str | tuple[str, dict[str, Any]]] | None = None,
        rows: Sequence[Sequence[Any]] | None = None,
        border_style: str = "dim blue",
        header_style: str = "bold cyan",
        print_out: bool = True,
        **kwargs: Any,
    ) -> Table:
        """Create and optionally display a styled Rich Table."""
        tbl = Table(
            title=title,
            border_style=border_style,
            header_style=header_style,
            **kwargs,
        )

        if columns:
            for col in columns:
                if isinstance(col, tuple):
                    name, col_kwargs = col
                    tbl.add_column(name, **col_kwargs)
                else:
                    tbl.add_column(str(col))

        if rows:
            for row in rows:
                tbl.add_row(*[str(cell) if not isinstance(cell, (Text, RenderableType)) else cell for cell in row])

        if print_out:
            self.stdout_console.print(tbl)
        return tbl

    @contextmanager
    def status_spinner(
        self,
        status: str = "Processing...",
        *,
        spinner: str = "dots",
        spinner_style: str = "cyan",
    ) -> Generator[Status, None, None]:
        """Context manager for showing a styled progress spinner on stdout."""
        with self.stdout_console.status(status, spinner=spinner, spinner_style=spinner_style) as st:
            yield st

    def rule(self, title: str = "", *, style: str = "dim blue", **kwargs: Any) -> None:
        """Print a horizontal rule across the terminal."""
        self.stdout_console.rule(title, style=style, **kwargs)

    def export_text(self, *, clear: bool = True, styles: bool = False) -> str:
        """Export recorded stdout text (requires record=True)."""
        return self.stdout_console.export_text(clear=clear, styles=styles)

    def export_stderr_text(self, *, clear: bool = True, styles: bool = False) -> str:
        """Export recorded stderr text (requires record=True)."""
        return self.stderr_console.export_text(clear=clear, styles=styles)


# Default global instance
console = UIConsole()

# Module-level convenience functions
info = console.info
success = console.success
warning = console.warning
error = console.error
panel = console.panel
table = console.table
status_spinner = console.status_spinner
print = console.print
print_error = console.print_error
rule = console.rule
