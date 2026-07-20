import json
from urllib.error import URLError

from hotin.sources import hn


def test_parser_extracts_url_and_story_text_dedupes_and_skips_reserved_owner():
    payload = {
        "hits": [
            {
                "url": "https://github.com/Example/Useful",
                "points": "90",
                "num_comments": 12,
                "objectID": "one",
                "title": "Useful project",
            },
            {
                "story_text": "Show HN: github.com/example/body-link is ready.",
                "points": 80,
                "num_comments": 4,
                "objectID": "two",
                "title": "Body link",
            },
            {
                "url": "https://github.com/example/useful/issues/1",
                "points": 150,
                "num_comments": 20,
                "objectID": "three",
                "title": "Higher duplicate",
            },
            {
                "url": "https://github.com/blog/announcement",
                "points": 500,
                "num_comments": 50,
                "objectID": "four",
                "title": "False match",
            },
            {
                "url": "https://example.com/nope",
                "points": 500,
                "num_comments": 50,
                "objectID": "five",
                "title": "Not GitHub",
            },
        ]
    }

    records = hn.dedupe_records(hn.parse_response(payload), 50)

    assert [record["canonical_repo"] for record in records] == ["example/useful", "example/body-link"]
    assert records[0]["url"] == "https://github.com/example/useful"
    assert records[0]["signal"] == {"hn_points": 150, "hn_comments": 20}
    assert records[0]["meta"] == {"hn_id": "three", "hn_title": "Higher duplicate"}


def test_parser_classifies_arxiv_as_paper_and_huggingface_as_model():
    payload = {
        "hits": [
            {
                "url": "https://arxiv.org/abs/2506.12345",
                "points": 200,
                "num_comments": 30,
                "objectID": "paper",
                "title": "A paper on HN",
            },
            {
                "url": "https://huggingface.co/deepseek-ai/DeepSeek-V4",
                "points": 175,
                "num_comments": 25,
                "objectID": "model",
                "title": "A model on HN",
            },
            {
                # HF reserved first path segment is a page, not a model
                "url": "https://huggingface.co/papers/2506.99999",
                "points": 300,
                "num_comments": 40,
                "objectID": "hfpage",
                "title": "HF papers page",
            },
        ]
    }

    records = hn.dedupe_records(hn.parse_response(payload), 50)
    identity = {(r["entity_type"], r["entity_id"]) for r in records}

    assert ("paper", "2506.12345") in identity
    assert ("model", "deepseek-ai/DeepSeek-V4") in identity
    assert not any(r["entity_type"] == "model" and r["entity_id"].startswith("papers/") for r in records)
    paper = next(r for r in records if r["entity_type"] == "paper")
    assert paper["url"] == "https://arxiv.org/abs/2506.12345"
    assert "canonical_repo" not in paper


def test_parser_hostile_shapes_overflow_and_missing_object_id_degrade_to_no_records():
    assert hn.parse_response({}) == []
    assert hn.parse_response({"hits": "not a list"}) == []
    assert hn.parse_response(
        {
            "hits": [
                {
                    "url": "https://github.com/example/repo",
                    "points": 1e309,
                    "num_comments": 1,
                    "title": "Hostile number",
                }
            ]
        }
    ) == []
    assert hn.parse_response(
        {
            "hits": [
                {
                    "url": "https://github.com/example/repo",
                    "points": 70,
                    "num_comments": 1,
                    "title": "Missing object ID",
                }
            ]
        }
    ) == []


def test_parser_trims_prose_glued_to_a_free_text_github_url():
    records = hn.parse_response(
        {
            "hits": [
                {
                    "story_text": (
                        "...https://github.com/francislabountyjr/"
                        "stereo2spatialGithub repo for the Windows app..."
                    ),
                    "points": 1,
                    "num_comments": 0,
                    "objectID": "stereo2spatial",
                    "title": "Stereo2Spatial",
                }
            ]
        }
    )

    assert records[0]["canonical_repo"] == "francislabountyjr/stereo2spatial"


def test_fetch_uses_recent_endpoint_filters_and_throttles(monkeypatch):
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

    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request.full_url, timeout))
        return Response(
            json.dumps(
                {
                    "hits": [
                        {
                            "url": "https://github.com/example/fixture",
                            "points": 77,
                            "num_comments": 3,
                            "objectID": "fixture",
                            "title": "Fixture repo",
                        }
                    ]
                }
            ).encode("utf-8")
        )

    throttle = TestThrottle()
    monkeypatch.setattr(hn, "THROTTLE", throttle)
    monkeypatch.setattr(hn.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(hn.time, "time", lambda: 2_000_000_000)

    result = hn.fetch(limit=5, config={"HN_MIN_POINTS": "75", "HN_DAYS": "7"})

    assert result["status"] == "ok"
    assert result["records"][0]["canonical_repo"] == "example/fixture"
    assert throttle.calls == 1
    assert seen[0][1] == 30
    assert "search_by_date" in seen[0][0]
    assert "numericFilters=points%3E75%2Ccreated_at_i%3E1999395200" in seen[0][0]


def test_fetch_request_failure_is_an_error(monkeypatch):
    monkeypatch.setattr(hn.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(URLError("fixture")))
    assert hn.fetch() == {"records": [], "status": "error", "detail": "hn request failed"}


def test_selftest():
    hn.selftest()
