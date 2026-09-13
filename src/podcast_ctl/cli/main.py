"""Main entry point for podcast-ctl Typer application."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated

import typer

from podcast_ctl import __version__
from podcast_ctl.cli.commands.cache import cache_app
from podcast_ctl.cli.commands.inspect import inspect_command
from podcast_ctl.cli.commands.kb import kb_app
from podcast_ctl.cli.commands.mapping import mapping_app
from podcast_ctl.cli.commands.search import search_command
from podcast_ctl.cli.commands.transcribe import transcribe_command
from podcast_ctl.storage.db import get_default_db_path
from podcast_ctl.ui.console import console

app = typer.Typer(
    name="podcast-ctl",
    help="Fast, modular CLI to discover, inspect, and transcribe podcast episodes and YouTube shows.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)

# Register standalone commands
app.command(
    "search",
    help="Search Apple Podcasts / iTunes directory for shows and RSS feeds.",
)(search_command)

app.command(
    "inspect",
    help="Inspect a podcast feed, video, or audio file and display pre-flight analysis.",
)(inspect_command)

app.command(
    "transcribe",
    help="Transcribe podcast episodes, YouTube videos, or local audio files.",
)(transcribe_command)

# Register command sub-applications
app.add_typer(
    mapping_app,
    name="mapping",
    help="Manage learned Show <-> YouTube Channel and Episode <-> YouTube Video mappings.",
)

app.add_typer(
    cache_app,
    name="cache",
    help="Inspect, list, and manage SQLite cached transcripts and storage.",
)

app.add_typer(
    kb_app,
    name="kb",
    help="Build and query the knowledge base derived from cached transcripts.",
)


def _default_log_file() -> Path:
    """Default persistent log file, next to the SQLite catalog."""
    return get_default_db_path().parent / "logs" / "podcast-ctl.log"


def _configure_logging(verbose: bool, log_file: Path | None) -> None:
    """Configure console logging plus a persistent rotating log file.

    The console stays quiet (WARNING, or DEBUG with --verbose). The log file
    always records INFO and above with simple rotation, so batch runs can be
    diagnosed afterwards. Logging setup never blocks the CLI: if the file
    cannot be opened, only console logging is used.
    """
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    handlers: list[logging.Handler] = [console_handler]

    path = log_file or _default_log_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        handlers.append(file_handler)
    except OSError:
        pass

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold cyan]podcast-ctl[/bold cyan] version [bold white]v{__version__}[/bold white]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Enable verbose debug logging output on the console.",
    ),
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Custom log file path (default: <data dir>/logs/podcast-ctl.log; always records INFO and above).",
        ),
    ] = None,
) -> None:
    """Fast, modular CLI to discover, inspect, and transcribe podcast episodes and YouTube shows."""
    _configure_logging(verbose=verbose, log_file=log_file)


if __name__ == "__main__":
    app()
