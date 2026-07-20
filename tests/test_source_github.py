import json
import time
import urllib.parse
from urllib.error import HTTPError

from hotin.sources import github


FIXTURE = {
    "total_count": 2,
    "items": [
        {
            "html_url": "https://github.com/example/first",
            "full_name": "example/first",
            "stargazers_count": 320,
            "created_at": "2026-06-01T12:00:00Z",
            "pushed_at": "2026-07-18T10:00:00Z",
            "language": "Python",
            "forks_count": 21,
            "open_issues_count": 4,
            "description": "A real-shaped fixture.",
            "topics": ["ai", "agents"],
            "license": {"spdx_id": "MIT"},
            "archived": False,
        },
        {
            "html_url": "https://github.com/example/second",
            "full_name": "example/second",
            "stargazers_count": 110,
            "forks_count": 2,
            "open_issues_count": 0,
            "topics": [],
            "license": None,
            "archived": False,
        },
    ],
}


def test_parse_realistic_github_search_fixture():
    records = github.parse_response(FIXTURE)

    assert len(records) == 2
    assert records[0] == {
        "url": "https://github.com/example/first",
        "canonical_repo": "example/first",
        "name": "example/first",
        "source": "github",
        "signal": {
            "stars": 320,
            "created_at": "2026-06-01T12:00:00Z",
            "pushed_at": "2026-07-18T10:00:00Z",
            "language": "Python",
            "forks": 21,
            "open_issues": 4,
        },
        "meta": {
            "description": "A real-shaped fixture.",
            "topics": ["ai", "agents"],
            "license": "MIT",
            "archived": False,
        },
    }


def test_hostile_input_degrades_without_raising():
    hostile = {
        "items": [
            {"html_url": "https://github.com/not-a-repo", "full_name": "not-a-repo"},
            {
                "html_url": "https://github.com/example/hostile",
                "full_name": "example/hostile",
                "stargazers_count": 1e309,
                "forks_count": "bad",
                "open_issues_count": None,
                "topics": "not-a-list",
                "license": None,
            },
        ]
    }

    records = github.parse_response(hostile)
    assert len(records) == 1
    assert records[0]["signal"]["stars"] == 0
    assert records[0]["signal"]["forks"] == 0
    assert records[0]["meta"]["topics"] == []
    assert records[0]["meta"]["license"] is None
    assert github.parse_response({"items": "not-a-list"}) == []


def test_fetch_builds_query_uses_optional_auth_and_throttles(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return json.dumps(FIXTURE).encode("utf-8")

    class TestThrottle:
        def __init__(self):
            self.calls = 0

        def wait(self):
            self.calls += 1

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["timeout"] = timeout
        return Response()

    throttle = TestThrottle()
    monkeypatch.setattr(github, "THROTTLE", throttle)
    monkeypatch.setattr(github.urllib.request, "urlopen", fake_urlopen)

    result = github.fetch(query="agent", limit=5, days=10, config={"GITHUB_TOKEN": "fixture"})

    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(captured["url"]).query)
    assert result["status"] == "ok"
    assert len(result["records"]) == 2
    assert parsed["q"][0].startswith("agent created:>")
    assert parsed["q"][0].endswith(" stars:>50")
    assert parsed["per_page"] == ["5"]
    assert captured["headers"]["authorization"] == "Bearer fixture"
    assert captured["timeout"] == 30
    assert throttle.calls == 1


def test_rate_limit_honors_retry_after_and_does_not_retry(monkeypatch):
    class TestThrottle:
        def __init__(self):
            self.wait_calls = 0
            self.retry_delays = []

        def wait(self):
            self.wait_calls += 1

        def wait_for_retry_after(self, seconds):
            self.retry_delays.append(seconds)

    def fake_urlopen(request, timeout):
        raise HTTPError(request.full_url, 429, "too many", {"Retry-After": "12"}, None)

    throttle = TestThrottle()
    monkeypatch.setattr(github, "THROTTLE", throttle)
    monkeypatch.setattr(github.urllib.request, "urlopen", fake_urlopen)

    result = github.fetch(config={})

    assert result == {"records": [], "status": "error", "detail": "rate limited"}
    assert throttle.wait_calls == 1
    assert throttle.retry_delays == [12.0]


def test_rate_limit_reset_is_used_without_retry_after(monkeypatch):
    delay = github._retry_after({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(time.time() + 2)})
    assert delay is not None
    assert 0 <= delay <= 3


def test_malformed_root_response_is_an_error(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return b'{"not_items": []}'

    class TestThrottle:
        def wait(self):
            pass

    monkeypatch.setattr(github, "THROTTLE", TestThrottle())
    monkeypatch.setattr(github.urllib.request, "urlopen", lambda request, timeout: Response())

    assert github.fetch(config={}) == {
        "records": [],
        "status": "error",
        "detail": "github response schema invalid",
    }


def test_selftest():
    github.selftest()
