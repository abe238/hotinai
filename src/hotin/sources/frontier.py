"""Official release announcements from frontier AI lab blogs (RSS/Atom).

Zero-key. Each lab is a curated ``(name, feed_url)``. Feeds are parsed
tolerantly by scanning ``<item>``/``<entry>`` blocks with regex (robust to
malformed XML, like the smolai adapter), handling both RSS (``<link>text</link>``)
and Atom (``<link href="..."/>``). Emits ``entity_type="release"`` records
flagged ``meta.official=True`` so the models view can show official releases
ABOVE HuggingFace trending. Never raises.

Labs without a public feed are listed in ``UNSUPPORTED`` for transparency rather
than silently dropped — an HTML-scrape fallback for them is a documented TODO.
"""

from __future__ import annotations

import email.utils
import gzip
import html
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from hotin.coerce import finite_int
from hotin.throttle import Throttle


SOURCE = "frontier"
THROTTLE = Throttle(min_interval=1.0, jitter=0.5)
USER_AGENT = "hotin/0.2.0"

# Labs with a clean public RSS/Atom feed (verified live). One request each.
FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Mistral AI", "https://mistral.ai/rss.xml"),
    ("Alibaba Qwen", "https://qwenlm.github.io/blog/index.xml"),
    ("Thinking Machines Lab", "https://thinkingmachines.ai/index.xml"),
]
# Named labs with no public feed (HTML-scrape fallback is a TODO). Kept visible
# so `hotin` can report honestly which labs it does and does not yet cover.
UNSUPPORTED = ["Anthropic", "xAI", "Meta AI", "Moonshot AI", "DeepSeek", "Z.ai", "MiniMax"]

_ITEM_RE = re.compile(r"<(?:item|entry)\b[^>]*>(.*?)</(?:item|entry)>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
# RSS: <link>url</link>.  Atom: <link href="url" .../>.
_LINK_TEXT_RE = re.compile(r"<link\b[^>]*>(.*?)</link>", re.DOTALL | re.IGNORECASE)
_LINK_HREF_RE = re.compile(r"<link\b[^>]*?href=[\"']([^\"']+)[\"']", re.IGNORECASE)
_DATE_RE = re.compile(r"<(?:pubDate|published|updated)\b[^>]*>(.*?)</(?:pubDate|published|updated)>",
                      re.DOTALL | re.IGNORECASE)


def _clean(text: str) -> str:
    inner = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
    return html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()


def _epoch(date_str: str) -> float:
    """Best-effort parse of an RSS (RFC822) or Atom (ISO8601) date to epoch seconds."""
    if not date_str:
        return 0.0
    try:  # RFC822, e.g. "Fri, 18 Jul 2026 00:00:00 GMT"
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt is not None:
            return dt.timestamp()
    except (TypeError, ValueError, OverflowError):
        pass
    try:  # ISO8601, e.g. "2026-07-18T00:00:00Z"
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def parse_feed(feed_text: Any, lab: str) -> List[Dict[str, Any]]:
    """Turn one lab's feed text into release records. Tolerant of malformed XML."""
    if not isinstance(feed_text, str):
        return []
    records: List[Dict[str, Any]] = []
    try:
        for block in _ITEM_RE.findall(feed_text):
            title_match = _TITLE_RE.search(block)
            href_match = _LINK_HREF_RE.search(block)  # Atom form wins if present
            text_match = _LINK_TEXT_RE.search(block)
            link = href_match.group(1).strip() if href_match else (_clean(text_match.group(1)) if text_match else "")
            if not title_match or not link.startswith("http"):
                continue
            title = _clean(title_match.group(1))
            if not title:
                continue
            date_match = _DATE_RE.search(block)
            date_raw = _clean(date_match.group(1)) if date_match else ""
            records.append({
                "entity_type": "release",
                "entity_id": link,
                "url": link,
                "name": title,
                "source": SOURCE,
                "signal": {"released_at": _epoch(date_raw)},
                "meta": {"official": True, "lab": lab, "date": date_raw},
            })
    except (AttributeError, TypeError, ValueError, re.error):
        return []
    return records


def _request(url: str) -> Optional[str]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
        return body.decode("utf-8", "replace") if isinstance(body, bytes) else None
    except Exception:
        return None


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Fetch recent official releases across the frontier-lab feeds, newest first."""
    del query, config
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        records: List[Dict[str, Any]] = []
        reached = 0
        for lab, url in FEEDS:
            text = _request(url)
            if text is None:
                continue
            reached += 1
            records.extend(parse_feed(text, lab))
        if not records:
            detail = "no frontier feeds reachable" if reached == 0 else "no releases parsed"
            return {"records": [], "status": "error" if reached == 0 else "empty", "detail": detail}
        records.sort(key=lambda record: -record["signal"].get("released_at", 0.0))
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "frontier fetch failed"}


def selftest() -> None:
    """Parse RSS + Atom shapes, sort newest-first, survive a malformed entry."""
    rss = (
        '<rss><channel>'
        '<item><title>GPT-6 is here</title><link>https://openai.com/news/gpt-6</link>'
        '<pubDate>Fri, 18 Jul 2026 00:00:00 GMT</pubDate></item>'
        '<item><title>Older post</title><link>https://openai.com/news/older</link>'
        '<pubDate>Mon, 01 Jun 2026 00:00:00 GMT</pubDate></item>'
        '<item><title>no link</title></item>'
        '</channel></rss>'
    )
    recs = parse_feed(rss, "OpenAI")
    assert [r["name"] for r in recs] == ["GPT-6 is here", "Older post"]
    assert recs[0]["entity_type"] == "release" and recs[0]["meta"]["lab"] == "OpenAI"
    assert recs[0]["meta"]["official"] is True

    atom = ('<feed><entry><title>Gemini 4</title>'
            '<link href="https://deepmind.google/blog/gemini-4"/>'
            '<updated>2026-07-19T12:00:00Z</updated></entry></feed>')
    arecs = parse_feed(atom, "Google DeepMind")
    assert arecs[0]["url"] == "https://deepmind.google/blog/gemini-4"
    assert arecs[0]["signal"]["released_at"] > 0

    # newest-first ordering across the two RSS items holds
    assert _epoch("Fri, 18 Jul 2026 00:00:00 GMT") > _epoch("Mon, 01 Jun 2026 00:00:00 GMT")
    assert parse_feed("garbage", "X") == []
    print("frontier selftest: ok")


if __name__ == "__main__":
    selftest()
