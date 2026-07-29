"""`first_seen` must survive re-sighting. That immutability is the whole point.

Before this, `fetched_at` was overwritten on every sighting, so the store held
LAST-seen and the board could never say when it first called a repo -- the one
claim that makes a public ledger worth citing.
"""

import sqlite3

import pytest

from hotin.cache import SCHEMA_VERSION, Cache


def _open(path):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return Cache(con)


def _rec(entity_id="a/b", **kw):
    base = {"entity_type": "repo", "entity_id": entity_id, "url": "u",
            "canonical_repo": entity_id, "name": entity_id, "source": "github",
            "signal_json": {"stars": 1}, "fetched_at": 1000.0}
    base.update(kw)
    return base


def _first_seen(path, entity_id="a/b"):
    con = sqlite3.connect(str(path))
    try:
        row = con.execute("SELECT first_seen, fetched_at FROM tools WHERE entity_id = ?",
                          (entity_id,)).fetchone()
        return row
    finally:
        con.close()


def test_first_seen_is_set_on_the_first_sighting(tmp_path):
    db = tmp_path / "c.db"
    cache = _open(db)
    cache.upsert(_rec())
    first, fetched = _first_seen(db)
    assert first == 1000.0 and fetched == 1000.0


def test_re_sighting_moves_fetched_at_but_never_first_seen(tmp_path):
    """The core guarantee."""
    db = tmp_path / "c.db"
    cache = _open(db)
    cache.upsert(_rec(fetched_at=1000.0))
    for later in (2000.0, 3000.0, 9999.0):
        cache.upsert(_rec(fetched_at=later))
    first, fetched = _first_seen(db)
    assert first == 1000.0, "first_seen moved -- the ledger claim is worthless"
    assert fetched == 9999.0, "fetched_at should still track the latest sighting"


def test_an_explicit_first_seen_is_honoured_once(tmp_path):
    db = tmp_path / "c.db"
    cache = _open(db)
    cache.upsert(_rec(fetched_at=5000.0, first_seen=42.0))
    assert _first_seen(db)[0] == 42.0
    cache.upsert(_rec(fetched_at=6000.0, first_seen=99.0))
    assert _first_seen(db)[0] == 42.0, "a later claim must not rewrite history"


def test_distinct_entities_keep_distinct_first_seen(tmp_path):
    db = tmp_path / "c.db"
    cache = _open(db)
    cache.upsert(_rec("a/one", fetched_at=100.0))
    cache.upsert(_rec("a/two", fetched_at=200.0))
    cache.upsert(_rec("a/one", fetched_at=300.0))
    assert _first_seen(db, "a/one")[0] == 100.0
    assert _first_seen(db, "a/two")[0] == 200.0


def test_migration_adds_first_seen_to_a_v2_database(tmp_path):
    """Additive migration on a store that predates the column."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(str(db))
    con.execute("""CREATE TABLE tools (id INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL DEFAULT 'repo', entity_id TEXT NOT NULL,
        url TEXT NOT NULL, canonical_repo TEXT, name TEXT NOT NULL,
        source TEXT NOT NULL, signal_json TEXT NOT NULL, fetched_at REAL NOT NULL,
        UNIQUE(entity_type, entity_id, source))""")
    con.execute("INSERT INTO tools (entity_type, entity_id, url, canonical_repo, name,"
                " source, signal_json, fetched_at) VALUES"
                " ('repo','old/repo','u','old/repo','n','github','{}', 777.0)")
    con.execute("PRAGMA user_version = 2")
    con.commit(); con.close()

    _open(db)  # migrate
    first, fetched = _first_seen(db, "old/repo")
    # Backfilled from fetched_at, which is LAST-seen: an upper bound, not exact.
    assert first == 777.0 == fetched
    con = sqlite3.connect(str(db))
    assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    con.close()


def test_a_migrated_row_then_keeps_its_first_seen_on_re_sighting(tmp_path):
    """The backfilled bound must not drift later on every subsequent run."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(str(db))
    con.execute("""CREATE TABLE tools (id INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL DEFAULT 'repo', entity_id TEXT NOT NULL,
        url TEXT NOT NULL, canonical_repo TEXT, name TEXT NOT NULL,
        source TEXT NOT NULL, signal_json TEXT NOT NULL, fetched_at REAL NOT NULL,
        UNIQUE(entity_type, entity_id, source))""")
    con.execute("INSERT INTO tools (entity_type, entity_id, url, canonical_repo, name,"
                " source, signal_json, fetched_at) VALUES"
                " ('repo','a/b','u','a/b','n','github','{}', 777.0)")
    con.execute("PRAGMA user_version = 2")
    con.commit(); con.close()

    cache = _open(db)
    cache.upsert(_rec(fetched_at=8888.0))
    first, fetched = _first_seen(db)
    assert first == 777.0, "the migrated bound drifted forward"
    assert fetched == 8888.0
