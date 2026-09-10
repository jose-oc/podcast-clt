"""Search helpers: citations and LLM-ready context blocks."""

from __future__ import annotations

from podcast_ctl.exporters.base import format_timestamp
from podcast_ctl.kb.store import KbStore


def search_kb(store: KbStore, query: str, limit: int = 10, show_id: str | None = None) -> list[dict[str, object]]:
    """Run a lexical search over the KB index (see KbStore.search)."""
    return store.search(query, limit=limit, show_id=show_id)


def format_citation(hit: dict[str, object]) -> str:
    """Render a hit as an ``[Episode @ mm:ss]`` citation."""
    start = hit.get("start_s")
    ts = format_timestamp(float(start), always_include_hours=False) if isinstance(start, (int, float)) else "00:00"
    return f"[{hit.get('episode_title', '')} @ {ts}]"


def format_context_block(hit: dict[str, object]) -> str:
    """Render a hit as a copy-pastable Markdown block for LLM prompts."""
    citation = format_citation(hit)
    return f"### {citation} — {hit.get('show_title', '')}\n\n{hit.get('text', '')}"
