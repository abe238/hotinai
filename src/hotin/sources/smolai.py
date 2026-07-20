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
import html
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


_ITEM_RE = re.compile(r"<item\b[^>]*>(.*?)</item>", re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_LINK_RE = re.compile(r"<link\b[^>]*>(.*?)</link>", re.DOTALL | re.IGNORECASE)
_DATE_RE = re.compile(r"<pubDate\b[^>]*>(.*?)</pubDate>", re.DOTALL | re.IGNORECASE)


def _clean(text: str) -> str:
    inner = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
    return html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()


def parse_news(feed_text: Any) -> List[Dict[str, Any]]:
    """Extract recent AINews items (title, link, date) as news records.

    Tolerant of malformed XML: it walks <item> blocks with regex and skips any
    item missing a title or link, so one broken entry never drops the feed. This
    surfaces headlines + links (attribution to AINews/Latent Space); it does not
    re-serve their prose.
    """
    if not isinstance(feed_text, str):
        return []
    news: List[Dict[str, Any]] = []
    try:
        for block in _ITEM_RE.findall(feed_text):
            title_match = _TITLE_RE.search(block)
            link_match = _LINK_RE.search(block)
            if not title_match or not link_match:
                continue
            title = _clean(title_match.group(1))
            link = _clean(link_match.group(1))
            if not title or not link.startswith("http"):
                continue
            date_match = _DATE_RE.search(block)
            news.append({
                "entity_type": "news",
                "entity_id": link,
                "url": link,
                "name": title,
                "source": SOURCE,
                "signal": {},
                "meta": {"date": _clean(date_match.group(1)) if date_match else "",
                         "publisher": "AINews (smol.ai / Latent Space)"},
            })
    except (AttributeError, TypeError, ValueError, re.error):
        return []
    return news


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

    # news headlines: title + link per item, tolerant of a broken item and CDATA
    feed = (
        '<rss><channel>'
        '<item><title>Kimi K3 release</title><link>https://news.smol.ai/issues/1</link>'
        '<pubDate>Fri, 17 Jul 2026 00:00:00 GMT</pubDate></item>'
        '<item><title>no link here</title></item>'
        '<item><title><![CDATA[GLM-5.2 drops]]></title><link>https://news.smol.ai/issues/2</link></item>'
        '</channel></rss>'
    )
    news = parse_news(feed)
    assert [n["name"] for n in news] == ["Kimi K3 release", "GLM-5.2 drops"]
    assert news[0]["entity_type"] == "news" and news[0]["url"] == "https://news.smol.ai/issues/1"
    assert parse_news("garbage") == []
    print("smolai selftest: ok")


if __name__ == "__main__":
    selftest()
