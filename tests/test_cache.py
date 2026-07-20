import sqlite3

from hotin import cache


def record(name="Useful Tool"):
    return {
        "url": "https://github.com/example/{}".format(name.replace(" ", "-").lower()),
        "canonical_repo": "example/{}".format(name.replace(" ", "-").lower()),
        "name": name,
        "source": "test",
        "signal_json": {"stars": 1},
        "fetched_at": 1,
    }


def test_insert_and_search(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    opened = cache.open_cache()
    opened.upsert(record())

    assert [item["name"] for item in opened.search("Useful")] == ["Useful Tool"]
    assert len(opened.get_all()) == 1
    opened.close()


def test_cache_keeps_one_observation_per_url_and_source_without_fts_cross_product():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    opened = cache.Cache(connection)
    shared = record("Shared Tool")
    other_source = dict(shared, source="other")
    opened.upsert(shared)
    opened.upsert(other_source)

    assert len(opened.get_all()) == 2
    assert len(opened.search("Shared")) == 2
    opened.close()


def test_fts_unavailable_uses_like_search(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    def no_fts(self):
        raise sqlite3.OperationalError("no such module: fts5")

    monkeypatch.setattr(cache.Cache, "_create_fts", no_fts)
    opened = cache.Cache(connection)
    opened.upsert(record("Fallback Finder"))

    assert opened._fts_available is False
    assert [item["name"] for item in opened.search("Finder")] == ["Fallback Finder"]
    opened.close()


def test_fts_and_like_search_have_matching_prefix_and_literal_wildcard_behavior(monkeypatch):
    fts_connection = sqlite3.connect(":memory:")
    fts_connection.row_factory = sqlite3.Row
    fts_cache = cache.Cache(fts_connection)
    fts_cache.upsert(record("Useful Tool"))
    fts_cache.upsert(record("Another Tool"))

    assert fts_cache._fts_available is True
    assert [item["name"] for item in fts_cache.search("Use")] == ["Useful Tool"]
    assert fts_cache.search("%") == []
    assert fts_cache.search("   ") == []
    fts_cache.close()

    def no_fts(self):
        raise sqlite3.OperationalError("no such module: fts5")

    monkeypatch.setattr(cache.Cache, "_create_fts", no_fts)
    like_connection = sqlite3.connect(":memory:")
    like_connection.row_factory = sqlite3.Row
    like_cache = cache.Cache(like_connection)
    like_cache.upsert(record("Useful Tool"))
    like_cache.upsert(record("Another Tool"))

    assert like_cache._fts_available is False
    assert [item["name"] for item in like_cache.search("Use")] == ["Useful Tool"]
    assert like_cache.search("%") == []
    assert like_cache.search("   ") == []
    like_cache.close()


def test_fts_creation_backfills_existing_like_only_cache(tmp_path, monkeypatch):
    database = tmp_path / "cache.db"
    connection = sqlite3.connect(str(database))
    connection.row_factory = sqlite3.Row
    original_create_fts = cache.Cache._create_fts

    def no_fts(self):
        raise sqlite3.OperationalError("no such module: fts5")

    monkeypatch.setattr(cache.Cache, "_create_fts", no_fts)
    like_cache = cache.Cache(connection)
    like_cache.upsert(record("Backfilled Tool"))
    like_cache.close()

    monkeypatch.setattr(cache.Cache, "_create_fts", original_create_fts)
    connection = sqlite3.connect(str(database))
    connection.row_factory = sqlite3.Row
    fts_cache = cache.Cache(connection)

    assert fts_cache._fts_available is True
    assert [item["name"] for item in fts_cache.search("Backfilled")] == ["Backfilled Tool"]
    fts_cache.close()


def test_open_error_degrades_to_memory_cache(monkeypatch):
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache.sqlite3, "connect", unavailable)
    opened = cache.open_cache()

    assert isinstance(opened, cache.MemoryCache)
    opened.upsert(record("Memory Tool"))
    assert [item["name"] for item in opened.search("Memory")] == ["Memory Tool"]


def _legacy_db(path, unique_sql, rows):
    """Create a pre-entity-model DB at `path` with the given UNIQUE clause."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE tools (id INTEGER PRIMARY KEY, url TEXT NOT NULL, "
        "canonical_repo TEXT, name TEXT NOT NULL, source TEXT NOT NULL, "
        "signal_json TEXT NOT NULL, fetched_at REAL NOT NULL{u})".format(u=unique_sql)
    )
    conn.executemany(
        "INSERT INTO tools (url, canonical_repo, name, source, signal_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)", rows,
    )
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()


def _open(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return cache.Cache(conn)


def test_migrates_legacy_url_unique_schema_preserving_rows(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_db(path, ", UNIQUE(url)", [
        ("https://github.com/a/b", "a/b", "AB", "github", '{"stars": 1}', 100.0),
        ("https://github.com/c/d", "c/d", "CD", "hn", '{"hn_points": 9}', 200.0),
    ])
    c = _open(path)
    rows = c.get_all()
    assert {r["entity_type"] for r in rows} == {"repo"}
    assert {r["entity_id"] for r in rows} == {"a/b", "c/d"}
    assert c._connection.execute("PRAGMA user_version").fetchone()[0] == cache.SCHEMA_VERSION
    # upsert (which uses ON CONFLICT(entity_type, entity_id, source)) works now.
    c.upsert(record("New One"))
    assert any(r["name"] == "New One" for r in c.get_all())
    c.close()


def test_migrates_shipped_url_source_unique_schema(tmp_path):
    path = tmp_path / "shipped.db"
    _legacy_db(path, ", UNIQUE(url, source)", [
        ("https://github.com/a/b", "a/b", "AB", "github", '{"stars": 1}', 100.0),
    ])
    c = _open(path)
    rows = c.get_all()
    assert len(rows) == 1 and rows[0]["entity_type"] == "repo" and rows[0]["entity_id"] == "a/b"
    c.close()


def test_fresh_db_gets_entity_schema(tmp_path):
    c = _open(tmp_path / "fresh.db")
    cols = {r[1] for r in c._connection.execute("PRAGMA table_info(tools)")}
    assert "entity_type" in cols and "entity_id" in cols
    assert c._connection.execute("PRAGMA user_version").fetchone()[0] == cache.SCHEMA_VERSION
    c.close()


def test_newer_db_degrades_to_memory_rather_than_corrupt(tmp_path):
    path = tmp_path / "future.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE tools ({})".format(cache._TABLE_COLUMNS))
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()
    c = _open(path)
    # Refused the migration and fell back to memory (no crash); still usable.
    assert c._fallback is not None
    c.upsert(record("Safe"))
    assert any(r["name"] == "Safe" for r in c.get_all())
    c.close()


def test_paper_and_model_rows_do_not_leak_into_repo_merge(tmp_path):
    from hotin import engine
    c = _open(tmp_path / "mixed.db")
    c.upsert({"entity_type": "repo", "entity_id": "acme/tool", "canonical_repo": "acme/tool",
              "url": "https://github.com/acme/tool", "name": "Acme", "source": "github",
              "signal_json": {"stars": 10}, "fetched_at": 1000.0})
    c.upsert({"entity_type": "paper", "entity_id": "2601.12345", "canonical_repo": None,
              "url": "https://arxiv.org/abs/2601.12345", "name": "A Paper", "source": "hfpapers",
              "signal_json": {"upvotes": 99}, "fetched_at": 1000.0})
    c.upsert({"entity_type": "model", "entity_id": "org/model", "canonical_repo": None,
              "url": "https://huggingface.co/org/model", "name": "org/model", "source": "hfmodels",
              "signal_json": {"downloads": 5}, "fetched_at": 1000.0})
    merged = engine.merge_by_repo(c.get_all())
    assert set(merged) == {"acme/tool"}  # only the repo; paper/model excluded
    c.close()
