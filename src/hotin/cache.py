"""A best-effort local SQLite cache; cache failures must never stop hotin.

Records are keyed by ``(entity_type, entity_id, source)``. For repos,
``entity_id == canonical_repo``; other entity types (paper, model) supply their
own id. URL is provenance, never identity.
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


LOGGER = logging.getLogger(__name__)

# Bump when the physical schema changes; _migrate() upgrades older databases.
SCHEMA_VERSION = 2

_TABLE_COLUMNS = """
                id INTEGER PRIMARY KEY,
                entity_type TEXT NOT NULL DEFAULT 'repo',
                entity_id TEXT NOT NULL,
                url TEXT NOT NULL,
                canonical_repo TEXT,
                name TEXT NOT NULL,
                source TEXT NOT NULL,
                signal_json TEXT NOT NULL,
                fetched_at REAL NOT NULL,
                UNIQUE(entity_type, entity_id, source)
"""

# Append-only time series. run_id groups one ingest; the uniqueness key makes a
# retried run idempotent (same value, no dup) while a genuine later run appends a
# fresh sample. This is what velocity/acceleration are computed from.
_OBSERVATIONS_COLUMNS = """
                id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                source TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                observed_at REAL NOT NULL,
                UNIQUE(run_id, entity_type, entity_id, source, metric)
"""


def cache_path() -> Path:
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    directory = root / "hotin"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / "cache.db"


def _normalise_record(record: Dict[str, Any]) -> Dict[str, Any]:
    signal = record.get("signal_json", {})
    if not isinstance(signal, str):
        signal = json.dumps(signal, sort_keys=True)
    entity_type = record.get("entity_type") or "repo"
    canonical = record.get("canonical_repo")
    # entity_id: repos use the canonical repo; other entity types supply one.
    # Fall back to canonical_repo, then url, so a row is never keyless.
    entity_id = record.get("entity_id") or canonical or record.get("url") or ""
    return {
        "entity_type": str(entity_type),
        "entity_id": str(entity_id),
        "url": str(record.get("url", "")),
        "canonical_repo": canonical,
        "name": str(record.get("name", "")),
        "source": str(record.get("source", "")),
        "signal_json": signal,
        "fetched_at": record.get("fetched_at", time.time()),
    }


class MemoryCache:
    """Interface-compatible cache used if SQLite cannot be used at all."""

    def __init__(self) -> None:
        self._records: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._observations: List[Dict[str, Any]] = []

    def upsert(self, record: Dict[str, Any]) -> None:
        normalized = _normalise_record(record)
        key = (normalized["entity_type"], normalized["entity_id"], normalized["source"])
        self._records[key] = normalized

    def record_observations(self, observations: List[Dict[str, Any]]) -> None:
        seen = {(o["run_id"], o["entity_type"], o["entity_id"], o["source"], o["metric"]) for o in self._observations}
        for obs in observations:
            key = (obs["run_id"], obs["entity_type"], obs["entity_id"], obs["source"], obs["metric"])
            if key not in seen:
                seen.add(key)
                self._observations.append(dict(obs))

    def observations_for(self, entity_type: str, entity_id: str, metric: str) -> List[Tuple[float, float]]:
        rows = [(o["value"], o["observed_at"]) for o in self._observations
                if o["entity_type"] == entity_type and o["entity_id"] == entity_id and o["metric"] == metric]
        return sorted(rows, key=lambda item: item[1])

    def recent_observations(self, since: float) -> List[Dict[str, Any]]:
        return [dict(o) for o in self._observations if o["observed_at"] >= since]

    def prune_observations(self, cutoff: float) -> None:
        self._observations = [o for o in self._observations if o["observed_at"] >= cutoff]

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Return observations per ``(entity_type, entity_id, source)``.

        Callers displaying tools must first route records through the engine's
        merge/filter (e.g. ``engine.merge_by_repo``).
        """
        if not query.strip():
            return []
        needle = query.lower()
        return [
            dict(record)
            for record in self._records.values()
            if needle in " ".join(str(record.get(key) or "") for key in ("url", "canonical_repo", "name", "source")).lower()
        ]

    def get_all(self) -> List[Dict[str, Any]]:
        """Return every observation; callers filter/merge in the engine."""
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
        try:
            self._migrate()
        except sqlite3.Error as exc:
            # A migration we cannot complete is not worth crashing over; degrade
            # to the in-memory cache for this run rather than lose the command.
            self._activate_fallback(exc)
            return
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

    def _migrate(self) -> None:
        """Bring the physical schema up to SCHEMA_VERSION, preserving data.

        Handles: fresh DB, the legacy pre-release ``UNIQUE(url)`` schema, and the
        shipped ``UNIQUE(url, source)`` schema (both at user_version 0). Rebuilds
        ``tools`` when the entity columns are absent, deterministically keeping
        the newest row per new key, then forces an FTS backfill.
        """
        conn = self._connection
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise sqlite3.Error("cache is newer (v{}) than this hotin (v{})".format(version, SCHEMA_VERSION))
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tools'"
        ).fetchone() is not None
        if not exists:
            conn.execute("CREATE TABLE tools ({})".format(_TABLE_COLUMNS))
        else:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(tools)")}
            if "entity_type" not in columns or "entity_id" not in columns:
                conn.execute("DROP TABLE IF EXISTS tools_new")
                conn.execute("CREATE TABLE tools_new ({})".format(_TABLE_COLUMNS))
                # Copy oldest-first so the newest row wins each (entity_id, source).
                conn.execute(
                    """INSERT OR REPLACE INTO tools_new
                         (entity_type, entity_id, url, canonical_repo, name, source, signal_json, fetched_at)
                       SELECT 'repo', COALESCE(NULLIF(canonical_repo, ''), url), url,
                              canonical_repo, name, source, signal_json, fetched_at
                       FROM tools ORDER BY fetched_at ASC"""
                )
                conn.execute("DROP TABLE tools")
                conn.execute("ALTER TABLE tools_new RENAME TO tools")
                conn.execute("DROP TABLE IF EXISTS tools_fts")  # force FTS rebuild
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_fetched_at ON tools(fetched_at DESC)")
        # v2: the append-only observation time series (additive, safe on any prior version).
        conn.execute("CREATE TABLE IF NOT EXISTS observations ({})".format(_OBSERVATIONS_COLUMNS))
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_obs_entity ON observations(entity_type, entity_id, metric, observed_at)"
        )
        conn.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))
        conn.commit()

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
                """INSERT INTO tools (entity_type, entity_id, url, canonical_repo, name, source, signal_json, fetched_at)
                   VALUES (:entity_type, :entity_id, :url, :canonical_repo, :name, :source, :signal_json, :fetched_at)
                   ON CONFLICT(entity_type, entity_id, source) DO UPDATE SET
                     url=excluded.url,
                     canonical_repo=excluded.canonical_repo,
                     name=excluded.name,
                     signal_json=excluded.signal_json,
                     fetched_at=excluded.fetched_at""",
                normalized,
            )
            if self._fts_available:
                row = self._connection.execute(
                    "SELECT id FROM tools WHERE entity_type = ? AND entity_id = ? AND source = ?",
                    (normalized["entity_type"], normalized["entity_id"], normalized["source"]),
                ).fetchone()
                rowid = row[0]
                self._connection.execute("DELETE FROM tools_fts WHERE rowid = ?", (rowid,))
                self._connection.execute(
                    "INSERT INTO tools_fts (rowid, url, canonical_repo, name, source) VALUES (?, ?, ?, ?, ?)",
                    (rowid, normalized["url"], normalized["canonical_repo"], normalized["name"], normalized["source"]),
                )
            self._connection.commit()
        except sqlite3.Error as exc:
            self._activate_fallback(exc).upsert(normalized)

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Return matching observations; callers filter/merge in the engine."""
        if not query.strip():
            return []
        if self._fallback is not None:
            return self._fallback.search(query)
        try:
            if self._fts_available:
                try:
                    rows = self._connection.execute(
                        """SELECT t.* FROM tools t JOIN tools_fts f ON t.id = f.rowid
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
        """Return every observation; callers filter/merge in the engine."""
        if self._fallback is not None:
            return self._fallback.get_all()
        try:
            rows = self._connection.execute("SELECT * FROM tools ORDER BY fetched_at DESC").fetchall()
            return [self._row(row) for row in rows]
        except sqlite3.Error as exc:
            return self._activate_fallback(exc).get_all()

    def record_observations(self, observations: List[Dict[str, Any]]) -> None:
        """Append time-series samples idempotently (INSERT OR IGNORE on the key)."""
        rows = list(observations)
        if not rows:
            return
        if self._fallback is not None:
            self._fallback.record_observations(rows)
            return
        try:
            self._connection.executemany(
                """INSERT OR IGNORE INTO observations
                     (run_id, entity_type, entity_id, source, metric, value, observed_at)
                   VALUES (:run_id, :entity_type, :entity_id, :source, :metric, :value, :observed_at)""",
                rows,
            )
            self._connection.commit()
        except sqlite3.Error as exc:
            self._activate_fallback(exc).record_observations(rows)

    def observations_for(self, entity_type: str, entity_id: str, metric: str) -> List[Tuple[float, float]]:
        """Return ``(value, observed_at)`` samples for one metric, oldest first."""
        if self._fallback is not None:
            return self._fallback.observations_for(entity_type, entity_id, metric)
        try:
            rows = self._connection.execute(
                "SELECT value, observed_at FROM observations WHERE entity_type=? AND entity_id=? AND metric=? ORDER BY observed_at ASC",
                (entity_type, entity_id, metric),
            ).fetchall()
            return [(row[0], row[1]) for row in rows]
        except sqlite3.Error as exc:
            return self._activate_fallback(exc).observations_for(entity_type, entity_id, metric)

    def recent_observations(self, since: float) -> List[Dict[str, Any]]:
        """Every observation at/after ``since`` (for the brief's deltas)."""
        if self._fallback is not None:
            return self._fallback.recent_observations(since)
        try:
            rows = self._connection.execute(
                "SELECT entity_type, entity_id, source, metric, value, observed_at FROM observations WHERE observed_at >= ? ORDER BY observed_at ASC",
                (since,),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            return self._activate_fallback(exc).recent_observations(since)

    def prune_observations(self, cutoff: float) -> None:
        if self._fallback is not None:
            self._fallback.prune_observations(cutoff)
            return
        try:
            self._connection.execute("DELETE FROM observations WHERE observed_at < ?", (cutoff,))
            self._connection.commit()
        except sqlite3.Error:
            pass

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
