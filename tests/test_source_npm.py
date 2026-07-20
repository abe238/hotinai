import json
from urllib.error import URLError

from hotin.sources import npm


def test_search_parser_uses_repository_then_homepage_and_ignores_bad_shapes():
    payload = {
        "objects": [
            {"package": {"name": "repo", "links": {"repository": "https://github.com/Example/Repo"}}},
            {"package": {"name": "home", "links": {"homepage": "https://github.com/Example/Home"}}},
            {"package": {"name": "wrong-links", "links": "https://github.com/example/wrong"}},
            {"package": {"links": {"repository": "https://github.com/example/no-name"}}},
        ]
    }

    assert npm.parse_search_response(payload) == [
        {"npm_package": "repo", "canonical_repo": "example/repo"},
        {"npm_package": "home", "canonical_repo": "example/home"},
    ]
    assert npm.parse_search_response({"objects": "nope"}) == []


def test_download_parser_computes_growth_and_skips_hostile_numeric_values():
    payload = {
        "downloads": [
            {"day": None, "downloads": 10},
            {"day": "not-a-date", "downloads": 10},
        ]
        + [{"day": "2026-07-{:02d}".format(day), "downloads": 10} for day in range(1, 6)]
        + [{"day": "2026-07-{:02d}".format(day), "downloads": 20} for day in range(6, 13)]
        + [{"day": "bad", "downloads": None}, {"downloads": "200"}, {"downloads": float("inf")}],
    }

    last_7, growth = npm.parse_downloads_response(payload)
    assert last_7 == 140
    assert growth == 1.0
    candidate = {"npm_package": "pkg", "canonical_repo": "Example/Repo"}
    record = npm.build_record(candidate, payload)
    assert record["url"] == "https://github.com/example/repo"
    assert record["signal"] == {"npm_downloads_week": 140, "npm_growth": 1.0}
    assert record["meta"] == {"npm_package": "pkg"}


def test_hostile_shapes_never_raise_or_emit_records():
    assert npm.parse_search_response(None) == []
    assert npm.parse_search_response({"objects": [{"package": {"name": "x", "links": []}}]}) == []
    assert npm.parse_downloads_response({"downloads": "wrong"}) is None
    assert npm.parse_downloads_response({"downloads": [{"downloads": 1e309}]}) == (0, 0.0)
    assert npm.build_record({"npm_package": "x", "canonical_repo": "not repo"}, {}) is None


def test_fetch_uses_both_endpoints_and_throttles_every_request(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    class TestThrottle:
        def __init__(self):
            self.calls = 0

        def wait(self):
            self.calls += 1

    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if "registry.npmjs.org" in request.full_url:
            return Response({"objects": [{"package": {"name": "@scope/pkg", "links": {"repository": "https://github.com/example/pkg"}}}]})
        return Response({"downloads": [{"day": "2026-07-{:02d}".format(day), "downloads": 5} for day in range(1, 15)]})

    throttle = TestThrottle()
    monkeypatch.setattr(npm, "THROTTLE", throttle)
    monkeypatch.setattr(npm.urllib.request, "urlopen", fake_urlopen)

    result = npm.fetch(query="fixture", limit=5)

    assert result["status"] == "ok"
    assert result["records"][0]["canonical_repo"] == "example/pkg"
    assert throttle.calls == 2
    assert len(calls) == 2
    assert "%40scope%2Fpkg" in calls[1][0]


def test_fetch_returns_error_when_all_search_requests_fail(monkeypatch):
    def fail(*unused, **unused_kwargs):
        raise URLError("fixture failure")

    monkeypatch.setattr(npm.urllib.request, "urlopen", fail)
    assert npm.fetch(query="fixture") == {
        "records": [],
        "status": "error",
        "detail": "npm search requests failed",
    }
