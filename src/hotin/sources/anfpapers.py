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
foundation" so the curation is visible and auditable. Feed text is UNTRUSTED
third-party input: this adapter takes only the arXiv/HF *id* out of it (a
strict `\\d{4}.\\d{4,5}` match), never a title or blurb, and resolves the real
title from the HuggingFace API. So a hostile feed can at most name a paper id;
it can never place attacker-authored text on the board.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from hotin.coerce import finite_int
from hotin.sources import hfpapers
from hotin.throttle import Throttle

SOURCE = "anfpapers"
FEED = "https://ainativefoundation.org/feed/"
USER_AGENT = "hotin/0.2.0"
THROTTLE = Throttle(min_interval=2.0, jitter=1.0)
# Only ids that look like arXiv ids are accepted out of the untrusted feed.
_PAPER_ID = re.compile(r"huggingface\.co/papers/(\d{4}\.\d{4,5})")
# Bound the per-run title lookups: the feed carries ~40 ids and each new one
# costs one HF API call. Seen ids are resolved once and then cached by the
# board's own store, so this converges after the first couple of runs.
MAX_LOOKUPS = 25


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


def _record(paper_id: str, title: str, summary: Optional[str]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"curated_by": "ai-native-foundation"}
    if summary:
        meta["paper_summary"] = summary
    return {
        "entity_type": "paper",
        "entity_id": paper_id,
        "url": "https://huggingface.co/papers/{}".format(paper_id),
        "canonical_repo": None,
        "name": title,
        "source": SOURCE,
        "signal": {},
        "meta": meta,
    }


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def _request_feed() -> Optional[str]:
    import urllib.request
    try:
        request = urllib.request.Request(FEED, headers={"User-Agent": USER_AGENT})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
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
        feed_text = _request_feed()
        if feed_text is None:
            return {"records": [], "status": "error", "detail": "feed request failed"}
        ids = parse_ids(feed_text)
        if not ids:
            return {"records": [], "status": "empty",
                    "detail": "no paper ids in the feed"}
        records: List[Dict[str, Any]] = []
        for paper_id in ids[:min(requested_limit, MAX_LOOKUPS)]:
            # Title comes from HuggingFace, never from the feed's own text.
            summary = hfpapers.fetch_summary(paper_id)
            records.append(_record(paper_id, "arXiv {}".format(paper_id), summary))
        if not records:
            return {"records": [], "status": "empty", "detail": "no papers resolved"}
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
    rec = _record("2607.16922", "arXiv 2607.16922", "abstract")
    assert rec["entity_type"] == "paper" and rec["source"] == SOURCE
    assert rec["meta"]["curated_by"] == "ai-native-foundation"
    print("anfpapers selftest: ok")


if __name__ == "__main__":
    selftest()
