"""Main entry point for podcast-ctl Typer application."""

from __future__ import annotations

import logging
from typing import Optional
import typer

from podcast_ctl import __version__
from podcast_ctl.cli.commands.cache import cache_app
from podcast_ctl.cli.commands.inspect import inspect_command
from podcast_ctl.cli.commands.mapping import mapping_app
from podcast_ctl.cli.commands.search import search_command
from podcast_ctl.cli.commands.transcribe import transcribe_command
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


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold cyan]podcast-ctl[/bold cyan] version [bold white]v{__version__}[/bold white]")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
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
        help="Enable verbose debug logging output.",
    ),
) -> None:
    """Fast, modular CLI to discover, inspect, and transcribe podcast episodes and YouTube shows."""
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


if __name__ == "__main__":
    app()
