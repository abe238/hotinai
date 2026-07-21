import json

from hotin.sources import insiders


def _page(*texts):
    # Real page ships each flight chunk as a JSON *string* value; escape it the
    # same way so the sibling decoders round-trip it back to the raw blob text.
    chunks = "".join(
        'self.__next_f.push([1, "{}"])</script>'.format(json.dumps(t)[1:-1]) for t in texts
    )
    return "<html><body>" + chunks + "</body></html>"


def _repos(objs):
    return _page(json.dumps(objs, separators=(",", ":")))


def test_parses_repos_dedupes_and_picks_top_insider():
    html = _repos([
        {"full_name": "Owner/Repo", "distinct_starrers": 3,
         "starrers": [{"username": "karpathy", "rank": 5}, {"username": "ilya", "rank": 1}]},
        {"full_name": "owner/repo", "distinct_starrers": 9,  # dup canonical, higher stars
         "starrers": [{"username": "sama", "rank": 2}, {"username": "greg", "rank": 4}]},
        {"full_name": "second/proj", "distinct_starrers": 4,
         "starrers": [{"username": "a", "rank": 10}, {"username": "b", "rank": 2},
                      {"username": "c", "rank": 8}, {"username": "d", "rank": 1},
                      {"username": "e", "rank": 7}, {"username": "f", "rank": 6}]},
    ])
    records = insiders.parse_repos(html)
    assert [r["entity_id"] for r in records] == ["owner/repo", "second/proj"]  # sorted by stars desc

    top = records[0]
    assert top["entity_type"] == "repo" and top["canonical_repo"] == "owner/repo"
    assert top["url"] == "https://github.com/owner/repo" and top["name"] == "owner/repo"
    assert top["source"] == "insiders"
    assert top["signal"]["insider_stars"] == 9  # dedupe kept the higher count
    assert top["meta"]["top_insider"] == "sama" and top["meta"]["insiders"] == ["sama", "greg"]

    second = records[1]
    assert second["signal"]["insider_stars"] == 4
    assert second["meta"]["top_insider"] == "d"  # lowest rank wins, not first listed
    assert second["meta"]["insiders"] == ["a", "b", "c", "d", "e"]  # capped at five, in order


def test_hostile_and_empty_inputs_are_safe():
    assert insiders.parse_repos(None) == []
    assert insiders.parse_repos("garbage") == []
    assert insiders.parse_repos("<html>self.__next_f.push([1,\"broken)</html>") == []
    messy = _repos([
        None,
        {"full_name": "bad repo"},                      # not a valid GitHub ref
        {"full_name": "ok/repo", "distinct_starrers": 1e309, "starrers": ["nope"]},
        {"full_name": "keys/missing"},                  # no starrers, no star count
    ])
    records = insiders.parse_repos(messy)
    by_id = {r["entity_id"]: r for r in records}
    assert by_id["ok/repo"]["signal"]["insider_stars"] == 0  # overflow coerced to default
    assert by_id["ok/repo"]["meta"] == {"insiders": [], "top_insider": None}
    assert by_id["keys/missing"]["signal"]["insider_stars"] == 0


def test_fetch_error_when_request_fails(monkeypatch):
    monkeypatch.setattr(insiders, "_request", lambda: None)
    assert insiders.fetch(limit=5) == {
        "records": [], "status": "error", "detail": "insiders request failed"
    }


def test_fetch_ok_caps_to_limit(monkeypatch):
    html = _repos([
        {"full_name": "a/one", "distinct_starrers": 5, "starrers": [{"username": "x", "rank": 1}]},
        {"full_name": "b/two", "distinct_starrers": 9, "starrers": [{"username": "y", "rank": 1}]},
    ])
    monkeypatch.setattr(insiders, "_request", lambda: html)
    result = insiders.fetch(limit=1)
    assert result["status"] == "ok" and len(result["records"]) == 1
    assert result["records"][0]["entity_id"] == "b/two"  # highest stars first


def test_fetch_zero_limit_is_empty():
    assert insiders.fetch(limit=0)["status"] == "empty"


def test_selftest():
    insiders.selftest()
