"""Search command for discovering podcasts via Apple Podcasts / iTunes API."""

from __future__ import annotations

import sys
from typing import Annotated, Optional
import questionary
from rich.table import Table
import typer

from podcast_cli.discovery.itunes import search_itunes
from podcast_cli.ui.console import console


def search_command(
    query: Annotated[str, typer.Argument(help="Search query (podcast title, topic, or host name)")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum number of search results to display")] = 10,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive/--no-interactive",
            help="Enable interactive selection prompt after search results",
        ),
    ] = True,
) -> None:
    """Search Apple Podcasts / iTunes directory for shows and feeds."""
    with console.status_spinner(f"Searching Apple Podcasts for '[bold white]{query}[/bold white]'..."):
        results = search_itunes(query, limit=limit)

    if not results:
        console.warning(f"No podcast search results found for '{query}'.")
        return

    table = Table(
        title=f"[bold cyan]Search Results for '{query}'[/bold cyan]",
        border_style="dim blue",
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("#", style="bold cyan", justify="right", width=4)
    table.add_column("Title", style="bold white", min_width=25)
    table.add_column("Author", style="dim", min_width=18)
    table.add_column("Episodes", style="cyan", justify="right", width=10)
    table.add_column("Feed URL", style="dim underline", min_width=35)

    for idx, item in enumerate(results, start=1):
        ep_count = str(item.episode_count) if item.episode_count > 0 else "-"
        feed_url = item.feed_url or "[dim italic]No feed URL[/dim italic]"
        table.add_row(str(idx), item.title, item.author or "-", ep_count, feed_url)

    console.print(table)

    # Interactive selection if in a TTY and enabled
    if interactive and sys.stdin.isatty():
        choices = [
            questionary.Choice(
                title=f"{idx}. {item.title} ({item.author or 'Unknown'})",
                value=item,
            )
            for idx, item in enumerate(results, start=1)
            if item.feed_url
        ]
        choices.append(questionary.Choice(title="Cancel / Exit", value="cancel"))

        selected = questionary.select(
            "Select a podcast to inspect or transcribe:",
            choices=choices,
        ).ask()

        if not selected or selected == "cancel" or not hasattr(selected, "feed_url") or not selected.feed_url:
            return

        action = questionary.select(
            f"Action for '{selected.title}':",
            choices=[
                questionary.Choice("Inspect Show & Episodes", value="inspect"),
                questionary.Choice("Transcribe Latest Episode", value="transcribe"),
                questionary.Choice("Print Feed URL", value="url"),
                questionary.Choice("Cancel", value="cancel"),
            ],
            default="inspect",
        ).ask()

        if not action or action == "cancel":
            return

        if action == "inspect":
            from podcast_cli.cli.commands.inspect import inspect_command
            inspect_command(input_source=selected.feed_url)
        elif action == "transcribe":
            from podcast_cli.cli.commands.transcribe import transcribe_command
            transcribe_command(input_source=selected.feed_url, latest=1)
        elif action == "url":
            console.info(f"Feed URL: {selected.feed_url}")
