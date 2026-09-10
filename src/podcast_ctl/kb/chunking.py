"""Turn building and retrieval chunking for knowledge base episodes.

Chunking rules (from docs/KNOWLEDGE_BASE_DESIGN.md):

- Chunks are built from whole speaker turns; a turn is never split mid-way
  (turns longer than the chunk max are pre-split at sentence boundaries).
- Chunks target ~1200 chars with a small overlap carried from the tail of the
  previous chunk.
- Every chunk is prefixed with ``[Show > Episode > Chapter]`` so retrieved
  fragments carry their context for free.
- Chunk IDs are content hashes of (show, episode, chapter, position, text),
  so unchanged input always reproduces identical IDs.
"""

from __future__ import annotations

import hashlib
import re

from podcast_ctl.exporters.base import format_timestamp
from podcast_ctl.kb.config import (
    CHUNK_MAX_CHARS,
    CHUNK_OVERLAP_CHARS,
    CHUNK_TARGET_CHARS,
    DEFAULT_CHAPTER,
    MAX_PAUSE_SECONDS,
)
from podcast_ctl.kb.models import Chunk, Turn
from podcast_ctl.models.transcript import TranscriptResult, TranscriptSegment

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def build_turns(segments: list[TranscriptSegment], max_pause_seconds: float = MAX_PAUSE_SECONDS) -> list[Turn]:
    """Group raw segments into speaker turns.

    A new turn starts when the speaker label changes or the pause since the
    previous segment exceeds ``max_pause_seconds`` (the same grouping rule as
    the Markdown exporter, so documents and chunks stay aligned).
    """
    turns: list[Turn] = []
    cur_texts: list[str] = []
    cur_speaker: str | None = None
    cur_start = 0.0
    cur_end = 0.0
    cur_first = 0
    cur_last = -1
    prev_end = 0.0

    def flush() -> None:
        nonlocal cur_texts, cur_speaker, cur_last
        if cur_last < 0:
            return
        turns.append(
            Turn(
                speaker=cur_speaker,
                start=cur_start,
                end=cur_end,
                text=" ".join(cur_texts),
                segment_start=cur_first,
                segment_end=cur_last,
            )
        )
        cur_texts = []
        cur_speaker = None
        cur_last = -1

    for idx, seg in enumerate(segments):
        text = seg.text.strip()
        if not text:
            continue
        speaker = seg.speaker.strip() if seg.speaker and seg.speaker.strip() else None

        if cur_last >= 0:
            speaker_changed = speaker != cur_speaker
            pause_exceeded = (seg.start - prev_end) > max_pause_seconds
            if speaker_changed or pause_exceeded:
                flush()

        if cur_last < 0:
            cur_texts = [text]
            cur_speaker = speaker
            cur_start = seg.start
            cur_first = idx
        else:
            cur_texts.append(text)

        cur_end = seg.end
        cur_last = idx
        prev_end = seg.end

    flush()
    return turns


def split_long_turns(turns: list[Turn], max_chars: int = CHUNK_MAX_CHARS) -> list[Turn]:
    """Split turns longer than ``max_chars`` at sentence boundaries.

    Speaker and timestamps are preserved on every part (they are
    approximations for the parts, but keep chunks honest about who is
    speaking). A single sentence longer than the limit is kept whole rather
    than cut mid-sentence.
    """
    out: list[Turn] = []
    for turn in turns:
        if len(turn.text) <= max_chars:
            out.append(turn)
            continue
        buf = ""
        for sentence in _SENTENCE_SPLIT_RE.split(turn.text):
            candidate = f"{buf} {sentence}" if buf else sentence
            if buf and len(candidate) > max_chars:
                out.append(turn.model_copy(update={"text": buf}))
                buf = sentence
            else:
                buf = candidate
        if buf:
            out.append(turn.model_copy(update={"text": buf}))
    return out


def format_turn_line(turn: Turn) -> str:
    """Render a turn as a ``**Speaker** (mm:ss): text`` Markdown line."""
    ts = format_timestamp(turn.start, always_include_hours=False)
    if turn.speaker:
        return f"**{turn.speaker}** ({ts}): {turn.text}"
    return f"({ts}): {turn.text}"


def _chunk_id(show_id: str, episode_id: str, chapter: str, position: int, text: str) -> str:
    digest = hashlib.sha256(f"{show_id}|{episode_id}|{chapter}|{position}|{text}".encode())
    return digest.hexdigest()[:16]


def chunk_episode(result: TranscriptResult, chapter: str = DEFAULT_CHAPTER) -> list[Chunk]:
    """Derive retrieval chunks from a transcript.

    Returns an empty list when the transcript has neither segments nor raw
    text. Episodes with only ``raw_text`` are chunked as a single unlabeled
    turn sequence (segment indexes are -1).
    """
    meta = result.metadata
    show_id = meta.effective_show_id

    if result.segments:
        turns = split_long_turns(build_turns(result.segments))
    elif result.raw_text.strip():
        turns = split_long_turns(
            [
                Turn(
                    speaker=None,
                    start=0.0,
                    end=meta.duration_seconds or 0.0,
                    text=result.raw_text.strip(),
                    segment_start=-1,
                    segment_end=-1,
                )
            ]
        )
    else:
        return []

    prefix = f"[{meta.show_title} > {meta.episode_title} > {chapter}]"

    def turn_len(idx: int) -> int:
        # +1 accounts for the blank line joining turn lines inside a chunk.
        return len(turns[idx].text) + 1

    def emit(indices: list[int]) -> Chunk:
        body = "\n\n".join(format_turn_line(turns[i]) for i in indices)
        text = f"{prefix}\n\n{body}"
        return Chunk(
            chunk_id=_chunk_id(show_id, meta.episode_id, chapter, len(chunks), text),
            show_id=show_id,
            episode_id=meta.episode_id,
            show_title=meta.show_title,
            episode_title=meta.episode_title,
            chapter=chapter,
            position=len(chunks),
            start_s=turns[indices[0]].start,
            end_s=turns[indices[-1]].end,
            text=text,
            segment_start=turns[indices[0]].segment_start,
            segment_end=turns[indices[-1]].segment_end,
        )

    chunks: list[Chunk] = []
    current: list[int] = []
    size = 0
    fresh = False  # True once `current` contains at least one not-yet-emitted turn

    i = 0
    while i < len(turns):
        t_len = turn_len(i)
        if fresh and size + t_len > CHUNK_TARGET_CHARS:
            chunks.append(emit(current))
            # Seed the next chunk with trailing turn(s) fitting the overlap
            # budget. The seed only repeats already-emitted turns; the next
            # emitted chunk still advances because turn i is unconsumed.
            seed: list[int] = []
            seed_size = 0
            for j in reversed(current):
                jl = turn_len(j)
                if seed_size + jl > CHUNK_OVERLAP_CHARS:
                    break
                seed.insert(0, j)
                seed_size += jl
            current = seed
            size = seed_size
            fresh = False
            continue
        current.append(i)
        size += t_len
        fresh = True
        i += 1

    if current and fresh:
        chunks.append(emit(current))

    return chunks
