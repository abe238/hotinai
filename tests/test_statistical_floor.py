import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from statistical_floor import compute_floor  # noqa: E402


def _item(tag, sessions, referrers):
    return {"tag": tag, "days": {"20260726": {"clicks": sessions, "sessions": sessions}},
            "sessions_total": 0, "referrers": referrers}


def test_referrer_diversity_gate_blocks_a_single_source_burst():
    # the PIN test the chain doc names explicitly: 3 items, each individually
    # qualifying, but ALL from one referrer -- must NOT confirm.
    clicks = {"items": {
        "a/1": _item("agents", 3, ["hackernews.com"]),
        "a/2": _item("agents", 3, ["hackernews.com"]),
        "a/3": _item("agents", 3, ["hackernews.com"]),
    }}
    result = compute_floor(clicks)
    assert result["confirmed"] == []
    watch = result["watchlist"][0]
    assert watch["tag"] == "agents"
    assert watch["near_miss_reason"] == "referrer_diversity"


def test_three_independent_items_two_referrers_confirms():
    clicks = {"items": {
        "a/1": _item("agents", 3, ["hackernews.com"]),
        "a/2": _item("agents", 3, ["twitter.com"]),
        "a/3": _item("agents", 3, ["hackernews.com"]),
    }}
    result = compute_floor(clicks)
    assert len(result["confirmed"]) == 1
    assert result["confirmed"][0]["tag"] == "agents"
    assert result["confirmed"][0]["qualifying_items"] == 3
    assert result["watchlist"] == []


def test_only_two_qualifying_items_is_a_near_miss_not_confirmed():
    clicks = {"items": {
        "a/1": _item("agents", 3, ["hackernews.com"]),
        "a/2": _item("agents", 3, ["twitter.com"]),
    }}
    result = compute_floor(clicks)
    assert result["confirmed"] == []
    assert result["watchlist"][0]["near_miss_reason"] == "item_count"


def test_item_below_per_item_session_floor_never_counts():
    clicks = {"items": {
        "a/1": _item("agents", 2, ["hn.com"]),  # below MIN_SESSIONS_PER_ITEM=3
        "a/2": _item("agents", 3, ["twitter.com"]),
        "a/3": _item("agents", 3, ["reddit.com"]),
    }}
    result = compute_floor(clicks)
    assert result["confirmed"] == []  # only 2 real qualifiers, not 3
    assert result["watchlist"][0]["qualifying_items"] == 2


def test_uncategorized_tag_can_never_become_a_pattern():
    clicks = {"items": {
        "a/1": _item("uncategorized", 5, ["hn.com"]),
        "a/2": _item("uncategorized", 5, ["twitter.com"]),
        "a/3": _item("uncategorized", 5, ["reddit.com"]),
    }}
    result = compute_floor(clicks)
    assert result["confirmed"] == []
    assert result["watchlist"] == []  # not even a near-miss -- excluded entirely


def test_sessions_sum_across_days_and_rolled_off_total():
    clicks = {"items": {"a/1": {
        "tag": "agents", "sessions_total": 2,
        "days": {"20260724": {"clicks": 1, "sessions": 1}, "20260726": {"clicks": 1, "sessions": 1}},
        "referrers": ["hn.com"],
    }}}
    result = compute_floor(clicks)
    # 2 (rolled-off) + 1 + 1 (days) = 4 sessions, clears MIN_SESSIONS_PER_ITEM=3
    assert result["watchlist"][0]["items"][0]["sessions"] == 4


def test_empty_clicks_produces_no_confirmed_and_no_watchlist():
    result = compute_floor({"items": {}})
    assert result == {"confirmed": [], "watchlist": []}


def test_two_different_tags_evaluated_independently():
    clicks = {"items": {
        "a/1": _item("agents", 3, ["hn.com"]), "a/2": _item("agents", 3, ["twitter.com"]),
        "a/3": _item("agents", 3, ["reddit.com"]),
        "b/1": _item("inference", 3, ["hn.com"]),
    }}
    result = compute_floor(clicks)
    tags_confirmed = {c["tag"] for c in result["confirmed"]}
    assert tags_confirmed == {"agents"}
    tags_watchlist = {w["tag"] for w in result["watchlist"]}
    assert tags_watchlist == {"inference"}


def test_sentinel_referrer_values_never_count_toward_diversity():
    # the exact gap review caught: "(direct)"/"(not set)" are GA4 placeholders,
    # not real distinct sources -- one HN burst plus ordinary direct traffic
    # must NOT satisfy the referrer-diversity gate.
    clicks = {"items": {
        "a/1": _item("agents", 3, ["hackernews.com", "(direct)"]),
        "a/2": _item("agents", 3, ["(not set)"]),
        "a/3": _item("agents", 3, ["hackernews.com"]),
    }}
    result = compute_floor(clicks)
    assert result["confirmed"] == []
    assert result["watchlist"][0]["near_miss_reason"] == "referrer_diversity"
    assert result["watchlist"][0]["referrer_domains"] == ["hackernews.com"]


def test_case_variant_entity_ids_dedupe_to_one_corroborator():
    # the L3 tracer's own finding: "baidu/unlimited-ocr" vs "baidu/Unlimited-OCR"
    # are the same repo. Two case-variant keys must not count as 2 independent items.
    clicks = {"items": {
        "baidu/unlimited-ocr": _item("agents", 3, ["hn.com"]),
        "baidu/Unlimited-OCR": _item("agents", 3, ["twitter.com"]),
        "other/repo": _item("agents", 3, ["reddit.com"]),
    }}
    result = compute_floor(clicks)
    # only 2 real distinct items (the duplicate collapses), so this is a near-miss
    assert result["confirmed"] == []
    assert result["watchlist"][0]["qualifying_items"] == 2


def test_none_tag_value_normalizes_to_uncategorized_not_null():
    clicks = {"items": {"a/1": {"tag": None, "days": {"d": {"clicks": 3, "sessions": 3}},
                                 "sessions_total": 0, "referrers": ["hn.com"]}}}
    result = compute_floor(clicks)
    assert result["confirmed"] == [] and result["watchlist"] == []  # uncategorized, excluded entirely


def test_tags_json_overrides_stale_clicks_json_tag():
    # trust-chain fix: L3 may retag an item after clicks.json last saw fresh
    # traffic for it. tags.json (live) must win over clicks.json's cached copy.
    clicks = {"items": {
        "a/1": _item("training", 3, ["hn.com"]),  # stale tag cached at click-pull time
        "a/2": _item("inference", 3, ["twitter.com"]),
        "a/3": _item("inference", 3, ["reddit.com"]),
    }}
    tags = {"a/1": {"tag": "inference"}}  # L3 retagged a/1 since clicks.json last updated
    result = compute_floor(clicks, tags)
    assert len(result["confirmed"]) == 1
    assert result["confirmed"][0]["tag"] == "inference"
    assert result["confirmed"][0]["qualifying_items"] == 3  # a/1 now correctly counted under inference


def test_item_absent_from_tags_json_falls_back_to_clicks_json_cache():
    clicks = {"items": {"a/1": _item("agents", 3, ["hn.com"]), "a/2": _item("agents", 3, ["x.com"]),
                         "a/3": _item("agents", 3, ["reddit.com"])}}
    result = compute_floor(clicks, tags={})  # empty tags.json -- everything falls back
    assert result["confirmed"][0]["tag"] == "agents"


def test_main_refuses_to_overwrite_patterns_json_on_missing_clicks_file(tmp_path, monkeypatch, capsys):
    import statistical_floor
    docs = tmp_path / "docs" / "data"
    docs.mkdir(parents=True)
    (docs / "patterns.json").write_text('{"confirmed": [{"tag": "prior-real-pattern"}], "watchlist": []}')
    monkeypatch.setattr(statistical_floor, "__file__", str(tmp_path / "scripts" / "statistical_floor.py"))

    rc = statistical_floor.main()
    assert rc == 1
    # the prior week's confirmed pattern must survive an input-file failure
    assert "prior-real-pattern" in (docs / "patterns.json").read_text()


def test_main_refuses_to_overwrite_patterns_json_on_corrupt_clicks_file(tmp_path, monkeypatch):
    import statistical_floor
    docs = tmp_path / "docs" / "data"
    docs.mkdir(parents=True)
    (docs / "clicks.json").write_text("{not valid json at all}")
    (docs / "patterns.json").write_text('{"confirmed": [{"tag": "prior-real-pattern"}], "watchlist": []}')
    monkeypatch.setattr(statistical_floor, "__file__", str(tmp_path / "scripts" / "statistical_floor.py"))

    rc = statistical_floor.main()
    assert rc == 1
    assert "prior-real-pattern" in (docs / "patterns.json").read_text()


def test_main_writes_normally_on_a_genuinely_empty_but_valid_clicks_file(tmp_path, monkeypatch):
    import statistical_floor
    docs = tmp_path / "docs" / "data"
    docs.mkdir(parents=True)
    (docs / "clicks.json").write_text('{"_schema_version": 1, "items": {}}')
    monkeypatch.setattr(statistical_floor, "__file__", str(tmp_path / "scripts" / "statistical_floor.py"))

    rc = statistical_floor.main()
    assert rc == 0
    data = __import__("json").loads((docs / "patterns.json").read_text())
    assert data["confirmed"] == [] and data["watchlist"] == []
