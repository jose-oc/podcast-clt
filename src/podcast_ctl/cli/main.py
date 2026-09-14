"""Main entry point for podcast-ctl Typer application."""

from __future__ import annotations

import logging
import sqlite3
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated

import httpx
import typer
from typer.exceptions import Abort

from podcast_ctl import __version__
from podcast_ctl.cli.commands.cache import cache_app
from podcast_ctl.cli.commands.inspect import inspect_command
from podcast_ctl.cli.commands.kb import kb_app
from podcast_ctl.cli.commands.mapping import mapping_app
from podcast_ctl.cli.commands.search import search_command
from podcast_ctl.cli.commands.transcribe import transcribe_command
from podcast_ctl.errors import PodcastCtlError, debug_enabled, set_debug
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
app.command("search")(search_command)

app.command("inspect")(inspect_command)

app.command("transcribe")(transcribe_command)

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
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Print full Python tracebacks on errors instead of a short message.",
        envvar="PODCAST_CTL_DEBUG",
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
    set_debug(debug)
    _configure_logging(verbose=verbose, log_file=log_file)


def _describe_unexpected(exc: Exception) -> str:
    """One-line, plain-language description of a common unexpected failure."""
    if isinstance(exc, httpx.ConnectError):
        host = exc.request.url.host if exc.request is not None else "the remote service"
        return f"could not connect to {host}. Check your network connection and that the service is running."
    if isinstance(exc, httpx.TimeoutException):
        return "the request timed out. The service may be slow or unreachable; try again."
    if isinstance(exc, httpx.HTTPStatusError):
        host = exc.request.url.host
        status = exc.response.status_code
        if status in (401, 403):
            return (
                f"the service at {host} rejected the request (HTTP {status}). "
                "Check the API key (for example PODCAST_CTL_EMBED_API_KEY) and that it is still valid."
            )
        if status == 404:
            return (
                f"the service at {host} returned HTTP 404. "
                "Check the base URL (for example PODCAST_CTL_EMBED_BASE_URL) and the model name."
            )
        return f"the service at {host} returned HTTP {status}. Try again later, or check the service status."
    if isinstance(exc, sqlite3.OperationalError):
        return f"SQLite error: {exc}. If the database path is custom, check PODCAST_CTL_DB_PATH."
    if isinstance(exc, PermissionError):
        return f"permission denied: {exc.filename or exc}. Check that the path is writable."
    if isinstance(exc, FileNotFoundError):
        return f"file not found: {exc.filename or exc}. Check that the path exists and is typed correctly."
    return f"{type(exc).__name__}: {exc}"


def _log_traceback_to_file(exc: BaseException) -> Path | None:
    """Record the full traceback on the file log handler only, keeping it off the console.

    Returns the log file path so the user can be pointed at it, or None when
    no file handler is configured (e.g. the log directory is not writable).
    """
    logger = logging.getLogger("podcast_ctl")
    record = logger.makeRecord(
        logger.name,
        logging.ERROR,
        __file__,
        0,
        f"Unhandled error: {exc!r}",
        (),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    log_path: Path | None = None
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            handler.handle(record)
            if log_path is None:
                log_path = Path(handler.baseFilename)
    return log_path


def run() -> None:
    """Console-script entry point: run the Typer app behind the CLI error boundary.

    Expected, user-facing errors (:class:`PodcastCtlError`) print a short,
    actionable message and exit 1. Unexpected errors print a one-line summary,
    write the full traceback to the log file, and exit 1. ``--debug`` or
    ``PODCAST_CTL_DEBUG=1`` re-raises unexpected errors with the full
    traceback for troubleshooting.
    """
    try:
        app()
    except (SystemExit, typer.Exit, Abort):
        raise
    except PodcastCtlError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc.message}")
        if exc.hint:
            console.print(f"[dim]Hint: {exc.hint}[/dim]")
        _log_traceback_to_file(exc)
        raise SystemExit(1) from None
    except Exception as exc:
        if debug_enabled():
            raise
        console.print(f"[bold red]Unexpected error:[/bold red] {_describe_unexpected(exc)}")
        log_path = _log_traceback_to_file(exc)
        if log_path is not None:
            console.print(f"[dim]The full traceback was written to the log file: {log_path}[/dim]")
        console.print("[dim]Rerun with --debug (or PODCAST_CTL_DEBUG=1) to print the traceback.[/dim]")
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
