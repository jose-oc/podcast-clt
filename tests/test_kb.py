"""Tests for the Phase 2 knowledge base (turns, chunking, Markdown, store, builder, CLI)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from podcast_ctl.cli.main import app
from podcast_ctl.kb.builder import KbBuilder, slugify
from podcast_ctl.kb.chunking import build_turns, chunk_episode, split_long_turns
from podcast_ctl.kb.config import CHUNK_MAX_CHARS, CHUNK_OVERLAP_CHARS, kb_index_path
from podcast_ctl.kb.markdown import normalize_date, render_episode_markdown
from podcast_ctl.kb.search import format_citation, search_kb
from podcast_ctl.models.transcript import EpisodeMetadata, TranscriptResult, TranscriptSegment
from podcast_ctl.storage.repository import StorageRepository

runner = CliRunner(env={"COLUMNS": "250"})


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run every test against an isolated catalog DB and KB directory."""
    db_file = tmp_path / "test_podcast_ctl.db"
    monkeypatch.setenv("PODCAST_CTL_DB_PATH", str(db_file))
    monkeypatch.setenv("PODCAST_CTL_KB_DIR", str(tmp_path / "kb"))
    return tmp_path


def make_result(
    show_title: str = "Monos Estocásticos",
    episode_title: str = "Ep 42 — La búsqueda semántica",
    episode_id: str = "ep-42",
    speaker_labels: bool = True,
) -> TranscriptResult:
    """Synthetic two-speaker episode with pauses, diacritics, and a long monologue."""
    host = "Jose" if speaker_labels else None
    guest = "Ada" if speaker_labels else None
    segments = [
        TranscriptSegment(start=0.0, end=5.0, text="Bienvenidos al episodio cuarenta y dos.", speaker=host),
        TranscriptSegment(start=5.2, end=9.0, text="Hoy hablamos de búsqueda semántica.", speaker=host),
        TranscriptSegment(start=9.4, end=14.0, text="La búsqueda semántica usa embeddings.", speaker=guest),
        TranscriptSegment(start=14.3, end=18.0, text="Y también índices vectoriales.", speaker=guest),
        # Pause > 3s forces a new turn even for the same speaker.
        TranscriptSegment(start=25.0, end=31.0, text="Después de la pausa seguimos con SQLite.", speaker=guest),
        TranscriptSegment(start=31.2, end=36.0, text="FTS5 da búsqueda léxica con BM25.", speaker=guest),
        TranscriptSegment(start=36.3, end=41.0, text="Exacto, y eso complementa a los vectores.", speaker=host),
    ]
    return TranscriptResult(
        metadata=EpisodeMetadata(
            show_title=show_title,
            episode_title=episode_title,
            episode_id=episode_id,
            audio_url="https://example.com/audio/ep42.mp3",
            duration_seconds=3720.0,
            published_date="Tue, 01 Sep 2026 10:00:00 GMT",
        ),
        segments=segments,
        tier_used="rss",
    )


def make_long_result(episode_id: str = "ep-long") -> TranscriptResult:
    """Episode whose single monologue turn must be split at sentence boundaries."""
    sentences = [f"Esta es la frase número {i} del monólogo largo sobre podcasting." for i in range(80)]
    text = " ".join(sentences)
    seg = TranscriptSegment(start=0.0, end=600.0, text=text, speaker="Jose")
    return TranscriptResult(
        metadata=EpisodeMetadata(
            show_title="Monos Estocásticos",
            episode_title="Ep 43 — Monólogo",
            episode_id=episode_id,
            duration_seconds=600.0,
            published_date="2026-09-08",
        ),
        segments=[seg],
        tier_used="whisper",
    )


# =============================================================================
# Slugs and dates
# =============================================================================


def test_slugify_folds_diacritics_and_symbols() -> None:
    assert slugify("Monos Estocásticos — Tëst!") == "monos-estocasticos-test"


def test_slugify_truncates_with_hash_suffix() -> None:
    slug = slugify("x" * 200, max_len=80)
    assert len(slug) <= 89  # 80 chars + dash + 8 hex chars
    assert slug.endswith("-" + "f2ca1bb6"[:8]) is False  # hash suffix is content-derived, not literal
    _, _, suffix = slug.rpartition("-")
    assert len(suffix) == 8


def test_normalize_date_formats() -> None:
    assert normalize_date("Tue, 01 Sep 2026 10:00:00 GMT") == "2026-09-01"
    assert normalize_date("2026-09-08T13:45:00Z") == "2026-09-08"
    assert normalize_date(None) == ""
    assert normalize_date("not a date") == "not a date"


# =============================================================================
# Turns and chunking
# =============================================================================


def test_build_turns_groups_by_speaker_and_pause() -> None:
    turns = build_turns(make_result().segments)
    # host intro, guest pair, guest pair after pause, host closing = 4 turns
    assert len(turns) == 4
    assert turns[0].speaker == "Jose"
    assert turns[0].segment_start == 0 and turns[0].segment_end == 1
    assert turns[1].speaker == "Ada"
    # Pause-driven split keeps the same speaker but starts a new turn.
    assert turns[2].speaker == "Ada" and turns[2].segment_start == 4
    assert turns[3].speaker == "Jose"


def test_build_turns_without_speaker_labels_splits_on_pause_only() -> None:
    turns = build_turns(make_result(speaker_labels=False).segments)
    assert all(t.speaker is None for t in turns)
    assert len(turns) == 2  # one block before the pause, one after


def test_split_long_turns_respects_sentence_boundaries() -> None:
    result = make_long_result()
    turns = build_turns(result.segments)
    assert len(turns) == 1
    parts = split_long_turns(turns)
    assert len(parts) > 1
    assert all(len(p.text) <= CHUNK_MAX_CHARS for p in parts)
    assert all(p.speaker == "Jose" for p in parts)
    # Nothing lost: concatenated parts reproduce the original text.
    assert " ".join(p.text for p in parts) == turns[0].text


def test_chunk_episode_prefix_citations_and_stability() -> None:
    result = make_result()
    chunks = chunk_episode(result)
    assert chunks
    first = chunks[0]
    assert first.text.startswith("[Monos Estocásticos > Ep 42 — La búsqueda semántica > Full episode]")
    assert "**Jose** (00:00):" in first.text
    # Positions are sequential and IDs stable across identical runs.
    assert [c.position for c in chunks] == list(range(len(chunks)))
    assert [c.chunk_id for c in chunk_episode(result)] == [c.chunk_id for c in chunks]
    # Timestamps and segment traceability are coherent.
    for chunk in chunks:
        assert chunk.start_s <= chunk.end_s
        assert 0 <= chunk.segment_start <= chunk.segment_end


def test_chunk_episode_never_splits_turns() -> None:
    result = make_result()
    chunks = chunk_episode(result)
    turns = build_turns(result.segments)
    body = "\n\n".join(c.text.split("\n\n", 1)[1] for c in chunks)
    for turn in turns:
        # Every turn appears whole in at least one chunk body.
        assert any(turn.text in c.text for c in chunks), turn.text[:40]
    assert "búsqueda" in body


def test_chunk_episode_overlap_carries_tail_turns() -> None:
    result = make_long_result()
    chunks = chunk_episode(result)
    assert len(chunks) > 1
    for prev, nxt in itertools.pairwise(chunks):
        prev_turn_lines = prev.text.split("\n\n")[1:]
        overlap = set(prev_turn_lines[-3:]) & set(nxt.text.split("\n\n")[1:])
        if overlap:
            # Overlap stays within the configured budget per chunk.
            assert sum(len(line) + 1 for line in overlap) <= CHUNK_OVERLAP_CHARS + 60  # speaker/ts line framing
        # No chunk is a full duplicate of another.
        assert prev.chunk_id != nxt.chunk_id


def test_chunk_episode_raw_text_only() -> None:
    result = TranscriptResult(
        metadata=EpisodeMetadata(show_title="Show", episode_title="Ep", episode_id="raw-1", duration_seconds=120.0),
        segments=[],
        tier_used="rss",
        raw_text="Texto plano sin segmentos temporales.",
    )
    chunks = chunk_episode(result)
    assert len(chunks) == 1
    assert chunks[0].segment_start == -1
    assert "Texto plano" in chunks[0].text


def test_chunk_episode_empty_transcript() -> None:
    result = TranscriptResult(
        metadata=EpisodeMetadata(show_title="Show", episode_title="Ep", episode_id="empty-1"),
        segments=[],
        tier_used="rss",
        raw_text="",
    )
    assert chunk_episode(result) == []


# =============================================================================
# Markdown rendering
# =============================================================================


def test_render_episode_markdown_frontmatter_and_turns() -> None:
    result = make_result()
    md = render_episode_markdown(result, "abc123")
    assert md.startswith("---\n")
    assert 'show: Monos Estocásticos' in md
    assert "date: '2026-09-01'" in md  # PyYAML quotes date-like strings
    assert "duration_s: 3720" in md
    assert "source_tier: rss" in md
    assert "episode_url: https://example.com/audio/ep42.mp3" in md
    assert "content_hash: sha256:abc123" in md
    assert "pipeline_version: 1" in md
    assert "# Ep 42 — La búsqueda semántica" in md
    assert "**Jose** (00:00): Bienvenidos" in md
    assert "**Ada** (00:09):" in md


# =============================================================================
# Builder + store end to end
# =============================================================================


def build_kb() -> KbBuilder:
    repo = StorageRepository()
    repo.save_transcript(make_result())
    repo.save_transcript(make_long_result())
    return KbBuilder()


def test_build_creates_all_artifacts() -> None:
    builder = build_kb()
    report = builder.build()
    assert len(report.built) == 2
    assert not report.pruned

    kb_dir = report.kb_dir
    assert (kb_dir / "raw" / "monos-estocasticos" / "ep-42.json").exists()
    assert (kb_dir / "episodes" / "monos-estocasticos" / "ep-42.md").exists()
    assert (kb_dir / "db" / "kb.sqlite").exists()

    index = kb_index_path(kb_dir).read_text(encoding="utf-8")
    assert "Ep 42 — La búsqueda semántica" in index
    assert "episodes/monos-estocasticos/ep-42.md" in index

    stats = builder.store.stats()
    assert stats["episodes"] == 2
    assert stats["chunks"] > 2


def test_build_is_idempotent_and_detects_changes() -> None:
    builder = build_kb()
    first = builder.build()
    assert len(first.built) == 2

    second = builder.build()
    assert len(second.skipped) == 2
    assert not second.built

    # The unchanged episode (ep-long) must keep its exact chunk IDs.
    chunk_ids_before = {row["chunk_id"] for row in builder.store.search("monólogo", limit=50)}
    assert chunk_ids_before

    # Re-transcribe one episode with different content: only it is rebuilt.
    repo = StorageRepository()
    changed = make_result()
    changed.segments.append(
        TranscriptSegment(start=45.0, end=50.0, text="Un cierre completamente nuevo.", speaker="Jose")
    )
    repo.save_transcript(changed)

    third = builder.build()
    assert len(third.built) == 1
    assert len(third.skipped) == 1
    chunk_ids_after = {row["chunk_id"] for row in builder.store.search("monólogo", limit=50)}
    assert chunk_ids_before == chunk_ids_after  # unchanged episode keeps its chunk IDs


def test_build_prunes_episodes_removed_from_cache() -> None:
    builder = build_kb()
    builder.build()

    repo = StorageRepository()
    repo.delete_transcript("Monos Estocásticos", "ep-long")

    report = builder.build()
    assert len(report.pruned) == 1
    assert builder.store.stats()["episodes"] == 1
    assert not (report.kb_dir / "episodes" / "monos-estocasticos" / "ep-long.md").exists()
    assert not (report.kb_dir / "raw" / "monos-estocasticos" / "ep-long.json").exists()


# =============================================================================
# Search
# =============================================================================


def test_search_finds_terms_with_diacritic_folding() -> None:
    builder = build_kb()
    builder.build()
    store = builder.store

    hits = search_kb(store, "busqueda semantica")  # no diacritics in the query
    assert hits
    assert "búsqueda semántica" in hits[0]["text"].lower() or "Búsqueda" in hits[0]["text"]


def test_search_citation_format() -> None:
    builder = build_kb()
    builder.build()
    hits = search_kb(builder.store, "SQLite FTS5")
    assert hits
    citation = format_citation(hits[0])
    assert citation.startswith("[Ep 42 — La búsqueda semántica @ ")


def test_search_show_filter_and_or_fallback() -> None:
    builder = build_kb()
    builder.build()
    store = builder.store

    # Show filter excludes the episode from other shows.
    assert search_kb(store, "monólogo", show_id="Monos Estocásticos")
    assert not search_kb(store, "monólogo", show_id="Otro show")

    # Terms that never co-occur still match via the OR fallback.
    hits = search_kb(store, "monólogo FTS5")
    assert hits


def test_search_empty_query_returns_nothing() -> None:
    builder = build_kb()
    builder.build()
    assert search_kb(builder.store, "   ") == []


# =============================================================================
# CLI
# =============================================================================


def test_cli_kb_build_search_and_status() -> None:
    repo = StorageRepository()
    repo.save_transcript(make_result())

    build = runner.invoke(app, ["kb", "build"])
    assert build.exit_code == 0, build.output
    assert "Built/updated 1 episode" in build.output

    search = runner.invoke(app, ["kb", "search", "búsqueda semántica"])
    assert search.exit_code == 0, search.output
    assert "Ep 42" in search.output
    assert "@" in search.output

    search_json = runner.invoke(app, ["kb", "search", "búsqueda semántica", "--json"])
    assert search_json.exit_code == 0, search_json.output
    payload = json.loads(search_json.output)
    assert payload and payload[0]["citation"].startswith("[Ep 42")

    context = runner.invoke(app, ["kb", "search", "búsqueda semántica", "--context"])
    assert context.exit_code == 0
    assert "### [Ep 42" in context.output

    status = runner.invoke(app, ["kb", "status"])
    assert status.exit_code == 0, status.output
    assert "Indexed episodes" in status.output
    assert "1" in status.output


def test_cli_kb_build_without_cache_warns() -> None:
    result = runner.invoke(app, ["kb", "build"])
    assert result.exit_code == 0
    assert "No cached transcripts found" in result.output


def test_cli_kb_search_no_results() -> None:
    repo = StorageRepository()
    repo.save_transcript(make_result())
    runner.invoke(app, ["kb", "build"])
    result = runner.invoke(app, ["kb", "search", "término inexistente xyz"])
    assert result.exit_code == 0
    assert "No results" in result.output
