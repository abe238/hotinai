import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pull_clicks import fold_clicks, load_json  # noqa: E402


def _row(entity_id, day, source, event_count, sessions):
    return {
        "dimensionValues": [{"value": entity_id}, {"value": day}, {"value": source}],
        "metricValues": [{"value": str(event_count)}, {"value": str(sessions)}],
    }


TODAY = date(2026, 7, 26)


def test_refolding_the_same_day_is_idempotent_not_additive():
    # This is the exact bug review caught: a rolling 3-day window re-queried
    # every 3h must NOT add the same day's total on every re-pull, or one
    # real click inflates to ~24x over its time in the window.
    clicks = {"_schema_version": 1, "items": {}}
    tags = {"a/b": {"tag": "agents"}}
    row = _row("a/b", "20260726", "google", 3, 2)
    for _ in range(24):  # simulates 24 runs (3 days at a 3h cadence) re-pulling the same day
        fold_clicks(clicks, tags, [row], today=TODAY)
    rec = clicks["items"]["a/b"]
    assert rec["days"]["20260726"] == {"clicks": 3, "sessions": 2}
    assert rec["clicks_total"] == 0  # today hasn't aged out
    # lifetime total (days + clicks_total) must equal the real count, not 24x it
    lifetime = rec["clicks_total"] + sum(d["clicks"] for d in rec["days"].values())
    assert lifetime == 3


def test_todays_count_naturally_grows_across_intraday_runs():
    # "today" legitimately accumulates as the day progresses; each run's
    # query returns a bigger running total for the SAME day, and assigning
    # (not adding) that growing total is correct.
    clicks = {"_schema_version": 1, "items": {}}
    fold_clicks(clicks, {}, [_row("a/b", "20260726", "google", 2, 1)], today=TODAY)
    fold_clicks(clicks, {}, [_row("a/b", "20260726", "google", 5, 3)], today=TODAY)
    assert clicks["items"]["a/b"]["days"]["20260726"] == {"clicks": 5, "sessions": 3}


def test_stale_days_roll_into_frozen_totals_and_leave_the_window():
    clicks = {"_schema_version": 1, "items": {}}
    # a day well outside the WINDOW_DAYS=3 lookback from TODAY
    fold_clicks(clicks, {}, [_row("a/b", "20260701", "google", 4, 2)], today=TODAY)
    rec = clicks["items"]["a/b"]
    assert "20260701" not in rec["days"]  # rolled off, never re-queried
    assert rec["clicks_total"] == 4
    assert rec["sessions_total"] == 2


def test_rolling_off_happens_even_for_items_untouched_this_run():
    clicks = {"_schema_version": 1, "items": {
        "old/item": {"tag": "agents", "days": {"20260701": {"clicks": 9, "sessions": 3}},
                     "clicks_total": 0, "sessions_total": 0, "referrers": [],
                     "first_click_at": "20260701", "last_click_at": "20260701"},
    }}
    fold_clicks(clicks, {}, [], today=TODAY)  # no new rows at all this run
    rec = clicks["items"]["old/item"]
    assert rec["days"] == {}
    assert rec["clicks_total"] == 9


def test_fold_clicks_never_stores_raw_session_or_click_rows():
    # fake-success mode this guards: a rolling aggregate that secretly keeps
    # a per-click or per-session list defeats the aggregate-only hard rule.
    clicks = {"_schema_version": 1, "items": {}}
    fold_clicks(clicks, {}, [_row("x/y", "20260726", "direct", 5, 4)], today=TODAY)
    rec = clicks["items"]["x/y"]
    assert set(rec.keys()) == {"tag", "days", "clicks_total", "sessions_total",
                                "referrers", "first_click_at", "last_click_at"}
    assert isinstance(rec["clicks_total"], int)


def test_fold_clicks_skips_not_set_and_malformed_rows():
    clicks = {"_schema_version": 1, "items": {}}
    rows = [_row("(not set)", "20260726", "google", 1, 1),
            {"dimensionValues": []}, _row("", "20260726", "x", 1, 1),
            _row("a/b", "", "x", 1, 1)]  # missing date_key
    folded = fold_clicks(clicks, {}, rows, today=TODAY)
    assert folded == 0
    assert clicks["items"] == {}


def test_fold_clicks_referrers_bounded():
    clicks = {"_schema_version": 1, "items": {}}
    rows = [_row("a/b", "20260726", f"source{i}", 1, 1) for i in range(20)]
    fold_clicks(clicks, {}, rows, today=TODAY)
    assert len(clicks["items"]["a/b"]["referrers"]) == 10  # MAX_REFERRERS


def test_fold_clicks_defaults_to_uncategorized_when_untagged():
    clicks = {"_schema_version": 1, "items": {}}
    fold_clicks(clicks, {}, [_row("no-tag/item", "20260726", "google", 1, 1)], today=TODAY)
    assert clicks["items"]["no-tag/item"]["tag"] == "uncategorized"


def test_first_and_last_click_at_span_the_days_seen():
    clicks = {"_schema_version": 1, "items": {}}
    fold_clicks(clicks, {}, [_row("a/b", "20260724", "google", 1, 1)], today=TODAY)
    fold_clicks(clicks, {}, [_row("a/b", "20260726", "google", 1, 1)], today=TODAY)
    rec = clicks["items"]["a/b"]
    assert rec["first_click_at"] == "20260724"
    assert rec["last_click_at"] == "20260726"


def test_load_json_never_raises_on_malformed_file(tmp_path):
    path = tmp_path / "clicks.json"
    path.write_text("not valid json {{{")
    result = load_json(path, {"_schema_version": 1, "items": {}})
    assert result == {"_schema_version": 1, "items": {}}


def test_load_json_missing_file_returns_default(tmp_path):
    result = load_json(tmp_path / "absent.json", {"a": 1})
    assert result == {"a": 1}
