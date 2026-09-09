"""SQLite database connection manager and schema initialization."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from typing import Generator, Optional, Union

DEFAULT_DB_DIR = Path.home() / ".local" / "share" / "podcast-cli"
DEFAULT_DB_FILE = "podcast_cli.db"


def get_default_db_path() -> Path:
    """Return the default SQLite database path, honoring PODCAST_CLI_DB_PATH env var if set."""
    env_path = os.environ.get("PODCAST_CLI_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_DIR / DEFAULT_DB_FILE


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS shows (
    id TEXT PRIMARY KEY,
    title TEXT,
    feed_url TEXT UNIQUE,
    metadata_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT,
    show_id TEXT,
    title TEXT,
    duration REAL,
    audio_url TEXT,
    published_date TEXT,
    metadata_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (show_id, id)
);

CREATE TABLE IF NOT EXISTS transcripts (
    show_id TEXT,
    episode_id TEXT,
    tier_used TEXT,
    transcript_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (show_id, episode_id)
);

CREATE TABLE IF NOT EXISTS knowledge_mappings (
    mapping_type TEXT,
    key TEXT PRIMARY KEY,
    target_url TEXT,
    confirmed_by_user INTEGER DEFAULT 1,
    metadata_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transcripts_show ON transcripts(show_id);
CREATE INDEX IF NOT EXISTS idx_episodes_show ON episodes(show_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_type ON knowledge_mappings(mapping_type);
"""


class Database:
    """Manages SQLite connections with WAL mode and schema initialization."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        if db_path is None:
            self.db_path = get_default_db_path()
            self._is_memory = False
        elif str(db_path) == ":memory:":
            self.db_path = Path(":memory:")
            self._is_memory = True
        else:
            self.db_path = Path(db_path)
            self._is_memory = False

        self._memory_conn: Optional[sqlite3.Connection] = None
        if not self._is_memory and str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def is_memory(self) -> bool:
        """Check if database is in-memory."""
        return self._is_memory

    def get_connection(self) -> sqlite3.Connection:
        """Create and configure a SQLite connection with WAL mode and foreign keys enabled."""
        if self._is_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._configure_connection(self._memory_conn)
            return self._memory_conn

        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._configure_connection(conn)
        return conn

    def _configure_connection(self, conn: sqlite3.Connection) -> None:
        """Apply performance and integrity pragmas to connection."""
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

    def init_schema(self) -> None:
        """Initialize required database tables and indices."""
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding a database connection and auto-committing or rolling back."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not self._is_memory:
                conn.close()

    def close(self) -> None:
        """Close persistent in-memory connection if active."""
        if self._memory_conn is not None:
            self._memory_conn.close()
            self._memory_conn = None
