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
# Labs with no feed at all, polled through their sitemap instead. This is the HTML-scrape
# fallback the UNSUPPORTED note below has always called for, built for the first lab that
# actually needed it: typesafe.ai serves no RSS or Atom, and even /blog 404s, so its posts are
# reachable ONLY via sitemap.xml. Each entry is (lab, sitemap url, path marker).
#
# Cost is 1 request for the sitemap plus one per post, against ~1 for a feed lab, so the post
# count is bounded. Do not add a lab here that publishes a real feed.
SITEMAP_LABS = [
    ("TypeSafe AI", "https://typesafe.ai/sitemap.xml", "/blog/"),
]
# Bound on posts fetched per sitemap lab per run. typesafe.ai has 5, so today every post is
# read and ordering does not matter; past this bound we take the sitemap's own order, which is
# newest-first there but is not a guarantee the format makes.
MAX_SITEMAP_POSTS = 8

# Named labs with no public feed AND no sitemap adapter yet. Kept visible so `hotin` can
# report honestly which labs it does and does not yet cover.
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


_LOC_RE = re.compile(r"<loc>([^<]+)</loc>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
# The post date as rendered ELEMENT TEXT: ">Sep 10, 2026<". Deliberately not "any date in the
# page": Framer stamps its own site-publish date into an HTML comment at the top of every page
# ("<!-- Published Sep 18, 2026, 11:44 PM UTC -->"), identical across every post and equal to
# the last time the SITE was deployed. Reading that would date every post to today and march
# the whole lab to the top of the board every time they touch any page. Comments are stripped
# before this runs, and the element-text anchor is the second line of defence.
_TEXT_DATE_RE = re.compile(r">\s*((?:%s)[a-z]*\s+\d{1,2},?\s+20\d\d)\s*<" % _MONTHS)
# " - TypeSafe AI Blog" / " | TypeSafe AI": strip the site suffix off the <title>.
_TITLE_SUFFIX_RE = re.compile(r"\s*[-|\u2013\u2014]\s*[^-|\u2013\u2014]*$")


def _month_epoch(date_str: str) -> float:
    """"Sep 10, 2026" -> epoch seconds (UTC midnight). 0.0 if unparseable."""
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc).timestamp()
        except (TypeError, ValueError):
            continue
    return 0.0


def parse_post(page: Any, url: str, lab: str) -> Optional[Dict[str, Any]]:
    """One feedless blog post -> a release record, or None if it cannot be dated.

    An undated post is DROPPED rather than given a fallback date: the board's freshness gate
    reads this date, and inventing one would present an old post as today's news.
    """
    if not isinstance(page, str):
        return None
    body = _COMMENT_RE.sub(" ", page)
    title_match = _TITLE_RE.search(body)
    if not title_match:
        return None
    title = _TITLE_SUFFIX_RE.sub("", _clean(title_match.group(1))).strip()
    if not title:
        return None
    date_match = _TEXT_DATE_RE.search(body)
    if not date_match:
        return None
    date_raw = date_match.group(1)
    released_at = _month_epoch(date_raw)
    if not released_at:
        return None
    return {
        "entity_type": "release",
        "entity_id": url,
        "url": url,
        "name": title,
        "source": SOURCE,
        "signal": {"released_at": released_at},
        "meta": {"official": True, "lab": lab, "date": date_raw},
    }


def parse_sitemap(sitemap_text: Any, marker: str) -> List[str]:
    """Post URLs from a sitemap, in document order, deduped."""
    if not isinstance(sitemap_text, str):
        return []
    seen, out = set(), []
    for loc in _LOC_RE.findall(sitemap_text):
        url = html.unescape(loc).strip()
        if marker in url and url.startswith("http") and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def fetch_sitemap_lab(lab: str, sitemap_url: str, marker: str) -> List[Dict[str, Any]]:
    """Every dated post for one feedless lab. Never raises."""
    sitemap = _request(sitemap_url)
    if sitemap is None:
        return []
    records = []
    for url in parse_sitemap(sitemap, marker)[:MAX_SITEMAP_POSTS]:
        page = _request(url)
        if page is None:
            continue
        record = parse_post(page, url, lab)
        if record is not None:
            records.append(record)
    return records


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
        for lab, sitemap_url, marker in SITEMAP_LABS:
            from_lab = fetch_sitemap_lab(lab, sitemap_url, marker)
            if from_lab:
                reached += 1
            records.extend(from_lab)
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
