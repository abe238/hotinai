import math
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from hotin import engine
from hotin.cache import MemoryCache
from hotin.health import SourceStatus


def record(source="github", **overrides):
    base = {
        "url": "https://github.com/acme/tool",
        "canonical_repo": "acme/tool",
        "name": "Acme Tool",
        "source": source,
        "signal": {},
        "meta": {},
        "fetched_at": time.time(),
    }
    base.update(overrides)
    return base


def test_merge_by_repo_unions_source_signal_and_meta():
    merged = engine.merge_by_repo([
        record("github", signal={"stars": 42}, meta={"topics": ["agent"]}),
        record("hn", name="Acme Tool — agent framework", signal={"hn_points": 99}, meta={"hn_id": "1"}),
    ])

    result = merged["acme/tool"]
    assert result["sources"] == {"github", "hn"}
    assert result["name"] == "Acme Tool — agent framework"
    assert result["signal"] == {"stars": 42, "hn_points": 99}
    assert result["meta"] == {"topics": ["agent"], "hn_id": "1"}
    assert result["signal_by_source"] == {"github": {"stars": 42}, "hn": {"hn_points": 99}}


def test_merge_by_repo_canonicalizes_case_variants():
    merged = engine.merge_by_repo([
        record("github", canonical_repo="Owner/Repo"),
        record("hn", canonical_repo="owner/repo"),
    ])

    assert set(merged) == {"owner/repo"}


def test_multiple_source_observations_keep_real_urls_and_merge(monkeypatch):
    cache = MemoryCache()
    first = SimpleNamespace(SOURCE="first")
    second = SimpleNamespace(SOURCE="second")
    first.fetch = lambda **kwargs: {"records": [record("first")], "status": "ok", "detail": None}
    second.fetch = lambda **kwargs: {"records": [record("second")], "status": "ok", "detail": None}
    monkeypatch.setattr(engine, "SOURCES", (first, second))

    engine.fetch_all({}, cache=cache)

    cached = cache.get_all()
    assert {item["url"] for item in cached} == {"https://github.com/acme/tool"}
    assert len(cached) == 2
    assert engine.merge_by_repo(cached)["acme/tool"]["sources"] == {"first", "second"}


def test_score_is_finite_and_uses_all_major_components():
    now = time.time()
    repo = engine.merge_by_repo([record(
        "github",
        signal={"stars": 1000, "created_at": datetime.fromtimestamp(now, timezone.utc).isoformat(), "pushed_at": now},
        meta={"description": "agent", "top_starrers": [{"rank": 10}]},
    ), record("hn", signal={"hn_points": 50}), record("npm", signal={"npm_downloads_week": 10000}),
       record("smartmoney", signal={"smartmoney_starrers": 3, "smartmoney_ai1000": 2})])["acme/tool"]

    scored = engine.score_repo(repo, now=now)
    assert math.isfinite(scored["score"])
    assert scored["score"] > 0
    assert scored["momentum"] > 0
    assert scored["credibility"] > 0
    assert scored["signal_score"] > 0


def test_corroboration_increases_otherwise_identical_score():
    now = time.time()
    single = engine.merge_by_repo([record("github", signal={"stars": 100, "pushed_at": now})])["acme/tool"]
    three = engine.merge_by_repo([
        record("github", signal={"stars": 100, "pushed_at": now}),
        record("hn", signal={}), record("reddit", signal={}),
    ])["acme/tool"]

    assert engine.score_repo(three, now=now)["score"] > engine.score_repo(single, now=now)["score"]


def test_fresh_repository_outranks_otherwise_identical_stale_one():
    now = time.time()
    fresh = engine.merge_by_repo([record(signal={"stars": 100, "pushed_at": now})])["acme/tool"]
    stale = engine.merge_by_repo([record(signal={"stars": 100, "pushed_at": now - 365 * 86400}, fetched_at=now - 365 * 86400)])["acme/tool"]

    assert engine.score_repo(fresh, now=now)["score"] > engine.score_repo(stale, now=now)["score"]


def test_hostile_numeric_signal_cannot_make_score_nonfinite():
    repo = engine.merge_by_repo([record(signal={"stars": float("inf"), "hn_points": float("inf"), "youtube_views": float("inf")})])["acme/tool"]
    scored = engine.score_repo(repo)
    assert math.isfinite(scored["score"])


def test_npm_growth_drives_momentum_instead_of_raw_download_popularity():
    now = time.time()
    popular = engine.merge_by_repo([record("npm", signal={"npm_downloads_week": 1_000_000, "npm_growth": 0, "pushed_at": now})])["acme/tool"]
    growing = engine.merge_by_repo([record("npm", signal={"npm_downloads_week": 10, "npm_growth": 0.5, "pushed_at": now})])["acme/tool"]

    assert engine.score_repo(growing, now=now)["momentum"] > engine.score_repo(popular, now=now)["momentum"]


def test_credibility_cap_keeps_corroborated_momentum_ahead_of_smart_money_alone():
    now = time.time()
    smart_money_only = engine.merge_by_repo([record("smartmoney", signal={"smartmoney_starrers": 100, "smartmoney_ai1000": 50, "pushed_at": now})])["acme/tool"]
    corroborated = engine.merge_by_repo([
        record("trends", signal={"trend_total_score": 100, "pushed_at": now}),
        record("hn", signal={}), record("reddit", signal={}),
    ])["acme/tool"]

    assert engine.score_repo(corroborated, now=now)["score"] > engine.score_repo(smart_money_only, now=now)["score"]


def test_fetch_all_starts_every_adapter_and_catches_errors(monkeypatch):
    cache = MemoryCache()
    called = []

    def success(name):
        def fetch(**kwargs):
            called.append(name)
            return {"records": [record(name)], "status": "ok", "detail": None}
        return fetch

    for source in engine.SOURCES:
        monkeypatch.setattr(source, "fetch", success(source.__name__.rsplit(".", 1)[-1]))
    monkeypatch.setattr(engine.github, "fetch", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    statuses = engine.fetch_all({}, cache=cache, timeout=0.5)
    assert set(called) == {source.__name__.rsplit(".", 1)[-1] for source in engine.SOURCES if source is not engine.github}
    github_status = next(status for status in statuses if status.source == "github")
    assert github_status.status == "error"
    assert "boom" in (github_status.detail or "")
    assert len(cache.get_all()) == 7


def test_fetch_all_timeout_does_not_wait_for_slow_adapter(monkeypatch):
    cache = MemoryCache()

    def slow(**kwargs):
        time.sleep(0.2)
        return {"records": [], "status": "empty", "detail": None}

    monkeypatch.setattr(engine.github, "fetch", slow)
    for source in engine.SOURCES[1:]:
        monkeypatch.setattr(source, "fetch", lambda **kwargs: {"records": [], "status": "empty", "detail": None})

    started = time.monotonic()
    statuses = engine.fetch_all({}, cache=cache, timeout=0.02)
    elapsed = time.monotonic() - started
    assert elapsed < 0.15
    assert next(status for status in statuses if status.source == "github").detail == "timed out"
    assert sum(status.status == "empty" for status in statuses) == 7


def test_fetch_all_has_one_timeout_budget_for_the_entire_batch(monkeypatch):
    cache = MemoryCache()
    slow_sources = tuple(SimpleNamespace(SOURCE="slow{}".format(index)) for index in range(4))
    fast_source = SimpleNamespace(SOURCE="fast")

    def slow(**kwargs):
        time.sleep(0.2)
        return {"records": [], "status": "empty", "detail": None}

    for source in slow_sources:
        source.fetch = slow
    fast_source.fetch = lambda **kwargs: {"records": [], "status": "empty", "detail": None}
    monkeypatch.setattr(engine, "SOURCES", slow_sources + (fast_source,))

    started = time.monotonic()
    statuses = engine.fetch_all({}, cache=cache, timeout=0.03)
    elapsed = time.monotonic() - started

    assert elapsed < 0.08
    assert {status.source for status in statuses if status.detail == "timed out"} == {source.SOURCE for source in slow_sources}
    assert next(status for status in statuses if status.source == "fast").status == "empty"


def test_fetch_all_serves_fresh_source_cache_and_refetches_stale_source(monkeypatch):
    cache = MemoryCache()
    fresh = SimpleNamespace(SOURCE="fresh")
    stale = SimpleNamespace(SOURCE="stale")
    calls = []
    fresh.fetch = lambda **kwargs: calls.append("fresh")
    stale.fetch = lambda **kwargs: (calls.append("stale") or {"records": [], "status": "empty", "detail": None})
    cache.upsert(record("fresh", fetched_at=time.time()))
    cache.upsert(record("stale", url="https://github.com/acme/stale", canonical_repo="acme/stale", fetched_at=time.time() - 301))
    monkeypatch.setattr(engine, "SOURCES", (fresh, stale))

    statuses = engine.fetch_all({}, cache=cache, ttl=300)

    assert calls == ["stale"]
    assert next(status for status in statuses if status.source == "fresh").detail == "served from cache"


def test_cache_payload_round_trips_signal_and_meta_through_engine_fetch(monkeypatch):
    cache = MemoryCache()
    for source in engine.SOURCES:
        monkeypatch.setattr(source, "fetch", lambda **kwargs: {"records": [], "status": "empty", "detail": None})
    monkeypatch.setattr(engine.github, "fetch", lambda **kwargs: {"records": [record(signal={"stars": 4}, meta={"topics": ["agent"]})], "status": "ok", "detail": None})

    engine.fetch_all({}, cache=cache)
    merged = engine.merge_by_repo(cache.get_all())["acme/tool"]
    assert merged["signal"] == {"stars": 4}
    assert merged["meta"] == {"topics": ["agent"]}
