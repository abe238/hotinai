"""GitHub repository-search adapter for recently popular projects."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from hotin.canonical import canonicalize
from hotin.coerce import finite_int
from hotin.config import get as config_get
from hotin.throttle import Throttle


SOURCE = "github"
ENDPOINT = "https://api.github.com/search/repositories"
THROTTLE = Throttle(min_interval=1.0, jitter=0.5)
USER_AGENT = "hotin/0.2.0"


def _normalise_limit(limit: Any) -> int:
    return max(0, min(finite_int(limit, 50), 100))


def _cutoff_date(days: Any) -> str:
    """Return a safe UTC date ``days`` before today, defaulting to 90 days."""
    normalised_days = finite_int(days, 90)
    if normalised_days < 0:
        normalised_days = 90
    try:
        return (datetime.now(timezone.utc).date() - timedelta(days=normalised_days)).isoformat()
    except (OverflowError, ValueError):
        return (datetime.now(timezone.utc).date() - timedelta(days=90)).isoformat()


def build_search_url(query: Optional[str], limit: Any, days: Any = 90) -> str:
    """Purely construct the GitHub repository-search URL."""
    keyword = query.strip() if isinstance(query, str) else ""
    criteria = "created:>{} stars:>50".format(_cutoff_date(days))
    search = "{} {}".format(keyword, criteria).strip()
    parameters = {
        "q": search,
        "sort": "stars",
        "order": "desc",
        "per_page": _normalise_limit(limit),
    }
    return "{}?{}".format(ENDPOINT, urllib.parse.urlencode(parameters))


def _string_or_none(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _topics(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [topic for topic in value if isinstance(topic, str)]


def _license_spdx(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    spdx_id = value.get("spdx_id")
    return spdx_id if isinstance(spdx_id, str) else None


def parse_response(payload: Any) -> List[Dict[str, Any]]:
    """Turn a GitHub search JSON payload into Records without network I/O."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []

    records: List[Dict[str, Any]] = []
    try:
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("html_url")
            name = item.get("full_name")
            if not isinstance(url, str) or not isinstance(name, str):
                continue
            canonical_repo = canonicalize(url)
            if canonical_repo is None:
                continue
            archived = item.get("archived")
            records.append(
                {
                    "url": url,
                    "canonical_repo": canonical_repo,
                    "name": name,
                    "source": SOURCE,
                    "signal": {
                        "stars": finite_int(item.get("stargazers_count"), 0),
                        "created_at": _string_or_none(item.get("created_at")),
                        "pushed_at": _string_or_none(item.get("pushed_at")),
                        "language": _string_or_none(item.get("language")),
                        "forks": finite_int(item.get("forks_count"), 0),
                        "open_issues": finite_int(item.get("open_issues_count"), 0),
                    },
                    "meta": {
                        "description": _string_or_none(item.get("description")),
                        "topics": _topics(item.get("topics")),
                        "license": _license_spdx(item.get("license")),
                        "archived": archived if isinstance(archived, bool) else False,
                    },
                }
            )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
    return records


def _retry_after(headers: Any) -> Optional[float]:
    """Find the delay GitHub asks us to respect, if it provided one."""
    if headers is None:
        return None
    try:
        retry_after = headers.get("Retry-After")
        if retry_after is not None:
            delay = float(retry_after)
            if delay >= 0:
                return delay
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        if str(remaining) == "0" and reset is not None:
            return max(0.0, float(reset) - time.time())
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return None


def _request_search(url: str, token: Optional[str]) -> Tuple[Optional[Any], Optional[str]]:
    """Fetch one search response, returning payload or a human-readable error."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = "Bearer {}".format(token)
    try:
        request = urllib.request.Request(url, headers=headers)
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not isinstance(body, bytes):
            return None, "github response was not bytes"
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
            return None, "github returned invalid JSON"
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            return None, "github response schema invalid"
        return payload, None
    except urllib.error.HTTPError as error:
        if error.code in (403, 429):
            delay = _retry_after(error.headers)
            if delay is not None:
                try:
                    THROTTLE.wait_for_retry_after(delay)
                except (AttributeError, TypeError, ValueError, OverflowError):
                    pass
                return None, "rate limited"
        return None, "github HTTP error {}".format(error.code)
    except Exception:
        return None, "github request failed"


def fetch(
    query: Optional[str] = None,
    *,
    limit: int = 50,
    config: Optional[dict] = None,
    days: int = 90,
) -> Dict[str, Any]:
    """Fetch young, popular GitHub repositories, optionally narrowed by keyword."""
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        token = config_get(config, "GITHUB_TOKEN") if isinstance(config, Mapping) else None
        if not isinstance(token, str) or not token.strip():
            token = None
        payload, error = _request_search(build_search_url(query, requested_limit, days), token)
        if error is not None:
            return {"records": [], "status": "error", "detail": error}
        records = parse_response(payload)
        if not records:
            return {"records": [], "status": "empty", "detail": "no usable repositories found"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "github fetch failed"}


def selftest() -> None:
    """Exercise realistic and hostile parser fixtures without network I/O."""
    fixture = {
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
    records = parse_response(fixture)
    assert len(records) == 2
    assert records[0]["canonical_repo"] == "example/first"
    assert records[0]["signal"]["stars"] == 320
    assert records[0]["meta"]["license"] == "MIT"

    hostile = {
        "items": [
            {
                "html_url": "https://github.com/example/missing-stars",
                "full_name": "example/missing-stars",
                "license": None,
                "topics": "not-a-list",
            },
            {
                "html_url": "https://github.com/example/hostile",
                "full_name": "example/hostile",
                "stargazers_count": 1e309,
                "forks_count": "bad",
                "open_issues_count": None,
                "topics": "not-a-list",
                "license": None,
            }
        ]
    }
    hostile_records = parse_response(hostile)
    assert len(hostile_records) == 2
    assert all(record["signal"]["stars"] == 0 for record in hostile_records)
    assert hostile_records[0]["meta"]["topics"] == []
    assert parse_response({"items": "not-a-list"}) == []
    print("github selftest: ok")


if __name__ == "__main__":
    selftest()
