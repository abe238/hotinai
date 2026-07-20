"""npm download-velocity adapter for GitHub-linked JavaScript packages."""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from hotin.canonical import canonicalize
from hotin.throttle import Throttle


SOURCE = "npm"
SEARCH_ENDPOINT = "https://registry.npmjs.org/-/v1/search"
DOWNLOADS_ENDPOINT = "https://api.npmjs.org/downloads/range/last-month/"
DEFAULT_QUERIES = ("llm", "ai agent", "rag", "mcp server", "vector database")
THROTTLE = Throttle(min_interval=1.5, jitter=0.5)
USER_AGENT = "hotin/0.0.1"


def _empty(detail: str) -> Dict[str, Any]:
    return {"records": [], "status": "empty", "detail": detail}


def _normalise_limit(limit: Any) -> int:
    if isinstance(limit, bool) or limit is None:
        return 50
    try:
        return max(0, int(limit))
    except (TypeError, ValueError, OverflowError):
        return 50


def _github_repo(package: Dict[str, Any]) -> Optional[str]:
    """Find the registry-attributed GitHub repository for one package."""
    links = package.get("links")
    if not isinstance(links, dict):
        return None
    for key in ("repository", "homepage"):
        candidate = links.get(key)
        if not isinstance(candidate, str):
            continue
        canonical = canonicalize(candidate)
        if canonical:
            return canonical
    return None


def parse_search_response(payload: Any) -> List[Dict[str, str]]:
    """Purely parse a registry search response into package/repository pairs."""
    if not isinstance(payload, dict):
        return []
    objects = payload.get("objects")
    if not isinstance(objects, list):
        return []

    candidates: List[Dict[str, str]] = []
    try:
        for item in objects:
            if not isinstance(item, dict):
                continue
            package = item.get("package")
            if not isinstance(package, dict):
                continue
            name = package.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            canonical_repo = _github_repo(package)
            if not canonical_repo:
                continue
            candidates.append(
                {"npm_package": name.strip(), "canonical_repo": canonical_repo}
            )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
    return candidates


def _finite_download(value: Any) -> Optional[float]:
    """Accept only finite numeric download counts from an individual day."""
    if not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def parse_downloads_response(payload: Any) -> Optional[Tuple[float, float]]:
    """Return last-seven downloads and week-over-week growth, or ``None``.

    ``None`` denotes a malformed downloads response.  A valid response with no
    usable days returns ``(0.0, 0.0)`` so callers can classify it as no signal.
    """
    if not isinstance(payload, dict):
        return None
    days = payload.get("downloads")
    if not isinstance(days, list):
        return None

    values: List[float] = []
    try:
        for entry in days:
            if not isinstance(entry, dict):
                continue
            numeric = _finite_download(entry.get("downloads"))
            if numeric is None:
                continue
            values.append(numeric)

        if len(values) < 7:
            return (sum(values), 0.0)
        last_7 = sum(values[-7:])
        if not math.isfinite(last_7):
            return (0.0, 0.0)
        if len(values) < 14:
            return (last_7, 0.0)
        prior_7 = sum(values[-14:-7])
        if not math.isfinite(prior_7):
            return (last_7, 0.0)
        growth = (last_7 - prior_7) / prior_7 if prior_7 else 0.0
        return (last_7, growth if math.isfinite(growth) else 0.0)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def build_record(candidate: Any, downloads_payload: Any) -> Optional[Dict[str, Any]]:
    """Purely join a parsed package candidate to its downloads response."""
    if not isinstance(candidate, dict):
        return None
    package_name = candidate.get("npm_package")
    canonical_repo = candidate.get("canonical_repo")
    if not isinstance(package_name, str) or not isinstance(canonical_repo, str):
        return None
    # Run every emitted reference through the common normalizer, even though
    # candidates ordinarily came from it too.
    canonical_repo = canonicalize(canonical_repo)
    if not canonical_repo:
        return None
    velocity = parse_downloads_response(downloads_payload)
    if velocity is None:
        return None
    last_7, growth = velocity
    if last_7 <= 0:
        return None
    return {
        "url": "https://github.com/{}".format(canonical_repo),
        "canonical_repo": canonical_repo,
        "name": package_name,
        "source": SOURCE,
        "signal": {"npm_downloads_week": last_7, "npm_growth": round(growth, 3)},
        "meta": {"npm_package": package_name},
    }


def _request_json(url: str) -> Optional[Any]:
    """Request one JSON endpoint, converting every transport failure to None."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not isinstance(body, bytes):
            return None
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _search_url(query: str) -> str:
    return "{}?{}".format(
        SEARCH_ENDPOINT,
        urllib.parse.urlencode({"text": query, "size": 40, "popularity": "1.0"}),
    )


def _downloads_url(package_name: str) -> str:
    return "{}{}".format(DOWNLOADS_ENDPOINT, urllib.parse.quote(package_name, safe=""))


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Fetch GitHub-linked npm packages with month-over-month download velocity."""
    del config  # npm's public registry endpoints do not require a key.
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return _empty("limit is zero")
        queries = (query,) if isinstance(query, str) and query.strip() else DEFAULT_QUERIES
        candidates: List[Dict[str, str]] = []
        seen_packages = set()
        successful_searches = 0
        for term in queries:
            payload = _request_json(_search_url(term))
            if payload is None or not isinstance(payload, dict) or not isinstance(payload.get("objects"), list):
                continue
            successful_searches += 1
            for candidate in parse_search_response(payload):
                package_name = candidate["npm_package"]
                if package_name not in seen_packages:
                    seen_packages.add(package_name)
                    candidates.append(candidate)

        if successful_searches == 0:
            return {"records": [], "status": "error", "detail": "npm search requests failed"}
        if not candidates:
            return _empty("no GitHub-linked npm packages found")

        records: List[Dict[str, Any]] = []
        successful_downloads = 0
        for candidate in candidates:
            payload = _request_json(_downloads_url(candidate["npm_package"]))
            if payload is None or not isinstance(payload, dict) or not isinstance(payload.get("downloads"), list):
                continue
            successful_downloads += 1
            record = build_record(candidate, payload)
            if record is not None:
                records.append(record)

        if successful_downloads == 0:
            return {"records": [], "status": "error", "detail": "npm download requests failed"}
        if not records:
            return _empty("no npm packages with recent downloads found")
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "npm fetch failed"}


def selftest() -> None:
    """Exercise the pure parsers against representative and hostile fixtures."""
    search = {
        "objects": [
            {"package": {"name": "repo-package", "links": {"repository": "https://github.com/Example/Repo"}}},
            {"package": {"name": "home-package", "links": {"homepage": "https://github.com/Example/Home"}}},
            {"package": {"name": "bad-links", "links": "not a dictionary"}},
            {"package": {"links": {"repository": "https://github.com/example/no-name"}}},
        ]
    }
    candidates = parse_search_response(search)
    assert [item["canonical_repo"] for item in candidates] == ["example/repo", "example/home"]
    downloads = {"downloads": [{"day": None, "downloads": 10}, {"day": "bad", "downloads": 10}] + [{"day": "2026-07-{:02d}".format(day), "downloads": 10} for day in range(1, 13)]}
    record = build_record(candidates[0], downloads)
    assert record is not None and record["signal"] == {"npm_downloads_week": 70.0, "npm_growth": 0.0}
    assert parse_search_response({"objects": [{"package": {"name": "x", "links": []}}]}) == []
    assert parse_downloads_response({"downloads": [{"downloads": None}, {"downloads": "99"}, {"downloads": float("inf")} ]}) == (0, 0.0)
    assert parse_downloads_response({"downloads": "not a list"}) is None
    print("npm selftest: ok")


if __name__ == "__main__":
    selftest()
