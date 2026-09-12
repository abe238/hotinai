import json
from pathlib import Path

from hotin import engine
from hotin.sources import diggactivity


FIXTURE = Path(__file__).parent / "fixtures" / "digg_activity_trimmed.html"


def _by_repo(page):
    return {record["canonical_repo"]: record for record in diggactivity.parse_page(page)}


def test_known_rows_parse_with_ints_and_lowercase_ids():
    page = FIXTURE.read_text(encoding="utf-8")
    assert len(diggactivity._rows(diggactivity._chunks(page))) == 6
    records = _by_repo(page)

    openclaw = records["openclaw/openclaw"]
    assert openclaw["url"] == "https://github.com/openclaw/openclaw"
    assert openclaw["name"] == "openclaw/openclaw"
    assert openclaw["source"] == "diggactivity"
    assert openclaw["signal"] == {}
    assert openclaw["meta"] == {
        "digg_rank": 1, "actions": 1622, "push": 231, "pr": 684, "issues": 429,
        "devs": 24, "stars": 389400, "digg_developer": "Peter Steinberger \U0001f99e",
    }
    llama = records["ggml-org/llama.cpp"]["meta"]
    assert (llama["digg_rank"], llama["actions"], llama["stars"], llama["digg_developer"]) == (6, 46, 127800, "Georgi Gerganov")
    codexbar = records["steipete/codexbar"]["meta"]  # key lowercased from steipete/CodexBar
    assert (codexbar["digg_rank"], codexbar["actions"], codexbar["stars"]) == (8, 38, 21200)
    # "—" cells are zero, not missing
    assert records["openclaw/docs"]["meta"]["pr"] == 0


def test_rows_with_eleven_or_fewer_stars_are_dropped():
    records = _by_repo(FIXTURE.read_text(encoding="utf-8"))
    assert "openclaw/docs" in records                    # 75 stars stays
    assert "lukas/hexapod" not in records                # 0 stars, inline tr chunk
    assert "rbgirshick/pv-feed-a9074342" not in records  # 0 stars, cells via $L refs
    assert set(records) == {"openclaw/openclaw", "openclaw/docs", "ggml-org/llama.cpp", "steipete/codexbar"}


def test_malformed_page_is_empty_and_fetch_reports_error(monkeypatch):
    for bad in ("", "<html>not next</html>", '<script>self.__next_f.push([1,"3d:[\\"$\\",\\"tr\\"]"])</script>', None, 42):
        assert diggactivity.parse_page(bad) == []
    monkeypatch.setattr(diggactivity, "_request_page", lambda: "<html></html>")
    result = diggactivity.fetch(limit=5)
    assert result["records"] == [] and result["status"] == "error"
    monkeypatch.setattr(diggactivity, "_request_page", lambda: None)
    assert diggactivity.fetch()["status"] == "error"


def _row(repo, stars, developer):
    cell = lambda child: ["$", "td", None, {"children": child}]
    dev = ["$", "$L3f", None, {"user": {"username": "u", "displayName": developer}, "children": []}]
    tr = ["$", "tr", repo, {"children": [cell(1), cell(repo), cell("5"), cell("1"), cell("—"),
                                         cell("—"), cell("1"), cell(stars), cell("1 Day"), cell(dev)]}]
    payload = "aa:" + json.dumps(tr).replace("<", "\\u003c")  # Next escapes "<" inside flight strings
    return "<script>self.__next_f.push([1," + json.dumps(payload) + "])</script>"


def test_html_in_developer_name_is_stripped_and_clipped():
    page = _row("Evil/Repo", "12", "<script>alert(1)</script>Mallory <b>x</b>" + "y" * 100)
    (record,) = diggactivity.parse_page(page)
    developer = record["meta"]["digg_developer"]
    assert "<" not in developer and "script" not in developer
    assert developer.startswith("alert(1) Mallory x y")
    assert len(developer) == 60
    assert diggactivity.parse_page(_row("Evil/Repo", "11", "x")) == []  # boundary: 11 is out
    assert diggactivity.parse_page(_row("bad repo/x", "99", "x")) == []  # id regex


def test_registered_in_engine_after_trends():
    names = [engine._source_name(source) for source in engine.SOURCES]
    assert names.index("diggactivity") == names.index("trends") + 1
    assert "diggactivity" not in engine._FLAG_SOURCES
