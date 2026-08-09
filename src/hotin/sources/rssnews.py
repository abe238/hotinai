"""Curated AI news headlines from primary sources and named experts (news entity).

The news tab's editorial rule, in code: link to the artifact, not the retelling.
Tier 1 ("primary") is the labs' own RSS — when a model ships, the lab's post IS
the news. Tier 2 ("analysis") is individually accountable experts, not content
farms. Every feed here was probed live before inclusion (2026-07-24); labs with
no working feed (Anthropic, Meta, xAI, DeepSeek) are honestly absent and arrive
via the expert tier instead. HN points are healed onto cached rows by
``backfill_hn_points`` during refresh — the crowd receipt, like stars on repos.

Parsing is deliberately regex-over-text (same trade as the smolai adapter): one
malformed entry or broken feed never drops the sweep. Never raises.
"""

from __future__ import annotations

import gzip
import html
import json
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from hotin.coerce import finite_int
from hotin.throttle import Throttle

SOURCE = "rssnews"
# many distinct hosts share this throttle, so a short interval is still polite
THROTTLE = Throttle(min_interval=0.5, jitter=0.3)
HN_THROTTLE = Throttle(min_interval=0.5, jitter=0.3)
USER_AGENT = "hotin/0.2.0"
MAX_PER_FEED = 8

# (url, publisher, kind); kind is "primary" (a lab's own post) or "analysis"
# (a named expert). Probed live 2026-07-24; a dead feed gets removed, not kept
# on faith — and the strict site windows silently absorb any that go stale.
FEEDS = (
    ("https://openai.com/news/rss.xml", "OpenAI", "primary"),
    ("https://deepmind.google/blog/rss.xml", "Google DeepMind", "primary"),
    ("https://mistral.ai/rss.xml", "Mistral", "primary"),
    ("https://qwenlm.github.io/blog/index.xml", "Qwen", "primary"),
    ("https://huggingface.co/blog/feed.xml", "Hugging Face", "primary"),
    ("https://blog.google/technology/ai/rss/", "Google AI", "primary"),
    ("https://www.microsoft.com/en-us/research/feed/", "Microsoft Research", "primary"),
    ("https://simonwillison.net/atom/everything/", "Simon Willison", "analysis"),
    ("https://www.interconnects.ai/feed", "Interconnects", "analysis"),
    ("https://importai.substack.com/feed", "Import AI", "analysis"),
    ("https://semianalysis.com/feed/", "SemiAnalysis", "analysis"),
    ("https://www.latent.space/feed", "Latent Space", "analysis"),
    # Daily digest newsletter; full-content RSS, probed live 2026-08-09. Also
    # swept by sources/smolai.py for its repo-mention credibility flag.
    ("https://www.rohan-paul.com/feed", "Rohan's Bytes", "analysis"),
)

_ITEM_RE = re.compile(r"<(?:item|entry)\b[^>]*>(.*?)</(?:item|entry)>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_RSS_LINK_RE = re.compile(r"<link\b[^>]*>([^<]+)</link>", re.DOTALL | re.IGNORECASE)
_ATOM_LINK_RE = re.compile(r"<link\b([^>]*?)/?>", re.IGNORECASE)
_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)
_REL_RE = re.compile(r'rel="([^"]+)"', re.IGNORECASE)
_DATE_RE = re.compile(
    r"<(?:pubDate|published|updated)\b[^>]*>(.*?)</(?:pubDate|published|updated)>",
    re.DOTALL | re.IGNORECASE)


def _clean(text: str) -> str:
    inner = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
    return html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()


def _iso_date(raw: Any) -> Optional[str]:
    """Normalize an RFC-2822 or ISO-8601 date to '<UTC ISO>Z', else None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    import datetime
    import email.utils
    parsed = None
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        pass
    if parsed is None:
        try:
            parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    try:
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(datetime.timezone.utc)
        return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


def _item_link(block: str) -> Optional[str]:
    """The item's own page: RSS `<link>text</link>`, else the Atom alternate."""
    match = _RSS_LINK_RE.search(block)
    if match:
        link = _clean(match.group(1))
        if link.startswith("http"):
            return link
    fallback = None
    for attrs in _ATOM_LINK_RE.findall(block):
        href_match = _HREF_RE.search(attrs)
        if not href_match:
            continue
        href = html.unescape(href_match.group(1)).strip()
        if not href.startswith("http"):
            continue
        rel_match = _REL_RE.search(attrs)
        rel = rel_match.group(1).lower() if rel_match else ""
        if rel in ("", "alternate"):
            return href
        fallback = fallback or href
    return fallback


def parse_feed(feed_text: Any, publisher: str, kind: str) -> List[Dict[str, Any]]:
    """Purely turn one RSS/Atom feed into news records; skip anything malformed."""
    if not isinstance(feed_text, str):
        return []
    records: List[Dict[str, Any]] = []
    try:
        for block in _ITEM_RE.findall(feed_text):
            title_match = _TITLE_RE.search(block)
            if not title_match:
                continue
            title = _clean(title_match.group(1))
            link = _item_link(block)
            if not title or not link:
                continue
            date_match = _DATE_RE.search(block)
            records.append({
                "entity_type": "news",
                "entity_id": link,
                "url": link,
                "name": title,
                "source": SOURCE,
                "signal": {},
                "meta": {"date": _iso_date(date_match.group(1)) if date_match else None,
                         "publisher": publisher, "kind": kind},
            })
            if len(records) >= MAX_PER_FEED:
                break
    except (AttributeError, TypeError, ValueError, re.error):
        return records
    return records


def _request_feed(url: str) -> Optional[str]:
    """Fetch one feed's text, returning None for any transport/decode failure."""
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
        return body.decode("utf-8", "replace") if isinstance(body, bytes) else None
    except Exception:
        return None


def _epoch(date_text: Any) -> float:
    """Sortable epoch seconds for a normalized ISO date; undated sinks to 0."""
    if not isinstance(date_text, str):
        return 0.0
    import calendar
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", date_text)
    if not match:
        return 0.0
    try:
        return float(calendar.timegm(tuple(int(g) for g in match.groups()) + (0, 0, 0)))
    except (ValueError, OverflowError):
        return 0.0


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Sweep every curated feed; newest first. detail carries the provenance."""
    del query, config  # curated feed roster, not a queryable API
    try:
        requested = finite_int(limit)
        requested = 50 if requested is None else max(0, requested)
        if requested == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        records: List[Dict[str, Any]] = []
        alive = 0
        for url, publisher, kind in FEEDS:
            text = _request_feed(url)
            if text is None:
                continue
            parsed = parse_feed(text, publisher, kind)
            if parsed:
                alive += 1
                records.extend(parsed)
        records.sort(key=lambda r: (-_epoch((r.get("meta") or {}).get("date")),
                                    (r.get("meta") or {}).get("kind") != "primary",
                                    r.get("entity_id") or ""))
        detail = "{}/{} feeds".format(alive, len(FEEDS))
        if not records:
            return {"records": [], "status": "empty" if alive else "error", "detail": detail}
        return {"records": records[:requested], "status": "ok", "detail": detail}
    except Exception:
        return {"records": [], "status": "error", "detail": "rssnews fetch failed"}


def _url_key(url: Any) -> str:
    """Loose URL identity for HN matching: scheme/www/trailing-slash agnostic."""
    if not isinstance(url, str):
        return ""
    return re.sub(r"^https?://(www\.)?", "", url.strip().lower()).rstrip("/")


def fetch_hn_points(url: Any, *, timeout: float = 15.0) -> Optional[int]:
    """HN points for a story URL via Algolia; 0 = checked-not-found, None = failure."""
    key = _url_key(url)
    if not key:
        return None
    try:
        endpoint = ("https://hn.algolia.com/api/v1/search?query={}"
                    "&restrictSearchableAttributes=url&tags=story&hitsPerPage=5").format(
                        urllib.parse.quote(url.strip(), safe=""))
        request = urllib.request.Request(endpoint, headers={"User-Agent": USER_AGENT})
        HN_THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        best = 0
        for hit in payload.get("hits", []) if isinstance(payload, dict) else []:
            if not isinstance(hit, dict):
                continue
            if _url_key(hit.get("url")) == key:
                best = max(best, finite_int(hit.get("points"), 0) or 0)
        return best
    except Exception:
        return None


def backfill_hn_points(cache: Any, *, max_calls: int = 25) -> int:
    """Heal cached news rows with the crowd receipt (HN points), newest first.

    Presence of the ``hn_points`` key marks a row as checked (0 = HN never saw
    it); ``hn_checked_at`` stamps when, so ``recheck_hn_points`` can re-score
    stories still climbing days later. Transport failures leave the key absent
    and retry next run. Bounded; never raises; returns rows healed."""
    healed = 0
    try:
        pending = []
        for raw in cache.get_all():
            if not isinstance(raw, dict) or raw.get("entity_type") != "news":
                continue
            if raw.get("source") != SOURCE:
                continue
            payload = raw.get("signal_json")
            try:
                payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            signal = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}
            if "hn_points" in signal:
                continue
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            pending.append((_epoch(meta.get("date")), raw, payload, signal))
        pending.sort(key=lambda item: -item[0])
        for _, raw, payload, signal in pending[:max_calls]:
            points = fetch_hn_points(raw.get("entity_id"))
            if points is None:
                continue
            signal["hn_points"] = points
            signal["hn_checked_at"] = time.time()
            payload["signal"] = signal
            updated = dict(raw)
            updated["signal_json"] = payload
            updated["fetched_at"] = raw.get("fetched_at")  # heal, keep age
            cache.upsert(updated)
            healed += 1
    except Exception:
        return healed
    return healed


RECHECK_MIN_AGE_D = 2.0     # a story must survive its news cycle first
RECHECK_MAX_AGE_D = 14.0    # after two weeks the verdict is in
RECHECK_COOLDOWN_H = 20.0   # at most one re-score per story per day
# ponytail: +10 pts filters random drift on old stories; tune if it misses
# slow burners or badges noise.
RISING_MIN_DELTA = 10


def recheck_hn_points(cache: Any, *, max_calls: int = 15, now: Optional[float] = None) -> int:
    """Re-score checked stories 2-14 days old: the crowd receipt, over time.

    A story whose points are still climbing days after it shipped gets
    ``hn_rising`` (the news tab's "rising" badge) and ``hn_points_delta``
    (the visible climb since last check); one that flatlines loses the badge.
    Rows checked before the stamp existed count as stale. Bounded; never
    raises; returns rows re-scored."""
    healed = 0
    clock = time.time() if now is None else now
    try:
        due = []
        for raw in cache.get_all():
            if not isinstance(raw, dict) or raw.get("entity_type") != "news":
                continue
            if raw.get("source") != SOURCE:
                continue
            payload = raw.get("signal_json")
            try:
                payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            signal = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}
            if "hn_points" not in signal:
                continue  # first check pending; backfill owns it
            published = _epoch((payload.get("meta") or {}).get("date"))
            if not published:
                continue
            age_days = (clock - published) / 86400.0
            if not (RECHECK_MIN_AGE_D <= age_days <= RECHECK_MAX_AGE_D):
                continue
            checked_at = signal.get("hn_checked_at")
            if isinstance(checked_at, (int, float)) and (clock - checked_at) < RECHECK_COOLDOWN_H * 3600.0:
                continue
            due.append((-_epoch((payload.get("meta") or {}).get("date")), raw, payload, signal))
        due.sort(key=lambda item: item[0])
        for _, raw, payload, signal in due[:max_calls]:
            points = fetch_hn_points(raw.get("entity_id"))
            if points is None:
                continue
            previous = finite_int(signal.get("hn_points"), 0) or 0
            delta = max(0, points - previous)
            signal["hn_points"] = max(points, previous)
            signal["hn_points_delta"] = delta
            signal["hn_rising"] = delta >= RISING_MIN_DELTA
            signal["hn_checked_at"] = clock
            payload["signal"] = signal
            updated = dict(raw)
            updated["signal_json"] = payload
            updated["fetched_at"] = raw.get("fetched_at")  # heal, keep age
            cache.upsert(updated)
            healed += 1
    except Exception:
        return healed
    return healed


# words too generic to anchor a story match across publishers
_STORY_STOPWORDS = frozenset(
    "introducing announcing launching launch release released releases update updates "
    "official model models open source with from this that what your into using "
    "https quoting notes weekly daily ainews".split())
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.-]{3,}")


def _anchor_tokens(title: Any) -> frozenset:
    """The distinctive words of a headline (>=4 chars, minus news boilerplate)."""
    if not isinstance(title, str):
        return frozenset()
    return frozenset(t for t in _TOKEN_RE.findall(title.lower()) if t not in _STORY_STOPWORDS)


def cluster_stories(records: Any, *, max_gap_days: float = 4.0) -> None:
    """Mark stories independently covered by 2+ publishers (in place).

    Conservative on purpose: two items match only when they come from
    DIFFERENT publishers, sit within ``max_gap_days`` of each other, and share
    at least two anchor tokens covering half the smaller title. The honest
    failure mode is a missed cluster, never an invented one. Sets
    ``meta.sources_count`` on every member of a matched cluster. Never raises.
    """
    try:
        items = []
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
            anchors = _anchor_tokens(record.get("name"))
            if anchors:
                items.append((record, meta.get("publisher"), _epoch(meta.get("date")), anchors))
        parent = list(range(len(items)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                _, pub_i, when_i, anchors_i = items[i]
                _, pub_j, when_j, anchors_j = items[j]
                if pub_i == pub_j:
                    continue
                if when_i and when_j and abs(when_i - when_j) > max_gap_days * 86400.0:
                    continue
                shared = anchors_i & anchors_j
                if len(shared) >= 2 and len(shared) * 2 >= min(len(anchors_i), len(anchors_j)):
                    parent[find(i)] = find(j)
        groups: Dict[int, List[int]] = {}
        for i in range(len(items)):
            groups.setdefault(find(i), []).append(i)
        for members in groups.values():
            publishers = {items[i][1] for i in members}
            if len(publishers) < 2:
                continue
            for i in members:
                record = items[i][0]
                record.setdefault("meta", {})["sources_count"] = len(publishers)
    except Exception:
        return


def selftest() -> None:
    """Parse RSS + Atom shapes, normalize dates, tolerate junk. No network."""
    rss = (
        '<rss><channel><item><title><![CDATA[GPT-6 ships]]></title>'
        '<link>https://openai.com/news/gpt-6</link>'
        '<pubDate>Wed, 22 Jul 2026 13:00:00 GMT</pubDate></item>'
        '<item><title>no link, skipped</title></item></channel></rss>'
    )
    records = parse_feed(rss, "OpenAI", "primary")
    assert len(records) == 1, records
    top = records[0]
    assert top["name"] == "GPT-6 ships" and top["entity_type"] == "news"
    assert top["meta"]["date"] == "2026-07-22T13:00:00Z"
    assert top["meta"]["publisher"] == "OpenAI" and top["meta"]["kind"] == "primary"

    atom = (
        '<feed><entry><title>Kimi K3 notes</title>'
        '<link rel="self" href="https://example.com/feed"/>'
        '<link rel="alternate" href="https://simonwillison.net/2026/Jul/23/kimi/"/>'
        '<published>2026-07-23T05:00:00+00:00</published></entry></feed>'
    )
    entry = parse_feed(atom, "Simon Willison", "analysis")[0]
    assert entry["url"] == "https://simonwillison.net/2026/Jul/23/kimi/"
    assert entry["meta"]["date"] == "2026-07-23T05:00:00Z"
    assert parse_feed("garbage", "X", "primary") == [] and parse_feed(None, "X", "primary") == []
    assert _iso_date("junk") is None and _iso_date(None) is None
    assert _epoch("2026-07-22T13:00:00Z") > 0 and _epoch(None) == 0.0
    assert _url_key("https://www.Example.com/a/") == "example.com/a"
    print("rssnews selftest: ok")


if __name__ == "__main__":
    selftest()
