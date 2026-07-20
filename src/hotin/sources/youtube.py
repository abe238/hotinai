"""YouTube videos surfaced through the optional ScrapeCreators API."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from hotin.canonical import GITHUB_URL_IN_TEXT_RE, canonicalize, trim_glued_repo_name
from hotin.coerce import finite_int
from hotin.throttle import Throttle


SOURCE = "youtube"
ENDPOINT = "https://api.scrapecreators.com/v1/youtube/search"
DEFAULT_QUERIES = ("new AI tool", "AI agent github", "open source AI")
THROTTLE = Throttle(min_interval=2.0, jitter=1.0)


def _empty(detail: str) -> Dict[str, Any]:
    return {"records": [], "status": "empty", "detail": detail}


def _github_reference(text: Any) -> Optional[Tuple[str, str]]:
    """Return the first canonical repository link in a video text field."""
    if not isinstance(text, str):
        return None
    for match in GITHUB_URL_IN_TEXT_RE.finditer(text):
        owner, repo = match.groups()
        repo = trim_glued_repo_name(repo)
        canonical = canonicalize("{}/{}".format(owner, repo))
        if canonical:
            return "https://github.com/{}".format(canonical), canonical
    return None


def _description_reference(video: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Check the documented description and common snippet alternative."""
    for key in ("description", "snippet"):
        reference = _github_reference(video.get(key))
        if reference is not None:
            return reference
    return None


def _view_count(video: Dict[str, Any]) -> Optional[int]:
    """Read documented and compatibility view-count fields without guessing text."""
    for key in ("viewCountInt", "viewCount", "view_count"):
        if key in video:
            value = finite_int(video.get(key))
            if value is not None:
                return value
    return None


def _published_at(video: Dict[str, Any]) -> Optional[str]:
    for key in ("publishedTime", "publishedAt", "published_at"):
        value = video.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _channel_name(video: Dict[str, Any]) -> Optional[str]:
    channel = video.get("channel")
    if not isinstance(channel, dict):
        return None
    title = channel.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


def parse_response(payload: Any) -> List[Dict[str, Any]]:
    """Purely parse one ScrapeCreators YouTube search response.

    Search responses only yield records when a video's supplied description or
    snippet contains a canonicalizable GitHub repository link.  Every malformed
    item is ignored so this parser remains safe for adversarial fixtures.
    """
    if not isinstance(payload, dict):
        return []
    videos = payload.get("videos")
    if not isinstance(videos, list):
        return []

    records: List[Dict[str, Any]] = []
    try:
        for video in videos:
            if not isinstance(video, dict):
                continue
            reference = _description_reference(video)
            if reference is None:
                continue
            video_id = video.get("id")
            if not isinstance(video_id, str) or not video_id.strip():
                continue
            url, canonical_repo = reference
            title = video.get("title")
            name = title.strip() if isinstance(title, str) and title.strip() else canonical_repo

            signal: Dict[str, Any] = {}
            views = _view_count(video)
            if views is not None:
                signal["youtube_views"] = views
            published_at = _published_at(video)
            if published_at is not None:
                signal["youtube_published_at"] = published_at

            meta: Dict[str, Any] = {
                "youtube_title": title.strip() if isinstance(title, str) and title.strip() else name,
                "youtube_video_id": video_id.strip(),
            }
            channel = _channel_name(video)
            if channel is not None:
                meta["youtube_channel"] = channel

            records.append(
                {
                    "url": url,
                    "canonical_repo": canonical_repo,
                    "name": name,
                    "source": SOURCE,
                    "signal": signal,
                    "meta": meta,
                }
            )
    except (TypeError, ValueError, OverflowError, AttributeError):
        return []
    return records


def dedupe_records(records: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Keep the first video mentioning each repository across search queries."""
    try:
        seen: Set[str] = set()
        result: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            canonical = record.get("canonical_repo")
            if not isinstance(canonical, str) or canonical in seen:
                continue
            seen.add(canonical)
            result.append(record)
            if len(result) >= limit:
                break
        return result
    except (TypeError, ValueError, OverflowError, AttributeError):
        return []


def _request_search(query: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Fetch one search response, returning ``None`` for all transport failures."""
    try:
        request_url = "{}?{}".format(
            ENDPOINT, urllib.parse.urlencode({"query": query, "includeExtras": "true"})
        )
        request = urllib.request.Request(
            request_url,
            headers={"x-api-key": api_key, "User-Agent": "hotin/0.0.1"},
        )
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not isinstance(body, bytes):
            return None
        payload = json.loads(body.decode("utf-8"))
        return payload if isinstance(payload, dict) and isinstance(payload.get("videos"), list) else None
    except (Exception,):
        return None


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Fetch repositories linked from AI-tool YouTube video descriptions."""
    try:
        api_key = config.get("SCRAPECREATORS_API_KEY") if isinstance(config, dict) else None
        if not isinstance(api_key, str) or not api_key.strip():
            return _empty("no SCRAPECREATORS_API_KEY configured")

        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return _empty("limit is zero")

        queries = (query.strip(),) if isinstance(query, str) and query.strip() else DEFAULT_QUERIES
        parsed: List[Dict[str, Any]] = []
        successful_queries = 0
        for search_query in queries:
            payload = _request_search(search_query, api_key)
            if payload is None:
                continue
            successful_queries += 1
            parsed.extend(parse_response(payload))

        if successful_queries == 0:
            return {"records": [], "status": "error", "detail": "all YouTube search requests failed"}
        records = dedupe_records(parsed, requested_limit)
        if not records:
            return _empty("no GitHub repositories found")
        return {"records": records, "status": "ok", "detail": None}
    except (Exception,):
        return {"records": [], "status": "error", "detail": "youtube fetch failed"}


def selftest() -> None:
    """Exercise parser-only valid and hostile response fixtures."""
    response = {
        "videos": [
            {
                "id": "demo-1",
                "title": "An excellent project",
                "description": "Source: https://github.com/Example/Useful-Tool).",
                "viewCountInt": "1200",
                "publishedTime": "2026-07-01T12:00:00Z",
                "channel": {"title": "Example Channel"},
            },
            {"id": "no-link", "title": "No linked repository", "description": "No links here."},
        ]
    }
    records = parse_response(response)
    assert len(records) == 1
    assert records[0]["canonical_repo"] == "example/useful-tool"
    assert records[0]["signal"]["youtube_views"] == 1200
    assert records[0]["meta"]["youtube_channel"] == "Example Channel"
    assert parse_response({"videos": [{"id": "bad", "description": None}]}) == []
    hostile = {
        "videos": [
            {
                "id": "hostile",
                "description": "https://github.com/example/hostile",
                "viewCountInt": "not-a-number",
            }
        ]
    }
    assert parse_response(hostile)[0]["signal"] == {}
    print("youtube selftest: ok")


if __name__ == "__main__":
    selftest()
