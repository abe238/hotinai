"""AI-Insider GitHub-star signal adapter.

The source page is an unofficial React Server Components feed rather than a public
API.  The extraction is deliberately shape-based: it searches every RSC chunk
for the repository rows instead of relying on a release-specific JSON path.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hotin.canonical import canonicalize
from hotin.coerce import finite_int
from hotin.throttle import Throttle


SOURCE = "smartmoney"
ENDPOINT = "https://digg.com/ai/github/stars"
THROTTLE = Throttle(min_interval=3.0, jitter=1.5)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
_RSC_CHUNK_RE = re.compile(
    r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)\s*</script>', re.DOTALL
)
_RSC_SEGMENT_RE = re.compile(r"^[0-9a-f]+:(.*)")
LOGGER = logging.getLogger(__name__)


def _decode_rsc_chunk(chunk: Any) -> Optional[str]:
    if not isinstance(chunk, str):
        return None
    try:
        return chunk.encode().decode("unicode_escape").encode("latin1").decode(
            "utf-8", errors="replace"
        )
    except (UnicodeError, AttributeError, TypeError, ValueError):
        return None


def _find_rows(obj: Any) -> Optional[List[Any]]:
    """Recursively find a rows list whose entries have repository payloads."""
    try:
        if isinstance(obj, dict):
            candidate = obj.get("rows")
            if isinstance(candidate, list):
                repo_shaped = sum(isinstance(row, dict) and "repo" in row for row in candidate)
                if not candidate or (repo_shaped and repo_shaped * 2 > len(candidate)):
                    return candidate
            for value in obj.values():
                found = _find_rows(value)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = _find_rows(value)
                if found is not None:
                    return found
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        return None
    return None


def extract_rows_from_html(html: Any) -> Optional[List[Any]]:
    """Extract the first structurally-valid rows list from all RSC script chunks.

    ``None`` specifically means the page no longer exposes its expected RSC
    shape, allowing the caller to distinguish schema drift from an empty feed.
    """
    if not isinstance(html, str):
        return None
    try:
        for match in _RSC_CHUNK_RE.finditer(html):
            decoded = _decode_rsc_chunk(match.group(1))
            if decoded is None:
                continue
            for line in decoded.splitlines():
                segment = _RSC_SEGMENT_RE.match(line)
                if segment is None:
                    continue
                try:
                    parsed = json.loads(segment.group(1))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                rows = _find_rows(parsed)
                if rows is not None:
                    return rows
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError, re.error):
        return None
    return None


def _freshness(value: Any, now: Optional[datetime] = None) -> str:
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        return "stale" if parsed < reference - timedelta(days=30) else "fresh"
    except (TypeError, ValueError, OverflowError):
        return "unknown"


def parse_rows(rows: Any, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Purely turn source rows into hotin Records; malformed rows are skipped."""
    if not isinstance(rows, list):
        return []
    records: List[Dict[str, Any]] = []
    try:
        for row in rows:
            if not isinstance(row, dict):
                continue
            repo = row.get("repo")
            if not isinstance(repo, dict):
                continue
            full_name = repo.get("full_name")
            if not isinstance(full_name, str):
                continue
            canonical_repo = canonicalize(full_name)
            if not canonical_repo:
                continue

            timestamp = repo.get("most_recent_star_at")
            raw_timestamp = timestamp if isinstance(timestamp, str) else None
            starrers = repo.get("starrers")
            top_starrers: List[Dict[str, Any]] = []
            if isinstance(starrers, list):
                for starrer in starrers:
                    if not isinstance(starrer, dict):
                        continue
                    username = starrer.get("username")
                    if not isinstance(username, str) or not username.strip():
                        continue
                    top_starrers.append(
                        {"username": username, "rank": finite_int(starrer.get("rank"), -1)}
                    )
                    if len(top_starrers) == 5:
                        break

            description = repo.get("description")
            language = repo.get("language")
            records.append(
                {
                    "url": "https://github.com/{}".format(canonical_repo),
                    "canonical_repo": canonical_repo,
                    "name": canonical_repo,
                    "source": SOURCE,
                    "signal": {
                        "smartmoney_starrers": finite_int(repo.get("distinct_starrers"), 0),
                        "smartmoney_ai1000": finite_int(repo.get("ai1000_stars"), 0),
                        "smartmoney_freshness": _freshness(raw_timestamp, now),
                        "smartmoney_most_recent_star_at": raw_timestamp,
                    },
                    "meta": {
                        "description": description if isinstance(description, str) else None,
                        "language": language if isinstance(language, str) else None,
                        "top_starrers": top_starrers,
                    },
                }
            )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
    return records


def _normalise_limit(limit: Any) -> int:
    return max(0, finite_int(limit, 50))


def _request_html() -> Optional[str]:
    """Fetch the page once, returning None for all transport/decoding failures."""
    try:
        request = urllib.request.Request(ENDPOINT, headers={"User-Agent": USER_AGENT})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            LOGGER.debug("insider-signal final URL: %s", response.geturl())
        if not isinstance(body, bytes):
            return None
        return body.decode("utf-8")
    except Exception:
        return None


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Return repositories recently starred by the AI Insiders."""
    del query, config  # This is a public ranked feed, not a queryable API.
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        html = _request_html()
        if html is None:
            return {"records": [], "status": "error", "detail": "insider-signal request failed"}
        rows = extract_rows_from_html(html)
        if rows is None:
            return {
                "records": [],
                "status": "error",
                "detail": "source page structure changed — no rows found in any RSC chunk",
            }
        records = parse_rows(rows)
        if not records:
            return {"records": [], "status": "empty", "detail": "no usable GitHub repositories found"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "smartmoney fetch failed"}


def selftest() -> None:
    """Exercise real captured rows and malformed RSC/parser input without network I/O."""
    fixture = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "insider_rows_sample.json"
    rows = json.loads(fixture.read_text(encoding="utf-8"))
    records = parse_rows(rows, now=datetime(2026, 7, 20, tzinfo=timezone.utc))
    assert len(records) == 2
    assert records[0]["canonical_repo"] == "testowner/test-repo"
    assert records[0]["signal"]["smartmoney_freshness"] == "fresh"

    payload = {"rows": [{"repo": {"full_name": "Example/Project"}}]}
    segment = "1:" + json.dumps(payload)
    escaped = json.dumps(segment)[1:-1]
    assert extract_rows_from_html('<script>self.__next_f.push([1, "{}"])</script>'.format(escaped))

    hostile = [
        {"repo": {"full_name": "not a repo", "ai1000_stars": 1e309}},
        {"repo": {"full_name": "good/repo", "ai1000_stars": 1e309, "starrers": ["bad"]}},
    ]
    assert parse_rows(hostile)[0]["signal"]["smartmoney_ai1000"] == 0
    assert extract_rows_from_html('<script>self.__next_f.push([1, "1:not json"])</script>') is None
    print("smartmoney selftest: ok")


if __name__ == "__main__":
    selftest()
