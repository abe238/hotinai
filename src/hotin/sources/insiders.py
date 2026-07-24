"""Repositories the AI Insiders are engaging with (repository entity).

This surfaces the raw "smart-money" signal: the GitHub repositories that a
curated cohort of influential AI accounts (the "AI Insiders") have recently
starred.  The public page ships its data as React flight chunks, so we reuse
the sibling adapter's chunk decoders to rebuild a decoded blob and then pull
the embedded repository objects (full name and per-repo insider starrer list)
straight out of it.

Like the other adapters this is best-effort and never raises: malformed rows
are skipped and any transport or parse failure returns a result dictionary,
not an exception.  Everything here is driven by the public AI-Insider
engagement graph — no API key and no login required.
"""

from __future__ import annotations

import gzip
import json
import re
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from hotin.canonical import canonicalize
from hotin.coerce import finite_int
from hotin.sources import smartmoney
from hotin.throttle import Throttle

SOURCE = "insiders"
THROTTLE = Throttle(min_interval=3.0, jitter=1.5)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

_REPO_ANCHOR = '{"full_name":'
# ponytail: naive brace scan bounded to this span (same trade-off as the sibling
# person parser); raise it only if real repo objects ever exceed it.
_MAX_OBJECT_SPAN = 20000


def _request() -> Optional[str]:
    """Fetch the AI-Insider engagement page, returning None on any failure."""
    try:
        request = urllib.request.Request(
            "https://digg.com/tech/github/stars", headers={"User-Agent": USER_AGENT}
        )
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
        return body.decode("utf-8", "replace") if isinstance(body, bytes) else None
    except Exception:
        return None


def _decode_page(html: str) -> str:
    """Concatenate every decoded React flight chunk into one searchable blob."""
    parts: List[str] = []
    for match in smartmoney._RSC_CHUNK_RE.finditer(html):
        decoded = smartmoney._decode_rsc_chunk(match.group(1))
        if decoded:
            parts.append(decoded)
    return "".join(parts)


def _iter_repo_objects(blob: str):
    """Yield each balanced JSON object that begins with a ``full_name`` field."""
    index = 0
    while True:
        index = blob.find(_REPO_ANCHOR, index)
        if index < 0:
            return
        depth = 0
        end = index
        for pos in range(index, min(index + _MAX_OBJECT_SPAN, len(blob))):
            char = blob[pos]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    break
        chunk = blob[index:end]
        index = end if end > index else index + 1
        try:
            obj = json.loads(chunk)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("full_name"), str):
            yield obj


def _read_starrers(starrers: Any) -> Tuple[List[str], Optional[str]]:
    """Return up to twelve insider usernames in AI-1000 rank order (most
    influential first; unranked last) and the top-ranked one."""
    if not isinstance(starrers, list):
        return [], None
    seen: List[Tuple[int, str]] = []
    for starrer in starrers:
        if not isinstance(starrer, dict):
            continue
        username = starrer.get("username")
        if not isinstance(username, str) or not username.strip():
            continue
        rank = finite_int(starrer.get("rank"))
        seen.append((rank if rank is not None else 10**9, username.strip()))
    seen.sort(key=lambda pair: pair[0])
    usernames = [name for _, name in seen[:12]]
    return usernames, (usernames[0] if usernames else None)


def parse_repos(html: Any) -> List[Dict[str, Any]]:
    """Purely turn the engagement page into repo records; skip anything malformed.

    Deduplicates by canonical repository, keeping the highest observed insider
    star count, and returns records ordered by that count (descending).  Never
    raises: any structural surprise yields fewer rows, not an exception.
    """
    if not isinstance(html, str):
        return []
    deduped: Dict[str, Dict[str, Any]] = {}
    try:
        for obj in _iter_repo_objects(_decode_page(html)):
            canonical = canonicalize(obj.get("full_name"))
            if not canonical:
                continue
            insider_stars = finite_int(obj.get("distinct_starrers"), 0)
            usernames, top_insider = _read_starrers(obj.get("starrers"))
            previous = deduped.get(canonical)
            if previous is not None and finite_int(
                previous["signal"]["insider_stars"], 0
            ) >= insider_stars:
                continue
            deduped[canonical] = {
                "entity_type": "repo",
                "entity_id": canonical,
                "canonical_repo": canonical,
                "url": "https://github.com/{}".format(canonical),
                "name": canonical,
                "source": SOURCE,
                "signal": {"insider_stars": insider_stars},
                "meta": {"insiders": usernames, "top_insider": top_insider,
                         "description": obj.get("description")
                         if isinstance(obj.get("description"), str) else None},
            }
    except (AttributeError, TypeError, ValueError, OverflowError, re.error):
        return []
    return sorted(
        deduped.values(),
        key=lambda record: (-finite_int(record["signal"]["insider_stars"], 0), record["entity_id"]),
    )


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Return repositories the AI Insiders are engaging with (top ``limit``)."""
    del query, config  # This is a public ranked feed, not a queryable API.
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        html = _request()
        if html is None:
            return {"records": [], "status": "error", "detail": "insiders request failed"}
        records = parse_repos(html)
        if not records:
            return {"records": [], "status": "empty", "detail": "no insider-starred repositories parsed"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "insiders fetch failed"}


def selftest() -> None:
    """Parse a flight-shaped fixture; dedupe by repo; tolerate junk. No network."""
    def page(text):
        escaped = json.dumps(text)[1:-1]  # escape " and \ exactly as the real page does
        return '<script>self.__next_f.push([1, "{}"])</script>'.format(escaped)

    repos = json.dumps(
        [
            {"full_name": "Owner/Repo", "distinct_starrers": 3,
             "starrers": [{"username": "karpathy", "rank": 5}, {"username": "ilya", "rank": 1}]},
            {"full_name": "owner/repo", "distinct_starrers": 9,  # dup canonical, higher stars
             "description": "an agent harness",
             "starrers": [{"username": "greg", "rank": 4}, {"username": "sama", "rank": 2}]},
            {"full_name": "not a repo", "distinct_starrers": 1e309},  # invalid + overflow, skipped
        ],
        separators=(",", ":"),
    )
    records = parse_repos(page(repos))
    assert len(records) == 1, records
    top = records[0]
    assert top["entity_type"] == "repo" and top["entity_id"] == "owner/repo"
    assert top["signal"]["insider_stars"] == 9  # dedupe kept the higher count
    # starrers arrive page-ordered greg(4), sama(2); output is AI-1000 rank order
    assert top["meta"]["top_insider"] == "sama" and top["meta"]["insiders"] == ["sama", "greg"]
    assert top["meta"]["description"] == "an agent harness"
    assert parse_repos("garbage") == [] and parse_repos(None) == []
    print("insiders selftest: ok")


if __name__ == "__main__":
    selftest()
