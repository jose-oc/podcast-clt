"""Domain models for the Phase 2 knowledge base."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """A contiguous block of speech by one speaker.

    Turns group consecutive raw segments from the same speaker (or separated
    by short pauses when no speaker labels exist) and are the smallest unit
    the chunker works with: chunks never split a turn mid-way.
    """

    speaker: str | None = Field(default=None, description="Speaker label if available")
    start: float = Field(..., description="Turn start timestamp in seconds")
    end: float = Field(..., description="Turn end timestamp in seconds")
    text: str = Field(..., description="Merged turn text")
    segment_start: int = Field(..., description="Index of first raw segment (inclusive); -1 when not segment-backed")
    segment_end: int = Field(..., description="Index of last raw segment (inclusive); -1 when not segment-backed")


class Chunk(BaseModel):
    """A retrieval-ready unit derived from consecutive turns of one chapter.

    Chunk text always starts with a ``[Show > Episode > Chapter]`` prefix so
    every retrieved fragment carries its own context. The chunk ID is a stable
    content hash: re-running the pipeline over unchanged input reproduces the
    exact same IDs.
    """

    chunk_id: str = Field(..., description="Stable content-hash identifier")
    show_id: str
    episode_id: str
    show_title: str
    episode_title: str
    chapter: str
    position: int = Field(..., description="Chunk order within the episode")
    start_s: float = Field(..., description="Start timestamp of the first turn in seconds")
    end_s: float = Field(..., description="End timestamp of the last turn in seconds")
    text: str = Field(..., description="Full chunk text including the context prefix")
    segment_start: int = Field(..., description="First raw segment index covered (inclusive); -1 if none")
    segment_end: int = Field(..., description="Last raw segment index covered (inclusive); -1 if none")
