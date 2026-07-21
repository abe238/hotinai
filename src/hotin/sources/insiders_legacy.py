"""The the influencer-stars source AI 1000 — the ranked roster of accounts shaping AI (people entity).

the influencer-stars source publishes a public ranking of ~1000 X accounts, built from the tech-community
follow graph, at https://digg.com/tech/x/rankings. The page is a Next.js app whose
data ships as React flight chunks; we decode those chunks and pull the embedded
person objects (rank, handle, category, follower/gravity signals, bio). No key, no
login. Like the other adapters this is best-effort and never raises.

We deliberately parse the flight payload rather than depend on any external CLI, so
hotin stays stdlib-only with zero runtime dependencies.
"""

from __future__ import annotations

import gzip
import json
import re
import urllib.request
from typing import Any, Dict, List, Optional

from hotin.coerce import finite_int
from hotin.throttle import Throttle

SOURCE = "insider_people"
ENDPOINT = "https://digg.com/tech/x/rankings"
THROTTLE = Throttle(min_interval=3.0, jitter=1.5)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

_FLIGHT_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def _request() -> Optional[str]:
    """Fetch the rankings page text, returning None for any transport/decode failure."""
    try:
        request = urllib.request.Request(ENDPOINT, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
        return body.decode("utf-8", "replace") if isinstance(body, bytes) else None
    except Exception:
        return None


def _decode_flight(html: str) -> str:
    """Concatenate the decoded React flight chunks embedded in the page."""
    parts: List[str] = []
    for match in _FLIGHT_RE.finditer(html):
        try:
            parts.append(json.loads(match.group(1)))
        except (ValueError, TypeError):
            continue
    return "".join(parts)


def _iter_person_objects(blob: str):
    """Yield each JSON person object (those beginning with a ``rank`` field)."""
    index = 0
    while True:
        index = blob.find('{"rank":', index)
        if index < 0:
            return
        depth = 0
        end = index
        for pos in range(index, min(index + 3000, len(blob))):
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
        if isinstance(obj, dict) and isinstance(obj.get("rank"), int) and isinstance(obj.get("username"), str):
            yield obj


def parse_rankings(html: Any) -> List[Dict[str, Any]]:
    """Purely turn the rankings page HTML into person records, ignoring bad entries.

    Deduplicates by rank (the flight payload lists each person twice) and returns
    them ordered by rank. Never raises: any structural surprise yields fewer rows,
    not an exception.
    """
    if not isinstance(html, str):
        return []
    seen: Dict[int, Dict[str, Any]] = {}
    try:
        blob = _decode_flight(html)
        for obj in _iter_person_objects(blob):
            rank = obj["rank"]
            if rank in seen or not (1 <= rank <= 100000):
                continue
            handle = obj["username"].strip()
            if not handle:
                continue
            bio = obj.get("bio")
            seen[rank] = {
                "entity_type": "person",
                "entity_id": handle,
                "rank": rank,
                "handle": handle,
                "name": obj.get("display_name") if isinstance(obj.get("display_name"), str) else handle,
                "category": obj.get("category") if isinstance(obj.get("category"), str) else "",
                "url": "https://x.com/{}".format(handle),
                "github": obj.get("githubUrl") if isinstance(obj.get("githubUrl"), str) else "",
                "source": SOURCE,
                "signal": {
                    "ai1000_followers": finite_int(obj.get("followed_by_count"), 0),
                    "score": finite_int(obj.get("score"), 0),
                    "x_followers": finite_int(obj.get("followers_count"), 0),
                    "rank_change": finite_int(obj.get("rankChange"), 0),
                },
                "meta": {
                    "previous_rank": finite_int(obj.get("previousRank")),
                    "category_rank": finite_int(obj.get("categoryRank")),
                    "bio": re.sub(r"\s+", " ", bio).strip() if isinstance(bio, str) else "",
                },
            }
    except (AttributeError, TypeError, ValueError, re.error):
        return []
    return [seen[rank] for rank in sorted(seen)]


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Fetch the the influencer-stars source AI 1000 ranked roster (top ``limit``, by rank). No key required."""
    del query, config
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        THROTTLE.wait()
        html = _request()
        if html is None:
            return {"records": [], "status": "error", "detail": "insider rankings request failed"}
        records = parse_rankings(html)
        if not records:
            return {"records": [], "status": "empty", "detail": "no rankings parsed"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "insider_people fetch failed"}


def selftest() -> None:
    """Parse a minimal flight-shaped fixture; dedupe by rank; tolerate junk."""
    def chunk(text):
        return 'self.__next_f.push([1,{}])'.format(json.dumps(text))

    person = ('[{"rank":1,"followed_by_count":759,"score":759,"username":"karpathy",'
              '"display_name":"Andrej Karpathy","followers_count":3418679,'
              '"bio":"I like  training nets.","category":"Research Engineer",'
              '"githubUrl":"https://github.com/karpathy","previousRank":1,"rankChange":0,"categoryRank":1}]')
    html = "<html>" + chunk(person) + chunk(person) + "</html>"  # duplicated, as the real page does
    recs = parse_rankings(html)
    assert len(recs) == 1, recs
    r = recs[0]
    assert r["rank"] == 1 and r["handle"] == "karpathy" and r["entity_type"] == "person"
    assert r["name"] == "Andrej Karpathy" and r["category"] == "Research Engineer"
    assert r["signal"]["ai1000_followers"] == 759 and r["signal"]["x_followers"] == 3418679
    assert r["github"] == "https://github.com/karpathy"
    assert r["meta"]["bio"] == "I like training nets."  # whitespace collapsed
    assert parse_rankings("garbage") == [] and parse_rankings(None) == []
    print("insider_people selftest: ok")


if __name__ == "__main__":
    selftest()
