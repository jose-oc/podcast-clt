"""Episode selection helpers: number specs, title/date filters, and interactive picking.

This module powers the multi-episode selection UX of ``podcast-ctl transcribe``:

* ``--episode`` stays the exact single-episode selector (handled in ``transcribe.py``).
* ``--episodes`` selects several episodes by their own number, as a comma-separated
  list and/or inclusive ranges (e.g. ``2890,2894,2901`` or ``2890..2900``).
* ``--match`` selects episodes whose title matches a case-insensitive regex.
* ``--since`` / ``--until`` select episodes by publication date (inclusive).
* ``--pick`` opens an interactive multi-select picker over the filtered candidates.

All filters compose as a logical AND, and every selection ends in the pre-flight
display (number, date, title and duration) before the confirmation prompt.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from email.utils import parsedate_to_datetime

import questionary

from podcast_ctl.models.transcript import EpisodeMetadata
from podcast_ctl.ui.console import UIConsole
from podcast_ctl.ui.console import console as default_console

# Leading episode number in a title, e.g. "2894. Title", "#2894 - Title" or "2894: Title"
LEADING_TITLE_NUMBER_REGEX = re.compile(r"^\s*#?(?P<number>\d+)[\s.\-:)\]]")

# Maximum number of choices shown at once in the interactive picker.
PICK_CHOICE_LIMIT = 100


class EpisodeSpecError(ValueError):
    """Raised when a CLI episode-selection specification is invalid."""


def episode_number(ep: EpisodeMetadata) -> int | None:
    """The episode's own number: feed-declared (e.g. itunes:episode) first, then a leading number in the title."""
    if ep.episode_number is not None:
        return ep.episode_number
    title_match = LEADING_TITLE_NUMBER_REGEX.match(ep.episode_title)
    if title_match:
        return int(title_match.group("number"))
    return None


def episode_number_label(ep: EpisodeMetadata) -> str:
    """Human-readable episode number, or '-' when the episode has no number."""
    number = episode_number(ep)
    return str(number) if number is not None else "-"


def _build_number_index(all_episodes: list[EpisodeMetadata]) -> dict[int, list[EpisodeMetadata]]:
    """Map episode number -> episodes, with feed-declared numbers winning over title-prefixed ones."""
    declared: dict[int, list[EpisodeMetadata]] = {}
    titled: dict[int, list[EpisodeMetadata]] = {}
    for ep in all_episodes:
        number = episode_number(ep)
        if number is None:
            continue
        if ep.episode_number is not None:
            declared.setdefault(number, []).append(ep)
        else:
            titled.setdefault(number, []).append(ep)
    index = dict(titled)
    index.update(declared)
    return index


def match_episode_number(all_episodes: list[EpisodeMetadata], number: int) -> list[EpisodeMetadata]:
    """Match episodes by their own declared or title-prefixed episode number."""
    return list(_build_number_index(all_episodes).get(number, []))


@dataclass
class EpisodeNumberSpec:
    """Parsed ``--episodes`` value: explicit numbers and inclusive ranges."""

    singles: list[int] = field(default_factory=list)
    ranges: list[tuple[int, int]] = field(default_factory=list)


def parse_episode_number_spec(spec: str) -> EpisodeNumberSpec:
    """Parse a comma-separated list of episode numbers and inclusive ``START..END`` ranges.

    Raises EpisodeSpecError on empty input, non-numeric tokens, malformed or reversed ranges.
    """
    result = EpisodeNumberSpec()
    tokens = [token.strip() for token in spec.split(",") if token.strip()]
    if not tokens:
        raise EpisodeSpecError("Empty episode list. Use e.g. --episodes 2890,2894,2901 or --episodes 2890..2900.")
    for token in tokens:
        if ".." in token:
            parts = token.split("..")
            if len(parts) != 2 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
                raise EpisodeSpecError(f"Invalid range '{token}'. Use START..END with whole numbers, e.g. 2890..2900.")
            start, end = int(parts[0]), int(parts[1])
            if start > end:
                raise EpisodeSpecError(
                    f"Invalid range '{token}': start must be less than or equal to end (got {start}..{end})."
                )
            result.ranges.append((start, end))
        elif token.isdigit():
            result.singles.append(int(token))
        else:
            raise EpisodeSpecError(
                f"Invalid episode number '{token}'. Only whole numbers, commas and START..END ranges are supported."
            )
    return result


def select_by_number_spec(
    all_episodes: list[EpisodeMetadata],
    spec: EpisodeNumberSpec,
) -> tuple[list[EpisodeMetadata], list[int]]:
    """Select episodes by number spec. Returns (selected, missing_numbers).

    Selection order follows the spec: explicit numbers in the given order, then each
    range in ascending numeric order. Duplicates across singles and ranges are removed.
    Numbers with no matching episode are reported in ``missing_numbers``.
    """
    index = _build_number_index(all_episodes)
    selected: list[EpisodeMetadata] = []
    seen_ids: set[str] = set()
    missing: list[int] = []

    def add_number(number: int) -> None:
        matches = index.get(number)
        if not matches:
            missing.append(number)
            return
        for ep in matches:
            if ep.episode_id not in seen_ids:
                seen_ids.add(ep.episode_id)
                selected.append(ep)

    for number in spec.singles:
        add_number(number)
    for start, end in spec.ranges:
        for number in range(start, end + 1):
            add_number(number)
    return selected, missing


def filter_by_title_pattern(
    all_episodes: list[EpisodeMetadata],
    pattern: str,
) -> list[EpisodeMetadata]:
    """Keep episodes whose title matches a case-insensitive regular expression."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise EpisodeSpecError(f"Invalid title pattern '{pattern}': {exc}") from exc
    return [ep for ep in all_episodes if regex.search(ep.episode_title)]


def parse_cli_date(value: str) -> date:
    """Parse a CLI date argument in ISO format (YYYY-MM-DD)."""
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise EpisodeSpecError(f"Invalid date '{value}'. Use ISO format YYYY-MM-DD.") from exc


def episode_publication_date(ep: EpisodeMetadata) -> date | None:
    """Best-effort parse of an episode's publication date (RFC 2822, ISO 8601, or bare date)."""
    raw = (ep.published_date or "").strip()
    if not raw:
        return None
    try:
        # RSS pubDate, e.g. "Wed, 10 Sep 2026 07:00:00 GMT"
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        pass
    try:
        # ISO 8601, e.g. "2026-09-10T07:00:00Z" (Atom feeds)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def filter_by_publication_date(
    all_episodes: list[EpisodeMetadata],
    since: date | None,
    until: date | None,
) -> tuple[list[EpisodeMetadata], int]:
    """Keep episodes published between ``since`` and ``until`` (both inclusive).

    Episodes without a parseable publication date are excluded. Returns the filtered
    list (feed order) and how many episodes were excluded for having no known date.
    """
    if since is None and until is None:
        return list(all_episodes), 0
    filtered: list[EpisodeMetadata] = []
    unknown_dates = 0
    for ep in all_episodes:
        published = episode_publication_date(ep)
        if published is None:
            unknown_dates += 1
            continue
        if since is not None and published < since:
            continue
        if until is not None and published > until:
            continue
        filtered.append(ep)
    return filtered, unknown_dates


def format_duration(duration_seconds: float | None) -> str:
    """Human-readable duration (e.g. '1h 5m 20s', '23m 1s'), or '-' when unknown."""
    if not duration_seconds or duration_seconds <= 0:
        return "-"
    total = int(duration_seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _picker_choice_title(ep: EpisodeMetadata) -> str:
    published = episode_publication_date(ep)
    published_str = published.isoformat() if published else "no date"
    return f"{episode_number_label(ep)} · {ep.episode_title} ({published_str} · {format_duration(ep.duration_seconds)})"


def pick_episodes_interactively(
    candidates: list[EpisodeMetadata],
    *,
    console: UIConsole | None = None,
) -> list[EpisodeMetadata] | None:
    """Interactive multi-select picker over ``candidates``.

    Returns the picked episodes in display order, an empty list when a narrowing
    filter matched nothing, or None when the user cancelled. Raises
    EpisodeSpecError on a non-interactive terminal.
    """
    c = console or default_console
    if not sys.stdin.isatty():
        raise EpisodeSpecError(
            "--pick requires an interactive terminal. In scripts, use --episodes, --match, --since or --until instead."
        )

    filtered = list(candidates)
    if len(filtered) > PICK_CHOICE_LIMIT:
        query = questionary.text(
            f"{len(filtered)} episodes available. Type a title filter to narrow the list "
            f"(empty keeps the newest {PICK_CHOICE_LIMIT}):",
        ).ask()
        if query is None:
            return None
        if query.strip():
            filtered = [ep for ep in filtered if query.strip().lower() in ep.episode_title.lower()]
        if not filtered:
            c.warning(f"No episodes match filter '{query.strip()}'.")
            return []
        if len(filtered) > PICK_CHOICE_LIMIT:
            c.info(
                f"Still {len(filtered)} matches; showing the newest {PICK_CHOICE_LIMIT}. Refine the filter to see others."
            )
            filtered = filtered[:PICK_CHOICE_LIMIT]

    choices = [questionary.Choice(title=_picker_choice_title(ep), value=idx) for idx, ep in enumerate(filtered)]
    selected_indexes = questionary.checkbox(
        "Select episodes to transcribe (space to toggle, enter to confirm):",
        choices=choices,
        validate=lambda selection: True if selection else "Select at least one episode",
    ).ask()
    if selected_indexes is None:
        return None
    chosen = set(selected_indexes)
    return [ep for idx, ep in enumerate(filtered) if idx in chosen]
