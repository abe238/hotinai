import json
from urllib.error import URLError

from hotin.sources import youtube


def test_no_key_is_the_normal_optional_state():
    assert youtube.fetch(config={}) == {
        "records": [],
        "status": "empty",
        "detail": "no YOUTUBE_API_KEY or SCRAPECREATORS_API_KEY configured",
    }


def test_v3_is_preferred_when_youtube_api_key_is_set(monkeypatch):
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        url = request.full_url
        calls.append(url)
        if "/youtube/v3/search" in url:
            return Response({"items": [{"id": {"videoId": "vid-1"}}]})
        if "/youtube/v3/videos" in url:
            return Response({"items": [{
                "id": "vid-1",
                "snippet": {"title": "Great repo", "description": "see https://github.com/example/pkg",
                            "channelTitle": "Chan", "publishedAt": "2026-07-10T00:00:00Z"},
                "statistics": {"viewCount": "4242"},
            }]})
        raise AssertionError("v3 path must not hit ScrapeCreators: " + url)

    monkeypatch.setattr(youtube.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(youtube, "V3_THROTTLE", type("T", (), {"wait": lambda self: None})())

    result = youtube.fetch(query="fixture", limit=5, config={"YOUTUBE_API_KEY": "yt-key"})
    assert result["status"] == "ok"
    assert result["records"][0]["canonical_repo"] == "example/pkg"
    assert result["records"][0]["signal"]["youtube_views"] == 4242
    # v3 search + videos were both hit; the key rode the query string (Google's design).
    assert any("/youtube/v3/search" in c and "key=yt-key" in c for c in calls)
    assert any("/youtube/v3/videos" in c for c in calls)


def test_v3_all_requests_failing_is_an_error(monkeypatch):
    def fail(*unused, **unused_kwargs):
        raise URLError("fixture failure")

    monkeypatch.setattr(youtube.urllib.request, "urlopen", fail)
    monkeypatch.setattr(youtube, "V3_THROTTLE", type("T", (), {"wait": lambda self: None})())
    result = youtube.fetch(query="fixture", config={"YOUTUBE_API_KEY": "yt-key"})
    assert result == {"records": [], "status": "error", "detail": "all YouTube API requests failed"}


def test_parser_extracts_description_link_and_skips_videos_without_one():
    payload = {
        "videos": [
            {
                "id": "demo-video",
                "title": "Useful AI project",
                "description": "Code: https://github.com/Example/Useful-Tool).",
                "viewCountInt": "1250",
                "publishedTime": "2026-07-01T12:00:00Z",
                "channel": {"title": "Example Creator"},
            },
            {
                "id": "no-link",
                "title": "No repo here",
                "description": "This video has no source link.",
            },
        ]
    }

    records = youtube.parse_response(payload)

    assert len(records) == 1
    assert records[0]["url"] == "https://github.com/example/useful-tool"
    assert records[0]["canonical_repo"] == "example/useful-tool"
    assert records[0]["name"] == "Useful AI project"
    assert records[0]["source"] == "youtube"
    assert records[0]["signal"] == {
        "youtube_views": 1250,
        "youtube_published_at": "2026-07-01T12:00:00Z",
    }
    assert records[0]["meta"] == {
        "youtube_title": "Useful AI project",
        "youtube_channel": "Example Creator",
        "youtube_video_id": "demo-video",
    }


def test_parser_hostile_shapes_missing_description_and_junk_views_are_safe():
    assert youtube.parse_response({}) == []
    assert youtube.parse_response({"videos": None}) == []
    assert youtube.parse_response({"videos": "not-a-list"}) == []
    assert youtube.parse_response({"videos": [{"id": "missing-description"}]}) == []
    assert youtube.parse_response(
        {
            "videos": [
                {
                    "id": "hostile-view-count",
                    "description": "https://github.com/example/hostile",
                    "viewCountInt": "not-a-number",
                    "channel": [],
                }
            ]
        }
    ) == [
        {
            "url": "https://github.com/example/hostile",
            "canonical_repo": "example/hostile",
            "name": "example/hostile",
            "source": "youtube",
            "signal": {},
            "meta": {"youtube_title": "example/hostile", "youtube_video_id": "hostile-view-count"},
        }
    ]
    assert youtube.parse_response(
        {"videos": [{"id": "overflow", "description": "https://github.com/example/overflow", "viewCountInt": 1e309}]}
    )[0]["signal"] == {}


def test_parser_trims_prose_glued_to_a_free_text_github_url():
    records = youtube.parse_response(
        {
            "videos": [
                {
                    "id": "stereo2spatial-video",
                    "description": (
                        "...https://github.com/francislabountyjr/"
                        "stereo2spatialGithub repo for the Windows app..."
                    ),
                }
            ]
        }
    )

    assert records[0]["canonical_repo"] == "francislabountyjr/stereo2spatial"


def test_fetch_throttles_each_default_query_and_includes_extras(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return json.dumps(
                {
                    "videos": [
                        {
                            "id": "fixture",
                            "description": "https://github.com/example/fixture",
                            "viewCountInt": 3,
                        }
                    ]
                }
            ).encode("utf-8")

    class TestThrottle:
        def __init__(self):
            self.calls = 0

        def wait(self):
            self.calls += 1

    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if "AI+agent+github" in request.full_url:
            raise URLError("fixture failure")
        return Response()

    throttle = TestThrottle()
    monkeypatch.setattr(youtube, "THROTTLE", throttle)
    monkeypatch.setattr(youtube.urllib.request, "urlopen", fake_urlopen)

    result = youtube.fetch(limit=5, config={"SCRAPECREATORS_API_KEY": "fixture-key"})

    assert result["status"] == "ok"
    assert result["detail"] is None
    assert len(result["records"]) == 1
    assert len(calls) == len(youtube.DEFAULT_QUERIES)
    assert throttle.calls == len(youtube.DEFAULT_QUERIES)
    assert result["records"][0]["canonical_repo"] == "example/fixture"
    assert all("includeExtras=true" in url for url, _ in calls)


def test_fetch_returns_empty_when_successful_videos_have_no_github_links(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def read(self):
            return json.dumps(
                {"videos": [{"id": "no-link", "description": "No repository link here."}]}
            ).encode("utf-8")

    monkeypatch.setattr(youtube.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    monkeypatch.setattr(youtube, "THROTTLE", type("Throttle", (), {"wait": lambda self: None})())

    assert youtube.fetch(query="fixture", config={"SCRAPECREATORS_API_KEY": "fixture-key"}) == {
        "records": [],
        "status": "empty",
        "detail": "no GitHub repositories found",
    }


def test_dedupe_records_respects_zero_and_positive_limits():
    records = [
        {"canonical_repo": "owner/one"},
        {"canonical_repo": "owner/two"},
        {"canonical_repo": "owner/one"},  # duplicate, dropped
        {"canonical_repo": "owner/three"},
    ]
    # limit 0 yields nothing (matches dedupe.dedupe_by_metric used by hn/reddit).
    assert youtube.dedupe_records(records, 0) == []
    # positive limit keeps first-seen unique repos up to the cap.
    kept = youtube.dedupe_records(records, 2)
    assert [r["canonical_repo"] for r in kept] == ["owner/one", "owner/two"]
