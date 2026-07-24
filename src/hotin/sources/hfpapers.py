"""HuggingFace daily trending papers (paper entity).

Extracts the ``DailyPapers`` JSON island embedded in the page's ``data-props``
attribute. Emits ``entity_type="paper"`` records keyed by arXiv id, and captures
each paper's linked GitHub repo (``githubRepo``) as a cross-entity link. Never
raises.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List, Optional

from hotin.canonical import canonicalize
from hotin.coerce import finite_int
from hotin.sources import _hf


SOURCE = "hfpapers"
ENDPOINT = "https://huggingface.co/papers"
_DATA_PROPS_RE = re.compile(r'data-target="DailyPapers"[^>]*\bdata-props="([^"]*)"')


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def extract_papers_props(html_text: Any) -> Optional[Any]:
    """Return the decoded DailyPapers props, or None if the island is absent.

    None specifically means the page no longer exposes its expected shape, so
    the caller can distinguish schema drift from a genuinely empty day.
    """
    if not isinstance(html_text, str):
        return None
    match = _DATA_PROPS_RE.search(html_text)
    if match is None:
        return None
    try:
        return json.loads(html.unescape(match.group(1)))
    except (TypeError, ValueError):
        return None


def _author_names(authors: Any) -> List[str]:
    names: List[str] = []
    if isinstance(authors, list):
        for author in authors[:6]:
            name = author.get("name") if isinstance(author, dict) else None
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    return names


def parse_papers(props: Any) -> List[Dict[str, Any]]:
    """Purely turn DailyPapers props into paper-entity Records; skip malformed."""
    entries = props.get("dailyPapers") if isinstance(props, dict) else None
    if not isinstance(entries, list):
        return []
    records: List[Dict[str, Any]] = []
    try:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            paper = entry.get("paper") if isinstance(entry.get("paper"), dict) else entry
            arxiv_id = paper.get("id")
            if not isinstance(arxiv_id, str) or not arxiv_id.strip():
                continue
            arxiv_id = arxiv_id.strip()
            title = paper.get("title") or entry.get("title")
            name = title.strip() if isinstance(title, str) and title.strip() else arxiv_id

            signal: Dict[str, Any] = {"paper_upvotes": finite_int(paper.get("upvotes"), 0)}
            published = paper.get("publishedAt") or entry.get("publishedAt")
            if isinstance(published, str) and published.strip():
                signal["created_at"] = published.strip()

            meta: Dict[str, Any] = {"paper_title": name}
            summary = paper.get("summary") or entry.get("summary")
            if isinstance(summary, str) and summary.strip():
                meta["paper_summary"] = summary.strip()
            names = _author_names(paper.get("authors"))
            if names:
                meta["paper_authors"] = names
            # Cross-entity link: the paper's implementation repo (Loop 2E bridge).
            linked = canonicalize(paper.get("githubRepo") or "")
            if linked:
                meta["linked_repo"] = linked

            records.append({
                "entity_type": "paper",
                "entity_id": arxiv_id,
                "url": "https://huggingface.co/papers/{}".format(arxiv_id),
                "canonical_repo": None,
                "name": name,
                "source": SOURCE,
                "signal": signal,
                "meta": meta,
            })
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
    return records


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Fetch HuggingFace daily trending papers. No key required."""
    del query, config
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        text = _hf.request_text(ENDPOINT)
        if text is None:
            return {"records": [], "status": "error", "detail": "huggingface papers request failed"}
        props = extract_papers_props(text)
        if props is None:
            return {"records": [], "status": "error", "detail": "huggingface papers page structure changed"}
        records = parse_papers(props)
        if not records:
            return {"records": [], "status": "empty", "detail": "no trending papers found"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "hfpapers fetch failed"}


def selftest() -> None:
    """Extraction + parser checks against a realistic and hostile fixture."""
    props = {
        "dateString": "2026-07-20",
        "dailyPapers": [
            {
                "title": "xHC: Expanded Hyper-Connections",
                "paper": {
                    "id": "2607.14530", "title": "xHC: Expanded Hyper-Connections", "upvotes": 33,
                    "authors": [{"name": "A. Researcher"}, {"name": "B. Scientist"}],
                    "githubRepo": "https://github.com/Example/xhc", "publishedAt": "2026-07-19T00:00:00Z",
                    "summary": "Expands residual hyper-connections for deeper nets.",
                },
            },
            {"paper": {"id": "  "}},          # blank id -> skipped
            {"paper": {"upvotes": 5}},        # no id -> skipped
        ],
    }
    records = parse_papers(props)
    assert [r["entity_id"] for r in records] == ["2607.14530"]
    assert records[0]["entity_type"] == "paper"
    assert records[0]["signal"]["paper_upvotes"] == 33
    assert records[0]["meta"]["paper_title"].startswith("xHC")
    assert records[0]["meta"]["paper_authors"] == ["A. Researcher", "B. Scientist"]
    assert records[0]["meta"]["linked_repo"] == "example/xhc"
    assert records[0]["meta"]["paper_summary"].startswith("Expands residual")
    assert records[0]["url"] == "https://huggingface.co/papers/2607.14530"

    escaped = '<div data-target="DailyPapers" data-props="{&quot;dailyPapers&quot;:[]}">'
    assert extract_papers_props(escaped) == {"dailyPapers": []}
    assert extract_papers_props("<div>no island here</div>") is None
    assert parse_papers({"dailyPapers": "not-a-list"}) == []
    print("hfpapers selftest: ok")


if __name__ == "__main__":
    selftest()
