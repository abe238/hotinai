"""Recent, high-traction Hacker News stories that point at GitHub repos."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

from hotin.canonical import canonicalize, trim_glued_repo_name
from hotin.coerce import finite_int
from hotin.dedupe import dedupe_by_metric
from hotin.throttle import Throttle


SOURCE = "hn"
ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
THROTTLE = Throttle(min_interval=1.0, jitter=0.5)
DEFAULT_MIN_POINTS = 50
DEFAULT_DAYS = 30

# Kept deliberately close to the documented extraction rule.  A story URL can
# point elsewhere while its Show HN body contains the repository link.
_GITHUB_REPO_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([\w.-]+/[\w.-]+)", re.IGNORECASE
)


def _github_reference(hit: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Find the first usable repository URL in an HN story's URL or body."""
    try:
        candidates: List[str] = []
        url = hit.get("url")
        if isinstance(url, str):
            candidates.append(url)

        for candidate in candidates:
            for match in _GITHUB_REPO_RE.finditer(candidate):
                slug = match.group(1)
                # canonicalize() rejects reserved paths such as github.com/blog.
                canonical_repo = canonicalize("https://github.com/{}".format(slug))
                if canonical_repo:
                    return "https://github.com/{}".format(canonical_repo), canonical_repo

        story_text = hit.get("story_text")
        if isinstance(story_text, str):
            for match in _GITHUB_REPO_RE.finditer(story_text):
                owner, repo = match.group(1).rsplit("/", 1)
                repo = trim_glued_repo_name(repo)
                canonical_repo = canonicalize("https://github.com/{}/{}".format(owner, repo))
                if canonical_repo:
                    return "https://github.com/{}".format(canonical_repo), canonical_repo
    except (AttributeError, TypeError, ValueError, OverflowError, re.error):
        return None
    return None


def parse_response(payload: Any) -> List[Dict[str, Any]]:
    """Purely turn an HN Algolia response into Records, ignoring bad hits.

    The parser performs no I/O and is intentionally defensive so fixture and
    live-response shape changes cannot escape this source adapter as errors.
    """
    if not isinstance(payload, dict):
        return []
    hits = payload.get("hits")
    if not isinstance(hits, list):
        return []

    records: List[Dict[str, Any]] = []
    try:
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            points = finite_int(hit.get("points"))
            comments = finite_int(hit.get("num_comments"))
            hn_id = hit.get("objectID")
            title = hit.get("title")
            if (
                points is None
                or comments is None
                or not isinstance(hn_id, str)
                or not hn_id.strip()
                or not isinstance(title, str)
                or not title.strip()
            ):
                continue
            reference = _github_reference(hit)
            if reference is None:
                continue
            url, canonical_repo = reference
            records.append(
                {
                    "url": url,
                    "canonical_repo": canonical_repo,
                    "name": title.strip(),
                    "source": SOURCE,
                    "signal": {"hn_points": points, "hn_comments": comments},
                    "meta": {"hn_id": hn_id, "hn_title": title.strip()},
                }
            )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
    return records


def dedupe_records(records: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Keep the highest-points HN submission for each canonical repository."""
    return dedupe_by_metric(records, limit, "hn_points", finite_int)


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit, 50)
    return max(0, value if value is not None else 50)


def _settings(config: Optional[dict]) -> Tuple[int, int]:
    """Read optional non-secret tuning values while retaining safe defaults."""
    if not isinstance(config, dict):
        return DEFAULT_MIN_POINTS, DEFAULT_DAYS
    min_points = finite_int(config.get("HN_MIN_POINTS"), DEFAULT_MIN_POINTS)
    days = finite_int(config.get("HN_DAYS"), DEFAULT_DAYS)
    return max(0, min_points if min_points is not None else DEFAULT_MIN_POINTS), max(
        1, days if days is not None else DEFAULT_DAYS
    )


def _request(min_points: int, days: int) -> Optional[Dict[str, Any]]:
    """Fetch the documented recent-first HN endpoint, or return None on failure."""
    try:
        cutoff = int(time.time()) - (days * 24 * 60 * 60)
        params = urllib.parse.urlencode(
            {
                "tags": "story",
                "numericFilters": "points>{},created_at_i>{}".format(min_points, cutoff),
                "hitsPerPage": 1000,
            }
        )
        request = urllib.request.Request(
            "{}?{}".format(ENDPOINT, params), headers={"User-Agent": "hotin/0.2.0"}
        )
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not isinstance(body, bytes):
            return None
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
            return None
        return payload
    except Exception:
        return None


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Fetch recently submitted, high-scoring GitHub repositories from HN."""
    del query  # HN filtering is intentionally fixed to recent high-traction stories.
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        min_points, days = _settings(config)
        payload = _request(min_points, days)
        if payload is None:
            return {"records": [], "status": "error", "detail": "hn request failed"}
        records = dedupe_records(parse_response(payload), requested_limit)
        if not records:
            return {"records": [], "status": "empty", "detail": "no GitHub repositories found"}
        return {"records": records, "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "hn fetch failed"}


def selftest() -> None:
    """Exercise parser-only realistic, duplicate, and hostile fixtures."""
    payload = {
        "hits": [
            {
                "url": "https://github.com/Example/Useful",
                "points": 90,
                "num_comments": 12,
                "objectID": "one",
                "title": "Useful project",
            },
            {
                "story_text": "Show HN: https://github.com/example/body-link is ready.",
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
                "title": "Not a repository",
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
    records = dedupe_records(parse_response(payload), 50)
    assert [record["canonical_repo"] for record in records] == ["example/useful", "example/body-link"]
    assert records[0]["signal"]["hn_points"] == 150
    assert parse_response(
        {"hits": [{"url": "https://github.com/example/repo", "points": 1e309}]}
    ) == []
    print("hn selftest: ok")


if __name__ == "__main__":
    selftest()
