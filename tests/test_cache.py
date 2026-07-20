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


def test_open_error_degrades_to_memory_cache(monkeypatch):
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache.sqlite3, "connect", unavailable)
    opened = cache.open_cache()

    assert isinstance(opened, cache.MemoryCache)
    opened.upsert(record("Memory Tool"))
    assert [item["name"] for item in opened.search("Memory")] == ["Memory Tool"]
