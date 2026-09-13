from datetime import date, timedelta, datetime
import os
import time

import pytest

from hotin.freshness import (
    KINDS,
    MAX_APPEARANCES,
    NEWS_MAX_AGE_DAYS,
    PAPER_MAX_AGE_DAYS,
    REPO_MAX_AGE_DAYS,
    MODEL_MAX_AGE_DAYS,
    age_days,
    entity_date,
    is_fresh,
    policy,
    window,
    _anchor,
)
from hotin import freshness
from zoneinfo import ZoneInfo


def test_null_date_is_not_fresh_and_has_no_age():
    for kind in KINDS:
        assert age_days(None) is None
        assert is_fresh(kind, None) is False


def test_unparsable_date_is_not_fresh_and_has_no_age():
    for kind in KINDS:
        assert age_days("not-a-date") is None
        assert is_fresh(kind, "not-a-date") is False


def test_future_date_clamps_to_zero_and_is_fresh():
    on_date = date(2026, 9, 1)
    future = "2026-09-05"
    assert age_days(future, on_date=on_date) == 0
    for kind in KINDS:
        assert is_fresh(kind, future, on_date=on_date) is True


@pytest.mark.parametrize("kind,max_age", [
    ("repo", REPO_MAX_AGE_DAYS),
    ("model", MODEL_MAX_AGE_DAYS),
    ("paper", PAPER_MAX_AGE_DAYS),
    ("news", NEWS_MAX_AGE_DAYS),
])
def test_boundary_age_equals_window_is_fresh(kind, max_age):
    on_date = date(2026, 9, 10)
    at_boundary = (on_date - timedelta(days=max_age)).isoformat()
    assert age_days(at_boundary, on_date=on_date) == max_age
    assert is_fresh(kind, at_boundary, on_date=on_date) is True


@pytest.mark.parametrize("kind,max_age", [
    ("repo", REPO_MAX_AGE_DAYS),
    ("model", MODEL_MAX_AGE_DAYS),
    ("paper", PAPER_MAX_AGE_DAYS),
    ("news", NEWS_MAX_AGE_DAYS),
])
def test_boundary_age_over_window_is_not_fresh(kind, max_age):
    on_date = date(2026, 9, 10)
    past_boundary = (on_date - timedelta(days=max_age + 1)).isoformat()
    assert age_days(past_boundary, on_date=on_date) == max_age + 1
    assert is_fresh(kind, past_boundary, on_date=on_date) is False


def test_full_iso8601_timestamp_and_bare_date_parse_to_same_age():
    on_date = date(2026, 9, 10)
    bare = "2026-09-05"
    timestamp = "2026-09-05T23:59:59Z"
    assert age_days(bare, on_date=on_date) == age_days(timestamp, on_date=on_date)


def test_entity_date_reads_signal_created_at_for_repo_model_paper():
    record = {"signal": {"created_at": "2026-08-01"}, "meta": {"date": "2026-08-02"}}
    for kind in ("repo", "model", "paper"):
        assert entity_date(record, kind) == "2026-08-01"


def test_entity_date_reads_meta_date_for_news():
    record = {"signal": {"created_at": "2026-08-01"}, "meta": {"date": "2026-08-02"}}
    assert entity_date(record, "news") == "2026-08-02"


def test_entity_date_returns_none_for_missing_or_empty_value():
    assert entity_date({"signal": {}}, "repo") is None
    assert entity_date({"signal": {"created_at": ""}}, "repo") is None
    assert entity_date({}, "news") is None


def test_entity_date_unknown_kind_raises_value_error():
    with pytest.raises(ValueError):
        entity_date({}, "bogus")


def test_window_unknown_kind_raises_value_error():
    with pytest.raises(ValueError):
        window("bogus")


def test_policy_returns_exactly_the_published_windows():
    # insider_max_age_days joined in POLICY_VERSION 2: an insider row is judged by when the
    # insider starred it, not by the repo's creation date.
    assert policy() == {
        "repo_max_age_days": 7,
        "model_max_age_days": 7,
        "paper_max_age_days": 7,
        "news_max_age_days": 2,
        "insider_max_age_days": 7,
        "max_appearances": 3,
    }


def test_max_appearances_constant():
    assert MAX_APPEARANCES == 3


def test_default_reference_date_is_pacific_not_host_local(monkeypatch):
    """age_days() without on_date must anchor on the Pacific civil date, never
    host-local time.

    Freezes freshness._now to a fixed Pacific-aware instant (2026-09-12 23:30
    PDT), which is already 2026-09-13 in a UTC+14 zone. Under two different
    host TZs whose civil date at that instant differs from Pacific's, the
    result must still equal the age computed against the PACIFIC date -- that
    is what proves host-independence deterministically (a date.today()
    regression would instead track the host TZ and diverge).
    """
    original_tz = os.environ.get("TZ")
    fixed_instant = datetime(2026, 9, 12, 23, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    monkeypatch.setattr(freshness, "_now", lambda: fixed_instant)

    date_iso = "2026-09-05"
    # Pacific civil date at the fixed instant is 2026-09-12; created 2026-09-05
    # is 7 days before Pacific noon on that date.
    expected_age = 7
    assert age_days(date_iso, on_date=fixed_instant.date()) == expected_age

    try:
        for tz in ("Etc/GMT-14", "Pacific/Kiritimati"):
            monkeypatch.setenv("TZ", tz)
            time.tzset()
            assert age_days(date_iso) == expected_age
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()


def test_anchor_is_correct_under_daylight_saving():
    """Verify that the anchor uses real Pacific zone (DST-aware), not fixed -8.

    Asserts on `_anchor`, the SAME builder `age_days` calls, so a revert of
    just its tzinfo cannot escape this test.
    """
    # August is PDT (UTC-7)
    anchor_august = _anchor(date(2026, 8, 20))
    assert anchor_august.utcoffset() == timedelta(hours=-7), "August should be PDT (UTC-7)"

    # November is PST (UTC-8)
    anchor_november = _anchor(date(2026, 11, 20))
    assert anchor_november.utcoffset() == timedelta(hours=-8), "November should be PST (UTC-8)"
