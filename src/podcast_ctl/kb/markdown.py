"""Derived per-episode Markdown renderer for the knowledge base.

Format follows docs/KNOWLEDGE_BASE_DESIGN.md: YAML frontmatter with show,
episode, date, duration, source tier, URL, content hash and pipeline version,
then speaker turns as ``**Speaker** (mm:ss): text`` lines. Chapter headings
(H2 + timestamp) arrive with the post-processing chaptering step; until then
the whole episode renders as a single flat sequence of turns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import yaml

from podcast_ctl.kb.chunking import build_turns, format_turn_line
from podcast_ctl.kb.config import PIPELINE_VERSION
from podcast_ctl.models.transcript import TranscriptResult


def normalize_date(raw: str | None) -> str:
    """Best-effort normalization of a publication date to ISO ``YYYY-MM-DD``.

    Handles ISO 8601 and RFC 2822 (RSS pubDate) strings; returns the original
    string when it cannot be parsed, and "" when empty.
    """
    if not raw:
        return ""
    value = raw.strip()
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.date().isoformat()
    return value


def render_episode_markdown(result: TranscriptResult, content_hash: str) -> str:
    """Render the derived knowledge base Markdown document for one episode."""
    meta = result.metadata

    duration = meta.duration_seconds
    if duration is None and result.segments:
        duration = max((seg.end for seg in result.segments), default=0.0)

    frontmatter = {
        "show": meta.show_title,
        "episode": meta.episode_title,
        "date": normalize_date(meta.published_date),
        "duration_s": int(duration) if duration is not None else None,
        "source_tier": str(result.tier_used),
        "episode_url": meta.audio_url or "",
        "content_hash": f"sha256:{content_hash}",
        "pipeline_version": PIPELINE_VERSION,
    }
    yaml_str = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)

    lines = [f"# {meta.episode_title}", ""]
    if result.segments:
        lines.extend(format_turn_line(turn) for turn in build_turns(result.segments))
    elif result.raw_text.strip():
        lines.append(result.raw_text.strip())

    return f"---\n{yaml_str}---\n\n" + "\n\n".join(lines) + "\n"
