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
_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.IGNORECASE)
_HF_MODEL_RE = re.compile(r"huggingface\.co/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE)
_HF_RESERVED = {"papers", "datasets", "models", "spaces", "blog", "docs", "collections"}


def _classify(hit: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """Classify an HN story by its link into (entity_type, entity_id, url).

    A GitHub link -> repo, an arXiv link -> paper, a HuggingFace model link ->
    model. Returns None for a story that is none of these (kept out of hotin's
    entity views rather than mis-filed as a repo).
    """
    reference = _github_reference(hit)
    if reference is not None:
        return ("repo", reference[1], reference[0])
    blob = " ".join(
        hit.get(field, "") for field in ("url", "story_text") if isinstance(hit.get(field), str)
    )
    arxiv = _ARXIV_RE.search(blob)
    if arxiv is not None:
        return ("paper", arxiv.group(1), "https://arxiv.org/abs/{}".format(arxiv.group(1)))
    model = _HF_MODEL_RE.search(blob)
    if model is not None:
        slug = model.group(1)
        if slug.split("/", 1)[0].lower() not in _HF_RESERVED:
            return ("model", slug, "https://huggingface.co/{}".format(slug))
    return None


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
            classified = _classify(hit)
            if classified is None:
                continue
            entity_type, entity_id, url = classified
            record: Dict[str, Any] = {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "url": url,
                "name": title.strip(),
                "source": SOURCE,
                "signal": {"hn_points": points, "hn_comments": comments},
                "meta": {"hn_id": hn_id, "hn_title": title.strip()},
            }
            if entity_type == "repo":
                record["canonical_repo"] = entity_id
            records.append(record)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
    return records


def dedupe_records(records: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Keep the highest-points HN submission per entity (repo, paper, or model)."""
    return dedupe_by_metric(records, limit, "hn_points", finite_int, key="entity_id")


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
                "url": "https://arxiv.org/abs/2506.12345",
                "points": 200,
                "num_comments": 30,
                "objectID": "five",
                "title": "A new paper",
            },
            {
                "url": "https://huggingface.co/deepseek-ai/DeepSeek-V4",
                "points": 175,
                "num_comments": 25,
                "objectID": "six",
                "title": "New model drop",
            },
            {
                "url": "https://huggingface.co/papers/2506.99999",
                "points": 300,
                "num_comments": 40,
                "objectID": "seven",
                "title": "HF papers page, not a model",
            },
            {
                "url": "https://example.com/nope",
                "points": 500,
                "num_comments": 50,
                "objectID": "eight",
                "title": "Not classifiable",
            },
        ]
    }
    records = dedupe_records(parse_response(payload), 50)
    by_type = {(r["entity_type"], r["entity_id"]) for r in records}
    assert ("repo", "example/useful") in by_type
    assert ("repo", "example/body-link") in by_type
    assert ("paper", "2506.12345") in by_type
    assert ("model", "deepseek-ai/DeepSeek-V4") in by_type
    # reserved HF first-segment (papers/) is not a model; unclassifiable is dropped
    assert not any(r["entity_id"].startswith("papers/") for r in records)
    assert all(r["url"] != "https://example.com/nope" for r in records)
    # highest-points duplicate of a repo wins
    repo = next(r for r in records if r["entity_id"] == "example/useful")
    assert repo["signal"]["hn_points"] == 150
    assert parse_response(
        {"hits": [{"url": "https://github.com/example/repo", "points": 1e309}]}
    ) == []
    print("hn selftest: ok")


if __name__ == "__main__":
    selftest()
