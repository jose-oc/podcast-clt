"""Phase 2 knowledge base: derived Markdown, chunked indexes, and lexical search.

The knowledge base turns immutable cached transcripts into retrieval-ready
artifacts:

- ``raw/``: write-once JSON snapshots of the source transcripts.
- ``episodes/``: derived per-episode Markdown documents.
- ``INDEX.md``: browsable catalog of every indexed episode.
- ``db/kb.sqlite``: chunk index with FTS5 lexical search (BM25), kept separate
  from the catalog database so it can be rebuilt or moved independently.
"""
