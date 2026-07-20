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
