from datetime import date, timedelta

from hotin import board
from hotin.cli import _age_days, _dated_within, _parse_date, _rising_velocity


def _iso(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat() + "T00:00:00Z"


def test_age_days_floor_and_unknown():
    assert _age_days(_iso(10)) == 10
    assert _age_days(_iso(0)) == 1          # same-day floored to 1, no divide-by-zero
    assert _age_days(None) > 10000          # unknown -> huge, so it sinks in ranking
    assert _age_days("not-a-date") > 10000


def test_velocity_falls_back_to_stars_per_day():
    rec = {"signal": {"stars": 1000, "created_at": _iso(10)}}
    assert abs(_rising_velocity(rec) - 100.0) < 0.01
    # a young repo with fewer total stars can out-rank an older bigger one
    young = {"signal": {"stars": 500, "created_at": _iso(2)}}
    old = {"signal": {"stars": 3000, "created_at": _iso(60)}}
    assert _rising_velocity(young) > _rising_velocity(old)  # 250/day > 50/day


def test_rising_rows_receipts_and_badge():
    ranked = [{"canonical_repo": "a/b", "url": "u",
               "signal": {"stars": 500, "age_days": 5, "velocity_per_day": 100.0},
               "meta": {"description": "a fresh rocket"}}]
    r = board.rising_rows(ranked)[0]
    assert r["rank"] == 1 and r["name"] == "a/b" and r["url"] == "u"
    labels = [x["label"] for x in r["receipts"]]
    assert any("/day" in x for x in labels)     # velocity leads
    assert any("500 stars" in x for x in labels)
    assert any("5d old" in x for x in labels)
    assert r["badges"] == [{"label": "fresh", "hot": False}]
    assert r["meta"] == "a fresh rocket"


def test_rising_rows_total_on_junk():
    assert board.rising_rows([]) == []
    out = board.rising_rows([None, {}, {"name": "x/y"}])
    assert isinstance(out, list) and all("name" in row for row in out)


def test_parse_date_iso_and_rfc():
    assert _parse_date("2026-06-19T09:40:33.000Z").isoformat() == "2026-06-19"
    assert _parse_date("Wed, 22 Jul 2026 05:44:39 GMT").isoformat() == "2026-07-22"
    assert _parse_date("nonsense") is None
    assert _parse_date(None) is None


def test_dated_within_drops_old_and_undated():
    cutoff = date.today() - timedelta(days=7)
    assert _dated_within(_iso(2), cutoff) is True
    assert _dated_within(_iso(30), cutoff) is False
    assert _dated_within(None, cutoff) is False


def test_ranking_uses_history_and_lifetime_fallback(monkeypatch):
    from hotin import cli
    from hotin.sources import _star_history
    records = [
        {"canonical_repo": "a/spike", "signal": {"stars": 326, "created_at": _iso(1)}},
        {"canonical_repo": "b/steady", "signal": {"stars": 2000, "created_at": _iso(40)}},
        {"canonical_repo": "c/missing", "signal": {"stars": 10, "created_at": _iso(10)}},
    ]
    monkeypatch.setattr(cli.github, "fetch", lambda *a, **kw: {"records": records})

    def fetch(repo, *args, **kwargs):
        gains = {"a/spike": [0, 0, 0, 326, 1, 0, 0], "b/steady": [100] * 7}.get(repo)
        if gains is None:
            return None
        return {"stars_7d": sum(gains), "stars_prev_7d": 0,
                "stars_1d": gains[-1], "daily": list(enumerate(gains))}

    monkeypatch.setattr(_star_history, "fetch_history", fetch)
    ranked = cli._rising_ranked({}, 3)
    assert [r["canonical_repo"] for r in ranked] == ["b/steady", "a/spike", "c/missing"]
    assert ranked[0]["signal"]["velocity_per_day"] == 100
    assert ranked[1]["signal"]["velocity_per_day"] == 46.7
    assert ranked[0]["signal"]["velocity_basis"] == "7d"
    assert ranked[2]["signal"]["velocity_basis"] == "lifetime"


def test_history_receipts_cooling_and_spark():
    rec = {"canonical_repo": "a/b", "signal": {"stars_7d": 1056},
           "meta": {"star_days": [0, 5, 10]}}
    assert board.rising_rows([rec])[0]["receipts"][0]["label"] == "+1.1k in 7d"
    assert board.repo_rows([rec])[0]["spark"] == [0, 5, 10]
    for current, cooling in [(20, True), (300, False)]:
        rec["signal"].update(stars_7d=current, stars_prev_7d=400)
        row = board.rising_rows([rec])[0]
        assert ("cooling" in [b["label"] for b in row["badges"]]) == cooling
        assert row["spark"] == [0, 5, 10]
