"""the public repo-trends API weekly repository-momentum adapter."""

from __future__ import annotations

import json
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
    """Accept both the public repo-trends API's positional and object row representations."""
    if isinstance(row, dict):
        return row
    if not isinstance(row, list) or len(row) < len(columns):
        return None
    try:
        return dict(zip(columns, row))
    except (TypeError, ValueError, OverflowError):
        return None


def parse_response(payload: Any) -> List[Dict[str, Any]]:
    """Purely convert an the public repo-trends API JSON response into hotin Records.

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


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def _normalise_period(period: Any) -> str:
    return period if isinstance(period, str) and period in _PERIODS else "past_week"


def _request_payload(period: str) -> Optional[Dict[str, Any]]:
    """Fetch and decode one response, returning None for every request failure."""
    try:
        url = "{}?{}".format(ENDPOINT, urllib.parse.urlencode({"period": period}))
        request = urllib.request.Request(url, headers={"User-Agent": "hotin/0.0.1"})
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
    """Fetch the public repo-trends API's precomputed repository trends without an API key."""
    del query, config
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}

        payload = _request_payload(_normalise_period(period))
        if payload is None:
            return {"records": [], "status": "error", "detail": "trends request failed"}
        if not _has_expected_shape(payload):
            return {"records": [], "status": "error", "detail": "trends response was malformed"}

        records = parse_response(payload)
        if not records:
            return {"records": [], "status": "empty", "detail": "no usable GitHub repositories found"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "trends fetch failed"}


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
