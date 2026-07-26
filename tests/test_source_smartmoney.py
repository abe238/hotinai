from datetime import datetime, timezone

from hotin.sources import _insider_roster, smartmoney


def _events(*triples):
    return [
        {"username": u, "canonical_repo": r, "starred_at": s,
         "stargazers_count": 42, "description": None}
        for (u, r, s) in triples
    ]


def test_maps_roster_events_to_smartmoney_signal_shape(monkeypatch):
    _insider_roster._reset_memo()
    events = _events(
        ("karpathy", "owner/repo", "2026-07-25T00:00:00Z"),
        ("simonw", "owner/repo", "2026-07-24T00:00:00Z"),
    )
    monkeypatch.setattr(_insider_roster, "poll_roster", lambda config=None, **kw: events)
    result = smartmoney.fetch(config={"GITHUB_TOKEN": "x"})
    assert result["status"] == "ok"
    rec = result["records"][0]
    assert rec["source"] == "smartmoney"
    assert rec["signal"]["smartmoney_starrers"] == 2
    assert rec["signal"]["smartmoney_ai1000"] == 0  # no API equivalent; always 0
    assert rec["signal"]["smartmoney_most_recent_star_at"] == "2026-07-25T00:00:00Z"
    # top_starrers carries usernames board.py can read, and deliberately NO
    # `rank` field: the roster is unranked, and a fake rank would make engine.py's
    # rank_bonus term read every starrer as top-influential (credibility inflation).
    assert rec["meta"]["top_starrers"][0] == {"username": "karpathy"}
    assert "rank" not in rec["meta"]["top_starrers"][0]


def test_ai1000_is_always_zero_even_with_many_starrers(monkeypatch):
    # Pin: the old weighted AI-1000 score has no API equivalent; hardcoding it to
    # 0 means engine.py's `* 1.2` credibility term degrades to a clean no-op
    # rather than reading stale/garbage data.
    _insider_roster._reset_memo()
    events = _events(*[("u{}".format(i), "big/repo", "2026-07-25T00:00:00Z") for i in range(20)])
    monkeypatch.setattr(_insider_roster, "poll_roster", lambda config=None, **kw: events)
    rec = smartmoney.fetch(config={"GITHUB_TOKEN": "x"})["records"][0]
    assert rec["signal"]["smartmoney_starrers"] == 20
    assert rec["signal"]["smartmoney_ai1000"] == 0


def test_freshness_bands():
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    assert smartmoney._freshness("2026-07-25T00:00:00Z", now=now) == "fresh"
    assert smartmoney._freshness("2026-01-01T00:00:00Z", now=now) == "stale"
    assert smartmoney._freshness(None) == "unknown"
    assert smartmoney._freshness("garbage") == "unknown"


def test_missing_token_is_a_loud_error(monkeypatch):
    _insider_roster._reset_memo()
    assert smartmoney.fetch(config={})["status"] == "error"


def test_empty_window_is_empty(monkeypatch):
    _insider_roster._reset_memo()
    monkeypatch.setattr(_insider_roster, "poll_roster", lambda config=None, **kw: [])
    assert smartmoney.fetch(config={"GITHUB_TOKEN": "x"})["status"] == "empty"


def test_zero_limit_is_empty():
    assert smartmoney.fetch(limit=0)["status"] == "empty"


def test_selftest():
    smartmoney.selftest()
