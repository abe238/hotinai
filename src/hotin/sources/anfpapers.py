"""AI Native Foundation's daily paper digest (RSS), as a paper source.

WHY THIS EXISTS. hfpapers reads HuggingFace *Daily* Papers -- a narrow
same-day window, so a paper only reaches us if we happened to poll on its day.
The AI Native Foundation publishes a curated daily digest that references the
same HuggingFace paper pages but reaches further back. Measured 2026-08-29:
of the 38 paper ids in their feed, 24 (63%) had never been seen by hotin --
not on the board, not in the tag ledger. That is the whole case for the source.

NOT VIA X. The account most people know this from is @AINativeF on X, and X
has no usable public API (see sources/x.py). The same content is published on
an ordinary WordPress RSS feed, so this adapter is plain HTTP with no
credentials and no scraping-fragility tax.

  NOTE the trailing slash: ainativefoundation.org/feed returns a 200 "page not
  found" HTML page (WordPress does this), which will parse to zero items and
  look like an empty feed rather than an error. The canonical URL is
  .../feed/ and there is a fixture pinning exactly this.

PROVENANCE, NOT AUTHORITY. Records carry meta["curated_by"] = "ai-native-
foundation" plus digest_date / digest_rank / digest_url so the curation is
visible and auditable. The feed itself carries no paper ids (measured
2026-09-04: ten digest/insights posts, zero huggingface links), so fetch
follows the newest "AI Native Daily Paper Digest" post pages and reads the
numbered headings there. Feed and page text are UNTRUSTED third-party input:
the id is a strict `\\d{4}.\\d{4,5}` match, the title is resolved from the
HuggingFace API and the digest heading is only a FALLBACK name when HF is
unreachable (clipped, tags stripped, escaped by every renderer downstream).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from hotin.coerce import finite_int
from hotin.throttle import Throttle

SOURCE = "anfpapers"
FEED = "https://ainativefoundation.org/feed/"
USER_AGENT = "hotin/0.2.0"
THROTTLE = Throttle(min_interval=2.0, jitter=1.0)
# Only ids that look like arXiv ids are accepted out of the untrusted feed.
_PAPER_ID = re.compile(r"huggingface\.co/papers/(\d{4}\.\d{4,5})")
# Bound the per-run title lookups: a digest carries ~15-20 ids and each one
# costs one HF API call. Seen ids are resolved once and then cached by the
# board's own store, so this converges after the first couple of runs.
MAX_LOOKUPS = 25
# Follow the newest N digest posts (one GET each). Two so a paper that fell
# off today's list is still reachable when yesterday's bake was missed.
MAX_DIGESTS = 2
DIGEST_TITLE_PREFIX = "AI Native Daily Paper Digest"
_ITEM = re.compile(r"<item>(.*?)</item>", re.S)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_LINK = re.compile(r"<link>(.*?)</link>", re.S)
_YYYYMMDD = re.compile(r"\b(\d{8})\b")
_HEADING = re.compile(r"<h[23][^>]*>(.*?)</h[23]>", re.S)
_TAG = re.compile(r"<[^>]+>")
_NUMBERED = re.compile(r"^\s*(\d{1,3})\.\s*(.+?)\s*$", re.S)
MAX_TITLE = 200


def parse_ids(feed_text: Any) -> List[str]:
    """Paper ids referenced by the feed, in order, de-duplicated.

    Deliberately regex over raw text rather than XML parsing: the ids are the
    only thing we trust from this document, and a malformed feed must degrade
    to "no ids" instead of raising.
    """
    if not isinstance(feed_text, str):
        return []
    seen, out = set(), []
    for match in _PAPER_ID.finditer(feed_text):
        paper_id = match.group(1)
        if paper_id not in seen:
            seen.add(paper_id)
            out.append(paper_id)
    return out


def _text(fragment: str) -> str:
    """Tags stripped, entities decoded, whitespace collapsed. Still untrusted."""
    import html as _html
    return " ".join(_html.unescape(_TAG.sub(" ", fragment)).split())


def parse_feed_digests(feed_text: Any) -> List[Dict[str, str]]:
    """Daily paper digest posts in the feed, newest first: [{date, url}].

    Scoped to <item> blocks (the channel has its own <title>/<link>), keyed on
    the title prefix so the Industry/Product Insights posts are skipped.
    """
    if not isinstance(feed_text, str):
        return []
    out: List[Dict[str, str]] = []
    for item in _ITEM.finditer(feed_text):
        title = _TITLE.search(item.group(1))
        link = _LINK.search(item.group(1))
        if not title or not link:
            continue
        name = _text(title.group(1))
        if not name.startswith(DIGEST_TITLE_PREFIX):
            continue
        date = _YYYYMMDD.search(name)
        url = link.group(1).strip()
        if not date or not url.startswith("https://ainativefoundation.org/"):
            continue
        out.append({"date": date.group(1), "url": url})
    out.sort(key=lambda d: d["date"], reverse=True)
    return out


def parse_digest(page_text: Any) -> List[Dict[str, Any]]:
    """Numbered papers on one digest page: [{id, rank, title}], page order.

    Each numbered <h2>/<h3> owns the text up to the next heading; the first
    huggingface paper link in that span is its id. Headings with no number,
    no title or no link (the live page ends on an empty "20. ") are skipped,
    and a repeated id keeps its first (highest) placement.
    """
    if not isinstance(page_text, str):
        return []
    heads = list(_HEADING.finditer(page_text))
    seen, out = set(), []
    for i, head in enumerate(heads):
        numbered = _NUMBERED.match(_text(head.group(1)))
        if not numbered:
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(page_text)
        link = _PAPER_ID.search(page_text, head.end(), end)
        if not link or link.group(1) in seen:
            continue
        seen.add(link.group(1))
        out.append({"id": link.group(1), "rank": int(numbered.group(1)),
                    "title": numbered.group(2)[:MAX_TITLE]})
    return out


def fetch_paper(paper_id: str) -> Dict[str, Any]:
    """Real title/upvotes/date for one paper id, from HuggingFace.

    The FEED gives us an id and nothing else we trust; everything a reader
    sees is resolved here. Upvotes matter beyond display: the papers tab is
    ranked on ``paper_upvotes``, so a record without it scores zero and can
    never surface -- the source would report "ok" while contributing nothing
    (found 2026-08-29, before it shipped).
    """
    import json as _json
    from hotin.sources import _hf
    text = _hf.request_text("https://huggingface.co/api/papers/{}".format(paper_id))
    if text is None:
        return {}
    try:
        data = _json.loads(text)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _record(paper_id: str, paper: Dict[str, Any],
            digest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"curated_by": "ai-native-foundation"}
    if digest:
        meta.update({"digest_date": digest.get("date"), "digest_rank": digest.get("rank"),
                     "digest_url": digest.get("url")})
    summary = paper.get("summary")
    if isinstance(summary, str) and summary.strip():
        meta["paper_summary"] = summary.strip()
    authors = paper.get("authors")
    if isinstance(authors, list):
        names = [a.get("name").strip() for a in authors
                 if isinstance(a, dict) and isinstance(a.get("name"), str) and a.get("name").strip()]
        if names:
            meta["paper_authors"] = ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")
    title = paper.get("title")
    fallback = (digest or {}).get("title")
    if isinstance(title, str) and title.strip():
        name = title.strip()
    elif isinstance(fallback, str) and fallback.strip():
        name = fallback.strip()   # untrusted digest heading; renderers escape it
    else:
        name = "arXiv {}".format(paper_id)
    signal: Dict[str, Any] = {"paper_upvotes": finite_int(paper.get("upvotes"), 0)}
    published = paper.get("publishedAt")
    if isinstance(published, str) and published.strip():
        signal["created_at"] = published.strip()
    return {
        "entity_type": "paper",
        "entity_id": paper_id,
        "url": "https://huggingface.co/papers/{}".format(paper_id),
        "canonical_repo": None,
        "name": name,
        "source": SOURCE,
        "signal": signal,
        "meta": meta,
    }


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def _request(url: str, timeout: float = 30) -> Optional[str]:
    import urllib.request
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
        return body.decode("utf-8", "replace") if isinstance(body, bytes) else None
    except Exception:
        return None


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Papers curated by the AI Native Foundation digest. No key required."""
    del query, config
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        feed_text = _request(FEED)
        if feed_text is None:
            return {"records": [], "status": "error", "detail": "feed request failed"}
        digests = parse_feed_digests(feed_text)
        if not digests:
            return {"records": [], "status": "empty",
                    "detail": "no daily paper digest post in the feed"}
        # newest digest first, so a paper repeated across days keeps today's
        # date and rank, and MAX_LOOKUPS always covers today's list
        entries: List[Dict[str, Any]] = []
        seen = set()
        for digest in digests[:MAX_DIGESTS]:
            page = _request(digest["url"], timeout=15)
            for entry in parse_digest(page):
                if entry["id"] in seen:
                    continue
                seen.add(entry["id"])
                entries.append({**entry, "date": digest["date"], "url": digest["url"]})
        if not entries:
            return {"records": [], "status": "empty",
                    "detail": "digest post had no numbered papers"}
        records: List[Dict[str, Any]] = []
        for entry in entries[:min(requested_limit, MAX_LOOKUPS)]:
            # Title comes from HuggingFace when it answers; the digest heading
            # is only the fallback.
            records.append(_record(entry["id"], fetch_paper(entry["id"]), entry))
        return {"records": records, "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "anfpapers fetch failed"}


def selftest() -> None:
    """Parser contract, including the hostile and the wrong-URL cases."""
    feed = ("<item><title>Daily Paper Digest</title>"
            "<link>https://huggingface.co/papers/2607.16922</link>"
            "<description>also https://huggingface.co/papers/2607.18806 and "
            "a repeat https://huggingface.co/papers/2607.16922</description></item>")
    assert parse_ids(feed) == ["2607.16922", "2607.18806"], parse_ids(feed)
    # the trailing-slash trap: WordPress serves 200 + an HTML 404 page
    assert parse_ids("<!doctype html><title>Page not found</title>") == []
    # untrusted input must degrade, never raise, and never yield a non-id
    assert parse_ids(None) == []
    assert parse_ids("huggingface.co/papers/not-an-id") == []
    assert parse_ids("huggingface.co/papers/2607.16922/../evil") == ["2607.16922"]
    rec = _record("2607.16922", {"title": "A Paper", "summary": "abstract", "upvotes": 7})
    assert rec["name"] == "A Paper" and rec["signal"]["paper_upvotes"] == 7
    rec = _record("2607.16922", {})   # HF unreachable: still a valid record
    assert rec["entity_type"] == "paper" and rec["source"] == SOURCE
    assert rec["meta"]["curated_by"] == "ai-native-foundation"
    feed = ("<title>chan</title><link>https://ainativefoundation.org/</link>"
            "<item><title>Global AI Native Industry Insights &#8211; 20260903</title>"
            "<link>https://ainativefoundation.org/insights/</link></item>"
            "<item><title>AI Native Daily Paper Digest – 20260903 – A</title>"
            "<link>https://ainativefoundation.org/digest-20260903/</link></item>")
    assert parse_feed_digests(feed) == [{"date": "20260903",
                                         "url": "https://ainativefoundation.org/digest-20260903/"}]
    page = ("<h3>1. First <em>Paper</em></h3><p><a href='https://huggingface.co/papers/2607.00001'>"
            "https://huggingface.co/papers/2607.00001</a></p><h3>2. Second</h3>"
            "<p>https://huggingface.co/papers/2607.00002</p><h3>3. </h3><h3>Related</h3>")
    assert parse_digest(page) == [{"id": "2607.00001", "rank": 1, "title": "First Paper"},
                                  {"id": "2607.00002", "rank": 2, "title": "Second"}], parse_digest(page)
    assert parse_digest("<!doctype html><title>Page not found</title>") == []
    print("anfpapers selftest: ok")


if __name__ == "__main__":
    selftest()
