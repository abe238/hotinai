import json
from datetime import datetime, timezone
from pathlib import Path

from hotin.sources import smartmoney


FIXTURE = Path(__file__).parent / "fixtures" / "insider_rows_sample.json"


def test_parse_synthetic_insider_fixture():
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    records = smartmoney.parse_rows(rows, now=datetime(2026, 7, 20, tzinfo=timezone.utc))

    assert len(records) == 2
    first = records[0]
    assert first["url"] == "https://github.com/testowner/test-repo"
    assert first["canonical_repo"] == "testowner/test-repo"
    assert first["source"] == "smartmoney"
    assert first["signal"] == {
        "smartmoney_starrers": 1,
        "smartmoney_ai1000": 1,
        "smartmoney_freshness": "fresh",
        "smartmoney_most_recent_star_at": "2026-07-20T00:09:26+00:00",
    }
    assert first["meta"]["top_starrers"] == [{"username": "testuser1", "rank": 100}]


def test_extract_rows_from_realistic_rsc_html():
    payload = {"outer": [{"rows": [{"repo": {"full_name": "Example/Project"}}]}]}
    segment = "a:" + json.dumps(payload)
    escaped = json.dumps(segment)[1:-1]
    html = '<script>self.__next_f.push([1, "{}"])</script>'.format(escaped)

    assert smartmoney.extract_rows_from_html(html) == [{"repo": {"full_name": "Example/Project"}}]


def test_hostile_input_degrades_without_raising():
    rows = [
        {"repo": {"full_name": "missing slash", "ai1000_stars": 1e309}},
        {
            "repo": {
                "full_name": "good/repo",
                "ai1000_stars": 1e309,
                "distinct_starrers": "not-a-number",
                "starrers": "not-a-list",
            }
        },
    ]
    records = smartmoney.parse_rows(rows)

    assert len(records) == 1
    assert records[0]["signal"]["smartmoney_ai1000"] == 0
    assert records[0]["signal"]["smartmoney_starrers"] == 0
    assert records[0]["meta"]["top_starrers"] == []
    assert records[0]["signal"]["smartmoney_freshness"] == "unknown"
    assert smartmoney.extract_rows_from_html(
        '<script>self.__next_f.push([1, "1:not-json"])</script>'
    ) is None
    assert smartmoney._find_rows({"rows": "not-a-list"}) is None


def test_find_rows_keeps_valid_rows_when_one_entry_is_malformed():
    rows = [
        {"repo": {"full_name": "testowner/first"}},
        None,
        {"repo": {"full_name": "testowner/second"}},
    ]

    assert smartmoney._find_rows({"rows": rows}) == rows
    assert [record["canonical_repo"] for record in smartmoney.parse_rows(rows)] == [
        "testowner/first",
        "testowner/second",
    ]


def test_selftest():
    smartmoney.selftest()
