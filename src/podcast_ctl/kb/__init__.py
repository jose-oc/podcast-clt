"""Phase 2 knowledge base: derived Markdown, chunked indexes, and hybrid search.

The knowledge base turns immutable cached transcripts into retrieval-ready
artifacts:

- ``raw/``: write-once JSON snapshots of the source transcripts.
- ``episodes/``: derived per-episode Markdown documents.
- ``INDEX.md``: browsable catalog of every indexed episode.
- ``db/kb.sqlite``: chunk index with FTS5 lexical search (BM25) and per-chunk
  embeddings (phase 2c), kept separate from the catalog database so it can be
  rebuilt or moved independently. Retrieval fuses lexical and vector ranking
  with Reciprocal Rank Fusion; embedding providers are pluggable, local by
  default, and every vector records its model/version provenance.
"""
