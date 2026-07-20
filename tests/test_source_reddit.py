import json
from urllib.error import URLError

from hotin.sources import reddit


def test_no_key_is_the_normal_optional_state():
    assert reddit.fetch(config={}) == {
        "records": [],
        "status": "empty",
        "detail": "no SCRAPECREATORS_API_KEY configured",
    }


def test_parser_extracts_direct_and_body_links_and_dedupes_by_higher_score():
    local_llama = {
        "posts": [
            {
                "title": "Direct URL",
                "url": "https://github.com/Example/Useful",
                "score": "12",
                "num_comments": 3,
                "permalink": "/r/LocalLLaMA/comments/one/direct_url/",
            },
            {
                "title": "Body URL",
                "selftext": "Here: https://github.com/example/body-link).",
                "score": 8,
            },
            {"title": "Not GitHub", "url": "https://example.com/project", "score": 99},
        ]
    }
    machine_learning = {
        "posts": [
            {
                "title": "Higher duplicate",
                "url_overridden_by_dest": "https://github.com/example/useful/issues/1",
                "score": 20,
            }
        ]
    }

    records = reddit.dedupe_records(
        reddit.parse_response(local_llama, "LocalLLaMA")
        + reddit.parse_response(machine_learning, "MachineLearning"),
        50,
    )

    assert [record["canonical_repo"] for record in records] == ["example/useful", "example/body-link"]
    assert records[0]["signal"] == {"reddit_score": 20}
    assert records[1]["signal"] == {"reddit_score": 8}
    assert records[0]["meta"]["subreddit"] == "MachineLearning"
    assert records[0]["url"] == "https://github.com/example/useful"
    assert records[1]["name"] == "Body URL"


def test_parser_hostile_shapes_and_missing_score_degrade_to_no_records():
    assert reddit.parse_response({}, "LocalLLaMA") == []
    assert reddit.parse_response({"posts": None}, "LocalLLaMA") == []
    assert reddit.parse_response({"posts": "not a list"}, "LocalLLaMA") == []
    assert reddit.parse_response(
        {"posts": [{"title": "Missing score", "url": "https://github.com/example/repo"}]},
        "LocalLLaMA",
    ) == []
    assert reddit.parse_response(
        {"posts": [{"title": "Overflow", "url": "https://github.com/example/repo", "score": 1e309}]},
        "LocalLLaMA",
    ) == []


def test_parser_trims_prose_glued_to_a_free_text_github_url():
    records = reddit.parse_response(
        {
            "posts": [
                {
                    "title": "Stereo2Spatial",
                    "selftext": (
                        "...https://github.com/francislabountyjr/"
                        "stereo2spatialGithub repo for the Windows app..."
                    ),
                    "score": 1,
                }
            ]
        },
        "LocalLLaMA",
    )

    assert records[0]["canonical_repo"] == "francislabountyjr/stereo2spatial"


def test_fetch_isolates_one_subreddit_failure_and_throttles_every_request(monkeypatch):
    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return self.body

    class TestThrottle:
        def __init__(self):
            self.calls = 0

        def wait(self):
            self.calls += 1

    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if "subreddit=MachineLearning" in request.full_url:
            raise URLError("fixture failure")
        payload = {
            "posts": [
                {
                    "title": "Fixture repo",
                    "url": "https://github.com/example/fixture",
                    "score": 10,
                }
            ]
        }
        return Response(json.dumps(payload).encode("utf-8"))

    throttle = TestThrottle()
    monkeypatch.setattr(reddit, "THROTTLE", throttle)
    monkeypatch.setattr(reddit.urllib.request, "urlopen", fake_urlopen)

    result = reddit.fetch(limit=5, config={"SCRAPECREATORS_API_KEY": "fixture-key"})

    assert result["status"] == "ok"
    assert len(result["records"]) == 1
    assert len(calls) == len(reddit.SUBREDDITS)
    assert throttle.calls == len(reddit.SUBREDDITS)


def test_fetch_query_uses_search_endpoint_while_default_uses_subreddits(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return json.dumps({"posts": []}).encode("utf-8")

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr(reddit.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(reddit, "THROTTLE", type("Throttle", (), {"wait": lambda self: None})())

    assert reddit.fetch(query="rust cli", config={"SCRAPECREATORS_API_KEY": "fixture-key"})[
        "status"
    ] == "empty"
    assert len(calls) == 1
    assert "/reddit/search?" in calls[0]
    assert "query=rust+cli" in calls[0]
    assert "sort=top" in calls[0]
    assert "timeframe=week" in calls[0]

    calls.clear()
    assert reddit.fetch(config={"SCRAPECREATORS_API_KEY": "fixture-key"})["status"] == "empty"
    assert len(calls) == len(reddit.SUBREDDITS)
    assert all("/reddit/subreddit?" in url for url in calls)
