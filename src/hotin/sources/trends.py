"""Weekly repository-momentum adapter (a curated trend-signal API)."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from hotin.canonical import canonicalize
from hotin.coerce import finite_float, finite_int
from hotin.throttle import Throttle


SOURCE = "trends"
ENDPOINT = "https://api.ossinsight.io/v1/trends/repos/"
THROTTLE = Throttle(min_interval=2.0, jitter=1.0)
_PERIODS = {"past_week", "past_month"}
# ossinsight's ranking is retired upstream (2026-03-01), so GitHub's own Trending page
# is the momentum signal: the only source that sees an OLD repo exploding today.
TRENDING_URL = "https://github.com/trending"
_SINCE = {"past_week": "weekly", "past_month": "monthly"}


def _unavailable_detail(payload: Any) -> str:
    """The upstream's own `data_quality` verdict, when it publishes one."""
    quality = payload.get("data_quality") if isinstance(payload, dict) else None
    if isinstance(quality, dict) and quality.get("status") == "unavailable":
        since = quality.get("unavailable_since")
        return ("upstream ranking RETIRED by the provider{}; this source cannot return rows "
                "and is not a quiet day".format(" since {}".format(since) if since else ""))
    return "no usable GitHub repositories found"


def _column_names(columns: Any) -> Optional[List[str]]:
    """Return the documented column names, or None for a malformed response."""
    if not isinstance(columns, list):
        return None
    names: List[str] = []
    try:
        for column in columns:
            if not isinstance(column, dict):
                return None
            name = column.get("col")
            if not isinstance(name, str) or not name:
                return None
            names.append(name)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return names


def _row_values(row: Any, columns: List[str]) -> Optional[Dict[str, Any]]:
    """Accept both the source's positional and object row representations."""
    if isinstance(row, dict):
        return row
    if not isinstance(row, list) or len(row) < len(columns):
        return None
    try:
        return dict(zip(columns, row))
    except (TypeError, ValueError, OverflowError):
        return None


def parse_response(payload: Any) -> List[Dict[str, Any]]:
    """Purely convert an the trend-signal source JSON response into hotin Records.

    Invalid response shapes and malformed rows are skipped.  This function has
    no network side effects so fixtures can exercise both row encodings.
    """
    if not isinstance(payload, dict):
        return []
    try:
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        columns = _column_names(data.get("columns"))
        rows = data.get("rows")
        if columns is None or not isinstance(rows, list):
            return []

        records: List[Dict[str, Any]] = []
        for row in rows:
            values = _row_values(row, columns)
            if values is None:
                continue
            repo_value = values.get("repo_name")
            if not isinstance(repo_value, str):
                repo_value = values.get("full_name")
            if not isinstance(repo_value, str):
                continue
            canonical_repo = canonicalize(repo_value)
            if canonical_repo is None:
                continue

            signal: Dict[str, Any] = {}
            for column in ("stars", "pull_requests", "pushes"):
                metric = finite_int(values.get(column))
                if metric is not None:
                    signal["trend_{}".format(column)] = metric

            # The current live endpoint exposes total_score.  Older variants
            # have used collection_score, so retain support for that schema.
            for score_column in ("total_score", "collection_score"):
                score = finite_float(values.get(score_column))
                if score is not None:
                    signal["trend_{}".format(score_column)] = score
                    break

            language = values.get("language", values.get("primary_language"))
            description = values.get("description")
            meta: Dict[str, Any] = {}
            if isinstance(language, str):
                meta["language"] = language
            if isinstance(description, str):
                meta["description"] = description

            records.append(
                {
                    "url": "https://github.com/{}".format(canonical_repo),
                    "canonical_repo": canonical_repo,
                    "name": canonical_repo,
                    "source": SOURCE,
                    "signal": signal,
                    "meta": meta,
                }
            )
        return records
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []


def parse_trending_html(page: Any) -> List[Dict[str, Any]]:
    """Purely convert a github.com/trending page into hotin Records."""
    # ponytail: regex over GitHub's HTML; if the markup changes this returns [] and the
    # source reads "empty" (health check surfaces it), never wrong rows.
    if not isinstance(page, str):
        return []
    records: List[Dict[str, Any]] = []
    for block in re.findall(r'<article class="Box-row">(.*?)</article>', page, re.S):
        repo = re.search(r'href="/([^"/?]+/[^"/?]+)/stargazers"', block)
        canonical_repo = canonicalize(repo.group(1)) if repo else None
        if canonical_repo is None:
            continue
        signal: Dict[str, Any] = {}
        stars = re.search(r"([\d,]+)\s+stars?\s+(?:today|this week|this month)", block)
        if stars:
            signal["trend_stars"] = finite_int(stars.group(1).replace(",", ""))
        meta: Dict[str, Any] = {}
        language = re.search(r'itemprop="programmingLanguage">([^<]+)<', block)
        if language:
            meta["language"] = html.unescape(language.group(1)).strip()
        description = re.search(r'<p class="[^"]*">(.*?)</p>', block, re.S)
        if description:
            text = re.sub(r"<[^>]+>", "", html.unescape(description.group(1)))
            text = " ".join(text.split())
            if text:
                meta["description"] = text
        records.append({
            "url": "https://github.com/{}".format(canonical_repo),
            "canonical_repo": canonical_repo,
            "name": canonical_repo,
            "source": SOURCE,
            "signal": signal,
            "meta": meta,
        })
    return records


def _request_trending(since: str) -> Optional[str]:
    """Fetch one github.com/trending page, returning None for every request failure."""
    try:
        url = "{}?{}".format(TRENDING_URL, urllib.parse.urlencode({"since": since}))
        request = urllib.request.Request(url, headers={"User-Agent": "hotin/0.2.0"})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:
        return None


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def _normalise_period(period: Any) -> str:
    return period if isinstance(period, str) and period in _PERIODS else "past_week"


def _request_payload(period: str) -> Optional[Dict[str, Any]]:
    """Fetch and decode one response, returning None for every request failure."""
    try:
        url = "{}?{}".format(ENDPOINT, urllib.parse.urlencode({"period": period}))
        request = urllib.request.Request(url, headers={"User-Agent": "hotin/0.2.0"})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not isinstance(body, bytes):
            return None
        payload = json.loads(body.decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _has_expected_shape(payload: Any) -> bool:
    """Distinguish a valid-but-empty feed from a malformed API response."""
    try:
        return (
            isinstance(payload, dict)
            and isinstance(payload.get("data"), dict)
            and _column_names(payload["data"].get("columns")) is not None
            and isinstance(payload["data"].get("rows"), list)
        )
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return False


def fetch(
    query: Optional[str] = None,
    *,
    limit: int = 50,
    config: Optional[dict] = None,
    period: str = "past_week",
) -> Dict[str, Any]:
    """Fetch the source's precomputed repository trends without an API key."""
    del query, config
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}

        normalised_period = _normalise_period(period)
        payload = _request_payload(normalised_period)
        records = parse_response(payload) if _has_expected_shape(payload) else []
        if not records:
            # daily first: an explosion today (morluto/rea, 2026-10-14) is not on weekly yet
            seen = set()
            for since in ("daily", _SINCE[normalised_period]):
                for record in parse_trending_html(_request_trending(since)):
                    if record["canonical_repo"] not in seen:
                        seen.add(record["canonical_repo"])
                        records.append(record)
            if records:
                return {"records": records[:requested_limit], "status": "ok", "detail": None}
        if payload is None:
            return {"records": [], "status": "error", "detail": "trend-signal request failed"}
        if not _has_expected_shape(payload):
            return {"records": [], "status": "error", "detail": "trend-signal response was malformed"}
        if not records:
            # The upstream declares its own availability. Say what it says, rather than
            # reporting a bare "empty" that reads like a quiet day: this ranking has been
            # unavailable since 2026-03-01 (their GitHub event capture fell to ~0.3% of
            # baseline), so the source has contributed exactly zero for months while looking
            # like a source that simply had nothing today. A scout that can never return ok
            # must not be mistaken for one that might.
            return {"records": [], "status": "empty", "detail": _unavailable_detail(payload)}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "trend-signal fetch failed"}


def selftest() -> None:
    """Run fixture-only parser checks without making a network request."""
    columns = [
        {"col": "repo_name"},
        {"col": "primary_language"},
        {"col": "description"},
        {"col": "stars"},
        {"col": "pull_requests"},
        {"col": "pushes"},
        {"col": "total_score"},
    ]
    positional = {
        "data": {
            "columns": columns,
            "rows": [["Example/Project", "Python", "A project", "12", "3", "4", "9.5"]],
        }
    }
    object_rows = {
        "data": {
            "columns": columns,
            "rows": [
                {
                    "repo_name": "Example/Project",
                    "primary_language": "Python",
                    "description": "A project",
                    "stars": "12",
                    "pull_requests": "3",
                    "pushes": "4",
                    "total_score": "9.5",
                }
            ],
        }
    }
    assert parse_response(positional) == parse_response(object_rows)
    assert parse_response(positional)[0]["canonical_repo"] == "example/project"
    hostile = {"data": {"columns": columns, "rows": [["too-short"], "not-a-row"]}}
    assert parse_response(hostile) == []
    assert parse_response({"data": {"rows": []}}) == []
    print("trends selftest: ok")


if __name__ == "__main__":
    selftest()
