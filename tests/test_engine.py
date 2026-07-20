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


def test_freshness_tracks_activity_not_fetch_time():
    now = time.time()
    # A repo trending on HN right now (fetched_at = now) but last pushed 3 years
    # ago must NOT be tagged fresh, and its decay factor must actually bite —
    # freshness is measured from pushed_at, not the cache-write time.
    dormant = engine.merge_by_repo([
        record("hn", signal={"hn_points": 500, "pushed_at": now - 3 * 365 * 86400}, fetched_at=now)
    ])["acme/tool"]
    scored = engine.score_repo(dormant, now=now)
    assert "fresh" not in scored["badges"]
    assert scored["freshness_factor"] == 0.2  # fully decayed at 3 years
    assert scored["freshness_days"] > 1000


def test_missing_activity_data_is_neutral_not_penalized():
    now = time.time()
    # Surfaced only via a source with no activity timestamp (e.g. HN with no
    # pushed_at): don't penalize data we don't have, and don't claim freshness.
    unknown = engine.merge_by_repo([
        record("hn", signal={"hn_points": 500}, fetched_at=now)
    ])["acme/tool"]
    scored = engine.score_repo(unknown, now=now)
    assert scored["freshness_factor"] == 1.0
    assert scored["freshness_days"] is None
    assert "fresh" not in scored["badges"]


def test_evidence_window_drops_stale_source_from_corroboration():
    now = time.time()
    fresh_run = now
    stale_run = now - 60 * 86400  # this source stopped re-surfacing the repo 60d ago
    records = [
        record("github", signal={"stars": 100, "pushed_at": now}, fetched_at=fresh_run),
        record("hn", signal={"hn_points": 500}, fetched_at=stale_run),
    ]
    # No window: both sources count -> corroboration multiplier applies.
    both = engine.merge_by_repo(records, now=now)["acme/tool"]
    assert both["sources"] == {"github", "hn"}
    # With a 21-day window: the stale hn evidence is dropped, so corroboration
    # reflects only what is currently hot.
    windowed = engine.merge_by_repo(records, max_age_days=21.0, now=now)["acme/tool"]
    assert windowed["sources"] == {"github"}
    assert engine.score_repo(windowed, now=now)["corroboration"] == 1.0
    assert engine.score_repo(both, now=now)["corroboration"] == 1.25


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
    assert len(cache.get_all()) == 8


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
    assert sum(status.status == "empty" for status in statuses) == 8


def test_fetch_all_has_one_timeout_budget_for_the_entire_batch(monkeypatch):
    cache = MemoryCache()
    # 10 slow sources make the concurrent-vs-sequential gap wide: one shared
    # timeout budget finishes in ~timeout, while a per-future (sequential) wait
    # would take ~10x that. A generous absolute threshold between the two keeps
    # the assertion meaningful without flaking on a loaded CI runner.
    slow_sources = tuple(SimpleNamespace(SOURCE="slow{}".format(index)) for index in range(10))
    fast_source = SimpleNamespace(SOURCE="fast")

    def slow(**kwargs):
        time.sleep(0.3)
        return {"records": [], "status": "empty", "detail": None}

    for source in slow_sources:
        source.fetch = slow
    fast_source.fetch = lambda **kwargs: {"records": [], "status": "empty", "detail": None}
    monkeypatch.setattr(engine, "SOURCES", slow_sources + (fast_source,))

    started = time.monotonic()
    statuses = engine.fetch_all({}, cache=cache, timeout=0.2)
    elapsed = time.monotonic() - started

    # One shared budget: ~0.2s + thread overhead. A per-future (sequential) wait
    # would be ~2.0s (10 x 0.2). The 1.0s threshold leaves ~0.8s of overhead
    # headroom on the concurrent path while staying well below sequential.
    assert elapsed < 1.0
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


def test_curated_youtube_flag_is_a_bounded_nudge_not_a_source():
    now = time.time()
    plain = engine.merge_by_repo([record("youtube", signal={"youtube_views": 1000})])["acme/tool"]
    curated = engine.merge_by_repo([record("youtube", signal={"youtube_views": 1000}, meta={"youtube_curated": True})])["acme/tool"]
    plain_score = engine.score_repo(plain, now=now)["score"]
    curated_score = engine.score_repo(curated, now=now)["score"]
    assert curated_score > plain_score          # curated helps
    assert curated_score - plain_score <= 1.0   # but is bounded, not a 1.25x source multiplier
    # it did not add a phantom source
    assert engine.score_repo(curated, now=now)["corroboration"] == 1.0


def test_merge_by_entity_is_type_scoped_and_ranks_by_metric():
    now = time.time()
    rows = [
        {"entity_type": "model", "entity_id": "org/big", "url": "https://huggingface.co/org/big",
         "name": "org/big", "source": "hfmodels", "signal": {"model_downloads": 100000, "model_likes": 10}, "meta": {}, "fetched_at": now},
        {"entity_type": "model", "entity_id": "org/small", "url": "https://huggingface.co/org/small",
         "name": "org/small", "source": "hfmodels", "signal": {"model_downloads": 5, "model_likes": 1}, "meta": {}, "fetched_at": now},
        {"entity_type": "paper", "entity_id": "2601.1", "url": "u", "name": "P",
         "source": "hfpapers", "signal": {"paper_upvotes": 9}, "meta": {}, "fetched_at": now},
        {"entity_type": "repo", "entity_id": "a/b", "canonical_repo": "a/b", "url": "https://github.com/a/b",
         "name": "a/b", "source": "github", "signal": {"stars": 5}, "meta": {}, "fetched_at": now},
    ]
    models = engine.merge_by_entity(rows, "model")
    assert set(models) == {"org/big", "org/small"}          # type-scoped: no paper/repo
    ranked = engine.rank_entities(models, {"model_downloads": 1.0, "model_likes": 0.5})
    assert [e["entity_id"] for e in ranked] == ["org/big", "org/small"]  # more downloads ranks first
    assert ranked[0]["score"] > 0
    assert engine.merge_by_entity(rows, "paper").keys() == {"2601.1"}


def test_smol_mention_is_a_flag_not_a_corroboration_source():
    now = time.time()
    # github + smolai on the same repo: smolai must NOT count as a 2nd source.
    merged = engine.merge_by_repo([
        record("github", signal={"stars": 100, "pushed_at": now}),
        record("smolai", signal={}, meta={"smol_mention": True}),
    ], now=now)["acme/tool"]
    scored = engine.score_repo(merged, now=now)
    assert "smolai" in merged["sources"]        # recorded as provenance
    assert scored["corroboration"] == 1.0       # but excluded from corroboration
    # a real 2nd source (hn) WOULD raise corroboration to 1.25
    two_real = engine.merge_by_repo([
        record("github", signal={"stars": 100, "pushed_at": now}), record("hn", signal={}),
    ], now=now)["acme/tool"]
    assert engine.score_repo(two_real, now=now)["corroboration"] == 1.25
    assert scored["score"] > engine.score_repo(
        engine.merge_by_repo([record("github", signal={"stars": 100, "pushed_at": now})], now=now)["acme/tool"], now=now
    )["score"]  # the flag still gives a small nudge


def test_cross_entity_bridge_boosts_paper_backed_repo():
    now = time.time()
    rows = [
        record("github", signal={"stars": 100, "pushed_at": now}),
        {"entity_type": "paper", "entity_id": "2601.1", "url": "u", "name": "A Paper",
         "source": "hfpapers", "signal": {"paper_upvotes": 50},
         "meta": {"linked_repo": "acme/tool"}, "fetched_at": now},
    ]
    links = engine.cross_entity_repo_links(rows, now=now)
    assert "acme/tool" in links
    merged = engine.merge_by_repo(rows, now=now)      # the paper is NOT a repo row
    assert set(merged) == {"acme/tool"}
    repo = merged["acme/tool"]
    repo["meta"]["paper_backed"] = True
    scored = engine.score_repo(repo, now=now)
    assert "paper-backed" in scored["badges"]
    plain = engine.score_repo(
        engine.merge_by_repo([record("github", signal={"stars": 100, "pushed_at": now})], now=now)["acme/tool"], now=now)
    assert scored["score"] > plain["score"]          # bounded boost, but real
    # a stale paper link stops counting
    stale_rows = [rows[0], dict(rows[1], fetched_at=now - 60 * 86400)]
    assert engine.cross_entity_repo_links(stale_rows, max_age_days=21.0, now=now) == set()


def test_series_velocity_states_and_reset_handling():
    now = time.time()
    day = 86400.0
    assert engine.series_velocity([(100, now)])[2] == "unknown"          # one sample
    assert engine.series_velocity([(100, now), (100, now)])[2] == "unknown"  # zero span
    v, accel, state = engine.series_velocity([(100, now - 2 * day), (300, now)])
    assert state == "rising" and v == 100.0                              # +200 over 2 days
    # a counter that decreases (reset) floors velocity at 0, not negative
    v2, _, state2 = engine.series_velocity([(500, now - day), (100, now)])
    assert v2 == 0.0 and state2 == "flat"


def test_rising_velocity_boosts_and_badges_only_with_history():
    now = time.time()
    day = 86400.0

    class Store:
        def __init__(self, samples):
            self._samples = samples
        def observations_for(self, entity_type, entity_id, metric):
            return self._samples

    base_repo = engine.merge_by_repo([record("github", signal={"stars": 300, "pushed_at": now})], now=now)
    cold = engine.score_repo(base_repo["acme/tool"], now=now)  # no annotation -> neutral
    assert "rising" not in cold["badges"] and "viral" not in cold["badges"]

    rising = engine.merge_by_repo([record("github", signal={"stars": 300, "pushed_at": now})], now=now)
    engine.annotate_velocity(rising, Store([(100, now - 2 * day), (300, now)]))
    scored = engine.score_repo(rising["acme/tool"], now=now)
    assert "rising" in scored["badges"]
    assert scored["score"] > cold["score"]                     # rising history helps, bounded

    unknown = engine.merge_by_repo([record("github", signal={"stars": 300, "pushed_at": now})], now=now)
    engine.annotate_velocity(unknown, Store([]))               # empty store -> unknown -> neutral
    assert engine.score_repo(unknown["acme/tool"], now=now)["score"] == cold["score"]


def test_badge_vocabulary_is_tight_and_word_of_mouth():
    now = time.time()
    created = datetime.fromtimestamp(now, timezone.utc).isoformat()
    # young + recently active -> a single "fresh" (old "new" merged in)
    fresh = engine.merge_by_repo([record("github", signal={"stars": 100, "created_at": created, "pushed_at": now})], now=now)["acme/tool"]
    fb = engine.score_repo(fresh, now=now)["badges"]
    assert "fresh" in fb and "new" not in fb
    # corroboration folded into the score, not badged; source tags demoted
    three = engine.merge_by_repo([
        record("github", signal={"stars": 100, "pushed_at": now}), record("hn", signal={}), record("reddit", signal={}),
    ], now=now)["acme/tool"]
    tb = engine.score_repo(three, now=now)["badges"]
    assert "corroborated" not in tb and "hn" not in tb and "reddit" not in tb
    # Smart Money = AI1000 stars AND corroboration (>=2 sources); alone is not enough
    sm_alone = engine.merge_by_repo([record("smartmoney", signal={"smartmoney_starrers": 50, "pushed_at": now})], now=now)["acme/tool"]
    assert "smart-money" not in engine.score_repo(sm_alone, now=now)["badges"]
    sm_backed = engine.merge_by_repo([
        record("smartmoney", signal={"smartmoney_starrers": 50, "pushed_at": now}),
        record("github", signal={"stars": 10, "pushed_at": now}),
    ], now=now)["acme/tool"]
    assert "smart-money" in engine.score_repo(sm_backed, now=now)["badges"]
