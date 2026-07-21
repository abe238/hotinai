"""AI-topic growth AI collection rankings (repository entity).

AI-topic growth publishes public repository collections, including several AI-focused
ones used by its AI trending page.  This adapter discovers those collections and
combines their star rankings without an API key or any runtime dependency beyond
the standard library.  It is deliberately best-effort: bad API rows are skipped
and fetch failures are always returned as a result dictionary, never raised.
"""

from __future__ import annotations

import gzip
import json
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from hotin.canonical import canonicalize
from hotin.coerce import finite_int
from hotin.throttle import Throttle


SOURCE = "collections"
ENDPOINT = "https://api.ossinsight.io/v1/collections/"
THROTTLE = Throttle(min_interval=1.5, jitter=0.5)
USER_AGENT = "hotin/0.2.0"
MAX_COLLECTIONS = 8
_AI_TERMS = ("ai", "llm", "artificial", "agent", "rag", "inference", "machine learning")


def _request(url: str) -> Optional[Any]:
    """Fetch and decode an AI-topic growth JSON response, or return None on failure."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
        if not isinstance(body, bytes):
            return None
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def parse_collections(payload: Any) -> List[Tuple[int, str]]:
    """Return at most eight AI-relevant ``(id, name)`` collection pairs."""
    if not isinstance(payload, dict):
        return []
    try:
        rows = payload.get("data", payload.get("rows"))
        if isinstance(rows, dict):
            rows = rows.get("rows")
        if not isinstance(rows, list):
            return []
        collections: List[Tuple[int, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            collection_id = finite_int(row.get("id"))
            name = row.get("name")
            if collection_id is None or not isinstance(name, str):
                continue
            name = name.strip()
            if not name or not any(term in name.lower() for term in _AI_TERMS):
                continue
            collections.append((collection_id, name))
            if len(collections) >= MAX_COLLECTIONS:
                break
        return collections
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []


def _ranking_rows(payload: Any) -> List[Any]:
    """Accept either ``data.rows`` or the top-level ``rows`` response shape."""
    if not isinstance(payload, dict):
        return []
    try:
        data = payload.get("data")
        rows = data.get("rows") if isinstance(data, dict) else payload.get("rows")
        return rows if isinstance(rows, list) else []
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []


def parse_ranking(payload: Any, collection_name: Any) -> List[Dict[str, Any]]:
    """Purely turn one collection's ranking payload into repository records."""
    if not isinstance(collection_name, str):
        return []
    records: List[Dict[str, Any]] = []
    try:
        for row in _ranking_rows(payload):
            if not isinstance(row, dict):
                continue
            repo_name = row.get("repo_name")
            if not isinstance(repo_name, str) or "/" not in repo_name:
                continue
            canonical = canonicalize("https://github.com/{}".format(repo_name))
            if not canonical:
                continue
            records.append(
                {
                    "entity_type": "repo",
                    "entity_id": canonical,
                    "canonical_repo": canonical,
                    "url": "https://github.com/{}".format(canonical),
                    "name": canonical,
                    "source": SOURCE,
                    "signal": {
                        "stars": finite_int(row.get("total"), 0),
                        "stars_growth": finite_int(row.get("current_period_growth"), 0),
                        "collections_rank": finite_int(row.get("current_period_rank")),
                    },
                    "meta": {"collection": collection_name, "on_trending_list": True},
                }
            )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
    return records


def dedupe_records(records: Any) -> List[Dict[str, Any]]:
    """Keep each repository's greatest observed star-growth record, sorted first."""
    if not isinstance(records, list):
        return []
    try:
        deduped: Dict[str, Dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("entity_id"), str):
                continue
            entity_id = record["entity_id"]
            growth = finite_int(record.get("signal", {}).get("stars_growth"), 0)
            previous = deduped.get(entity_id)
            previous_growth = finite_int(previous.get("signal", {}).get("stars_growth"), 0) if previous else None
            if previous is None or growth > previous_growth:
                deduped[entity_id] = record
        return sorted(
            deduped.values(),
            key=lambda record: (-finite_int(record["signal"].get("stars_growth"), 0), record["entity_id"]),
        )
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return []


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Fetch AI collection rankings, deduped and ordered by star growth."""
    del query, config
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}

        collection_payload = _request(ENDPOINT)
        if collection_payload is None:
            return {"records": [], "status": "error", "detail": "AI-topic collections request failed"}
        collections = parse_collections(collection_payload)
        if not collections:
            return {"records": [], "status": "empty", "detail": "no AI collections parsed"}

        records: List[Dict[str, Any]] = []
        reached = 0
        for collection_id, name in collections:
            payload = _request("{}{}/ranking_by_stars/".format(ENDPOINT, collection_id))
            if payload is None:
                continue
            reached += 1
            records.extend(parse_ranking(payload, name))
        if reached == 0:
            return {"records": [], "status": "error", "detail": "AI-topic rankings request failed"}

        records = dedupe_records(records)
        if not records:
            return {"records": [], "status": "empty", "detail": "no AI repositories parsed"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "collections fetch failed"}


def selftest() -> None:
    """Run fixture-only parser checks without making network requests."""
    collections = {"data": [{"id": 1, "name": "AI Agents"}, {"id": 2, "name": "Databases"}]}
    ranking = {"data": {"rows": [{"repo_name": "Example/Project", "total": "42",
                                     "current_period_growth": "7", "current_period_rank": "1"}]}}
    assert parse_collections(collections) == [(1, "AI Agents")]
    records = parse_ranking(ranking, "AI Agents")
    assert records[0]["entity_id"] == "example/project"
    assert records[0]["signal"]["stars_growth"] == 7
    assert dedupe_records(records + parse_ranking(
        {"rows": [{"repo_name": "example/project", "current_period_growth": 9}]}, "LLMs"
    ))[0]["signal"]["stars_growth"] == 9
    assert parse_ranking(None, "AI") == [] and parse_collections("bad") == []
    print("collections selftest: ok")


if __name__ == "__main__":
    selftest()
