from datetime import date, timedelta

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
)


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


def test_policy_returns_exactly_the_five_keys():
    assert policy() == {
        "repo_max_age_days": 7,
        "model_max_age_days": 7,
        "paper_max_age_days": 7,
        "news_max_age_days": 2,
        "max_appearances": 3,
    }


def test_max_appearances_constant():
    assert MAX_APPEARANCES == 3
