"""A best-effort local SQLite cache; cache failures must never stop hotin."""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


LOGGER = logging.getLogger(__name__)


def cache_path() -> Path:
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    directory = root / "hotin"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / "cache.db"


def _normalise_record(record: Dict[str, Any]) -> Dict[str, Any]:
    signal = record.get("signal_json", {})
    if not isinstance(signal, str):
        signal = json.dumps(signal, sort_keys=True)
    return {
        "url": str(record.get("url", "")),
        "canonical_repo": record.get("canonical_repo"),
        "name": str(record.get("name", "")),
        "source": str(record.get("source", "")),
        "signal_json": signal,
        "fetched_at": record.get("fetched_at", time.time()),
    }


class MemoryCache:
    """Interface-compatible cache used if SQLite cannot be used at all."""

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}

    def upsert(self, record: Dict[str, Any]) -> None:
        normalized = _normalise_record(record)
        key = normalized["url"] or "{}:{}".format(normalized["source"], normalized["name"])
        self._records[key] = normalized

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        needle = query.lower()
        return [
            dict(record)
            for record in self._records.values()
            if needle in " ".join(str(record.get(key) or "") for key in ("url", "canonical_repo", "name", "source")).lower()
        ]

    def get_all(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self._records.values()]

    def close(self) -> None:
        return None


class Cache:
    """SQLite-backed cache with FTS5 when its Python SQLite build supports it."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._fts_available = False
        self._fallback: Optional[MemoryCache] = None
        self._initialize()

    def _initialize(self) -> None:
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL UNIQUE,
                canonical_repo TEXT,
                name TEXT NOT NULL,
                source TEXT NOT NULL,
                signal_json TEXT NOT NULL,
                fetched_at REAL NOT NULL
            )"""
        )
        fts_existed = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tools_fts'"
        ).fetchone() is not None
        try:
            self._create_fts()
            if not fts_existed:
                self._connection.execute(
                    """INSERT INTO tools_fts (rowid, url, canonical_repo, name, source)
                       SELECT id, url, canonical_repo, name, source FROM tools"""
                )
            self._fts_available = True
        except sqlite3.OperationalError:
            LOGGER.warning("SQLite FTS5 unavailable; cache search will use LIKE")
            self._fts_available = False
        self._connection.commit()

    def _create_fts(self) -> None:
        self._connection.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS tools_fts USING fts5(
                url, canonical_repo, name, source
            )"""
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> Dict[str, Any]:
        return dict(row)

    def _activate_fallback(self, exc: sqlite3.Error) -> MemoryCache:
        LOGGER.warning("SQLite cache unavailable; using memory-only cache: %s", exc)
        if self._fallback is None:
            self._fallback = MemoryCache()
        return self._fallback

    def upsert(self, record: Dict[str, Any]) -> None:
        normalized = _normalise_record(record)
        if self._fallback is not None:
            self._fallback.upsert(normalized)
            return
        try:
            self._connection.execute(
                """INSERT INTO tools (url, canonical_repo, name, source, signal_json, fetched_at)
                   VALUES (:url, :canonical_repo, :name, :source, :signal_json, :fetched_at)
                   ON CONFLICT(url) DO UPDATE SET
                     canonical_repo=excluded.canonical_repo,
                     name=excluded.name,
                     source=excluded.source,
                     signal_json=excluded.signal_json,
                     fetched_at=excluded.fetched_at""",
                normalized,
            )
            if self._fts_available:
                self._connection.execute("DELETE FROM tools_fts WHERE url = ?", (normalized["url"],))
                self._connection.execute(
                    "INSERT INTO tools_fts (url, canonical_repo, name, source) VALUES (?, ?, ?, ?)",
                    (normalized["url"], normalized["canonical_repo"], normalized["name"], normalized["source"]),
                )
            self._connection.commit()
        except sqlite3.Error as exc:
            self._activate_fallback(exc).upsert(normalized)

    def search(self, query: str) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        if self._fallback is not None:
            return self._fallback.search(query)
        try:
            if self._fts_available:
                try:
                    rows = self._connection.execute(
                        """SELECT t.* FROM tools t JOIN tools_fts f ON t.url = f.url
                           WHERE tools_fts MATCH ? ORDER BY t.fetched_at DESC""",
                        (self._fts_query(query),),
                    ).fetchall()
                except sqlite3.OperationalError:
                    # A user query can be invalid FTS syntax; retain the same
                    # friendly substring semantics as the no-FTS build.
                    rows = self._like_search(query)
            else:
                rows = self._like_search(query)
            return [self._row(row) for row in rows]
        except sqlite3.Error as exc:
            return self._activate_fallback(exc).search(query)

    def _like_search(self, query: str) -> List[sqlite3.Row]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%{}%".format(escaped)
        return self._connection.execute(
            """SELECT * FROM tools
               WHERE url LIKE ? ESCAPE '\\' OR canonical_repo LIKE ? ESCAPE '\\'
                  OR name LIKE ? ESCAPE '\\' OR source LIKE ? ESCAPE '\\'
               ORDER BY fetched_at DESC""",
            (pattern, pattern, pattern, pattern),
        ).fetchall()

    @staticmethod
    def _fts_query(query: str) -> str:
        return " ".join('"{}"*'.format(token.replace('"', '""')) for token in query.split())

    def get_all(self) -> List[Dict[str, Any]]:
        if self._fallback is not None:
            return self._fallback.get_all()
        try:
            rows = self._connection.execute("SELECT * FROM tools ORDER BY fetched_at DESC").fetchall()
            return [self._row(row) for row in rows]
        except sqlite3.Error as exc:
            return self._activate_fallback(exc).get_all()

    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error as exc:
            LOGGER.warning("could not close SQLite cache: %s", exc)


def open_cache() -> Any:
    """Open the persistent cache, or return an in-memory replacement on failure."""
    try:
        path = cache_path()
        connection = sqlite3.connect(str(path))
        connection.row_factory = sqlite3.Row
        return Cache(connection)
    except (sqlite3.Error, OSError) as exc:
        LOGGER.warning("SQLite cache unavailable; using memory-only cache: %s", exc)
        return MemoryCache()
