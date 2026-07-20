import json
import urllib.parse
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


def test_split_batch_downloads_handles_wrapped_and_flat_shapes():
    wrapped = {"pkg-a": {"downloads": [{"day": "2026-07-01", "downloads": 5}]}, "pkg-b": None}
    assert npm._split_batch_downloads(wrapped, ["pkg-a", "pkg-b"]) == {
        "pkg-a": {"downloads": [{"day": "2026-07-01", "downloads": 5}]},
        "pkg-b": None,
    }
    flat = {"downloads": [{"day": "2026-07-01", "downloads": 5}], "package": "pkg-a"}
    assert npm._split_batch_downloads(flat, ["pkg-a"]) == {"pkg-a": flat}
    assert npm._split_batch_downloads("not a dict", ["pkg-a"]) == {}


def test_fetch_batches_unscoped_and_caps_scoped_download_lookups(monkeypatch):
    # 3 unscoped candidates (should collapse into ONE batched downloads request)
    # and more scoped candidates than MAX_SCOPED_DOWNLOAD_LOOKUPS allows (each
    # scoped candidate costs its own throttled request, so only the cap's worth
    # should ever be requested).
    scoped_count = npm.MAX_SCOPED_DOWNLOAD_LOOKUPS + 2
    objects = [
        {"package": {"name": "unscoped-{}".format(i), "links": {"repository": "https://github.com/example/unscoped-{}".format(i)}}}
        for i in range(3)
    ] + [
        {"package": {"name": "@scope/pkg-{}".format(i), "links": {"repository": "https://github.com/example/scoped-{}".format(i)}}}
        for i in range(scoped_count)
    ]
    search_payload = {"objects": objects}
    days = [{"day": "2026-07-{:02d}".format(day), "downloads": 5} for day in range(1, 15)]

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    download_requests = []

    def fake_urlopen(request, timeout):
        url = request.full_url
        if "registry.npmjs.org" in url:
            return Response(search_payload)
        download_requests.append(url)
        if "," in url.split("/downloads/range/last-month/", 1)[1]:
            names = url.split("/downloads/range/last-month/", 1)[1].split(",")
            return Response({urllib.parse.unquote(name): {"downloads": days} for name in names})
        return Response({"downloads": days})

    monkeypatch.setattr(npm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(npm, "THROTTLE", type("T", (), {"wait": lambda self: None})())

    result = npm.fetch(query="fixture", limit=50)

    assert result["status"] == "ok"
    # 1 unscoped batch request + exactly MAX_SCOPED_DOWNLOAD_LOOKUPS scoped requests.
    assert len(download_requests) == 1 + npm.MAX_SCOPED_DOWNLOAD_LOOKUPS
    package_names = {record["meta"]["npm_package"] for record in result["records"]}
    assert {"unscoped-0", "unscoped-1", "unscoped-2"} <= package_names
    assert sum(1 for name in package_names if name.startswith("@scope/")) == npm.MAX_SCOPED_DOWNLOAD_LOOKUPS


def test_fetch_returns_error_when_all_search_requests_fail(monkeypatch):
    def fail(*unused, **unused_kwargs):
        raise URLError("fixture failure")

    monkeypatch.setattr(npm.urllib.request, "urlopen", fail)
    assert npm.fetch(query="fixture") == {
        "records": [],
        "status": "error",
        "detail": "npm search requests failed",
    }
