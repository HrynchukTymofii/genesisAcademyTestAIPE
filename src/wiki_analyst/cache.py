"""SQLite response cache keyed by full request URL.

Entries with ``expires_at = NULL`` are permanent (completed months never change);
others expire after a TTL (current period, search results).
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    url        TEXT PRIMARY KEY,
    status     INTEGER NOT NULL,
    body       TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    expires_at REAL
)
"""


def default_cache_path() -> Path:
    env = os.environ.get("WIKI_ANALYST_CACHE")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "wiki-analyst" / "cache.sqlite"


class Cache:
    """Tiny key/value store. Use ``Cache(":memory:")`` in tests."""

    def __init__(self, path: str | Path | None = None):
        path = default_cache_path() if path is None else path
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, url: str) -> tuple[int, str] | None:
        row = self._conn.execute(
            "SELECT status, body, expires_at FROM responses WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return None
        status, body, expires_at = row
        if expires_at is not None and expires_at < time.time():
            return None
        return status, body

    def set(self, url: str, status: int, body: str, ttl: float | None) -> None:
        """Store a response. ``ttl=None`` means permanent."""
        now = time.time()
        expires = None if ttl is None else now + ttl
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (url, status, body, fetched_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (url, status, body, now, expires),
        )
        self._conn.commit()

    def stats(self) -> dict:
        total, permanent = self._conn.execute(
            "SELECT COUNT(*), SUM(expires_at IS NULL) FROM responses"
        ).fetchone()
        return {"path": self.path, "entries": total, "permanent": permanent or 0}

    def close(self) -> None:
        self._conn.close()
