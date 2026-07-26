from hotin.sources import _insider_roster, insiders


def _events(*triples):
    """(username, repo, starred_at) -> shared-core event dicts."""
    return [
        {"username": u, "canonical_repo": r, "starred_at": s,
         "stargazers_count": 10, "description": None}
        for (u, r, s) in triples
    ]


def test_maps_roster_events_to_insider_records_deduped_across_members(monkeypatch):
    # Two roster members star the same repo -> one record, insider_stars == 2.
    _insider_roster._reset_memo()
    events = _events(
        ("karpathy", "owner/repo", "2026-07-24T00:00:00Z"),
        ("simonw", "owner/repo", "2026-07-25T00:00:00Z"),  # 2nd starrer, more recent
        ("simonw", "solo/pick", "2026-07-20T00:00:00Z"),
    )
    monkeypatch.setattr(_insider_roster, "poll_roster", lambda config=None, **kw: events)
    result = insiders.fetch(config={"GITHUB_TOKEN": "x"})
    assert result["status"] == "ok"
    recs = {r["entity_id"]: r for r in result["records"]}

    top = recs["owner/repo"]
    assert top["source"] == "insiders"
    assert top["url"] == "https://github.com/owner/repo"
    assert top["signal"]["insider_stars"] == 2          # both members counted once
    assert top["signal"]["most_recent_star_at"] == "2026-07-25T00:00:00Z"  # most recent wins
    assert top["meta"]["insiders"] == ["karpathy", "simonw"]
    assert top["meta"]["top_insider"] == "karpathy"

    assert recs["solo/pick"]["signal"]["insider_stars"] == 1


def test_records_sorted_by_distinct_starrers_desc(monkeypatch):
    _insider_roster._reset_memo()
    events = _events(
        ("a", "solo/one", "2026-07-24T00:00:00Z"),
        ("a", "shared/two", "2026-07-24T00:00:00Z"),
        ("b", "shared/two", "2026-07-24T00:00:00Z"),
    )
    monkeypatch.setattr(_insider_roster, "poll_roster", lambda config=None, **kw: events)
    result = insiders.fetch(config={"GITHUB_TOKEN": "x"})
    assert [r["entity_id"] for r in result["records"]] == ["shared/two", "solo/one"]


def test_missing_token_is_a_loud_error_not_silent(monkeypatch):
    # Regression pin: an unauthenticated poll degrades to 60/hr and would pass
    # locally while failing in CI -- the adapter must surface it as an error.
    _insider_roster._reset_memo()
    assert insiders.fetch(config={})["status"] == "error"
    assert insiders.fetch()["status"] == "error"  # no config at all


def test_empty_window_is_empty_not_error(monkeypatch):
    _insider_roster._reset_memo()
    monkeypatch.setattr(_insider_roster, "poll_roster", lambda config=None, **kw: [])
    assert insiders.fetch(config={"GITHUB_TOKEN": "x"})["status"] == "empty"


def test_fetch_caps_to_limit(monkeypatch):
    _insider_roster._reset_memo()
    events = _events(
        ("a", "b/two", "2026-07-24T00:00:00Z"),
        ("a", "a/one", "2026-07-24T00:00:00Z"),
        ("b", "b/two", "2026-07-24T00:00:00Z"),  # b/two has 2 starrers -> ranks first
    )
    monkeypatch.setattr(_insider_roster, "poll_roster", lambda config=None, **kw: events)
    result = insiders.fetch(limit=1, config={"GITHUB_TOKEN": "x"})
    assert len(result["records"]) == 1 and result["records"][0]["entity_id"] == "b/two"


def test_fetch_zero_limit_is_empty():
    assert insiders.fetch(limit=0)["status"] == "empty"


def test_selftest():
    insiders.selftest()


# --- backfill_created_at: unchanged behavior, kept from the scraper era ---

class FakeCache:
    def __init__(self, rows):
        self.rows = rows
        self.upserts = []

    def get_all(self):
        return list(self.rows)

    def upsert(self, record):
        self.upserts.append(record)


def _ins_row(rid, signal):
    import json as _json
    return {"entity_type": "repo", "entity_id": rid, "source": "insiders",
            "fetched_at": 7.0,
            "signal_json": _json.dumps({"signal": signal, "meta": {"insiders": []}})}


def test_backfill_created_at_heals_and_remembers_failures(monkeypatch):
    cache = FakeCache([
        _ins_row("a/new", {"insider_stars": 2}),                      # healed
        _ins_row("b/known", {"insider_stars": 1, "created_at": "2026-07-20"}),  # skipped
        _ins_row("c/gone", {"insider_stars": 1}),                     # 404 -> "" cached
        {"entity_type": "repo", "entity_id": "x/y", "source": "github",
         "signal_json": "{}"},                                        # not insiders
    ])
    monkeypatch.setattr(insiders, "fetch_created_at",
                        lambda rid, token=None: {"a/new": "2026-07-22T01:00:00Z"}.get(rid))
    healed = insiders.backfill_created_at(cache)
    assert healed == 2
    sig = {u["entity_id"]: u["signal_json"]["signal"] for u in cache.upserts}
    assert sig["a/new"]["created_at"] == "2026-07-22T01:00:00Z"
    assert sig["c/gone"]["created_at"] == ""  # known-failure marker, no refetch loop
    assert cache.upserts[0]["fetched_at"] == 7.0
