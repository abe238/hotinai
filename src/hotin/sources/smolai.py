"""smol.ai / AINews — a light repo-corroboration flag (the repos it mentions).

smol.ai is overwhelmingly a models/news signal (its trending-repo yield is tiny),
so here it contributes only a bounded credibility FLAG for the repos its editors
mention, NOT an independent corroboration source (see engine._FLAG_SOURCES).

We deliberately do NOT parse the feed as XML: we scan the raw text for GitHub
repository links. That makes this adapter immune to the feed's recurrent
malformed-XML bug (a broken tag cannot drop the whole feed). Never raises.
"""

from __future__ import annotations

import gzip
import re
import urllib.request
from typing import Any, Dict, List, Optional

from hotin.canonical import GITHUB_URL_IN_TEXT_RE, canonicalize, trim_glued_repo_name
from hotin.coerce import finite_int
from hotin.throttle import Throttle


SOURCE = "smolai"
ENDPOINT = "https://news.smol.ai/rss.xml"
THROTTLE = Throttle(min_interval=2.0, jitter=1.0)
USER_AGENT = "hotin/0.2.0"


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def parse_repos(feed_text: Any) -> List[Dict[str, Any]]:
    """Scan raw feed text for GitHub repos; robust to malformed XML by design."""
    if not isinstance(feed_text, str):
        return []
    seen: Dict[str, Dict[str, Any]] = {}
    try:
        for match in GITHUB_URL_IN_TEXT_RE.finditer(feed_text):
            owner, repo = match.groups()
            repo = trim_glued_repo_name(repo)
            canonical = canonicalize("{}/{}".format(owner, repo))
            if canonical and canonical not in seen:
                seen[canonical] = {
                    "entity_type": "repo",
                    "entity_id": canonical,
                    "url": "https://github.com/{}".format(canonical),
                    "canonical_repo": canonical,
                    "name": canonical,
                    "source": SOURCE,
                    "signal": {},
                    "meta": {"smol_mention": True},
                }
    except (AttributeError, TypeError, ValueError, OverflowError, re.error):
        return []
    return list(seen.values())


def _request() -> Optional[str]:
    """Fetch the feed text, returning None for any transport/decode failure."""
    try:
        request = urllib.request.Request(ENDPOINT, headers={"User-Agent": USER_AGENT})
        THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
        return body.decode("utf-8", "replace") if isinstance(body, bytes) else None
    except Exception:
        return None


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Return the repos smol.ai/AINews editorially mentions (a corroboration flag)."""
    del query, config
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        text = _request()
        if text is None:
            return {"records": [], "status": "error", "detail": "smol request failed"}
        records = parse_repos(text)
        if not records:
            return {"records": [], "status": "empty", "detail": "no repos mentioned in smol feed"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "smolai fetch failed"}


def selftest() -> None:
    """Even deliberately malformed XML still yields repos (we scan raw text)."""
    malformed = (
        '<rss><item><title>x</title>'
        '<description>see https://github.com/Example/Repo &unclosed entity</description>'
        '</item><item broken tag <content>https://github.com/other/tool no closing'
    )
    records = parse_repos(malformed)
    slugs = {r["canonical_repo"] for r in records}
    assert "example/repo" in slugs and "other/tool" in slugs
    assert records[0]["source"] == "smolai"
    assert records[0]["meta"]["smol_mention"] is True
    assert records[0]["entity_type"] == "repo"
    # reserved / non-repo paths are rejected by canonicalize
    assert parse_repos("https://github.com/blog/post https://github.com/features") == []
    assert parse_repos("no links here") == []
    print("smolai selftest: ok")


if __name__ == "__main__":
    selftest()
