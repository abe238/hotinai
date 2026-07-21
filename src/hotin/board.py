"""Map ranked entity records to the shared board Row view-model.

Pure functions (no I/O, never raise) that turn each entity's records into the
Row shape `render_board` consumes: {rank, name, url, meta, receipts, badges}.
Receipts are numbers (who points at it), badges are verdicts. This is the one
place record-shape knowledge meets the renderer, so the console/markdown/html
surfaces stay identical.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .coerce import finite_float, finite_int


def _num(value: float) -> str:
    """Compact human number: 2100 -> 2.1k, 1.2M, 3.4M; whole values stay whole."""
    value = float(value)
    for unit in ("", "k", "M", "B"):
        if abs(value) < 1000:
            if unit and abs(value) < 100:
                return "{:.1f}".format(value).rstrip("0").rstrip(".") + unit
            return "{:.0f}{}".format(value, unit)
        value /= 1000
    return "{:.0f}T".format(value)


def _sig(record: dict) -> dict:
    signal = record.get("signal")
    return signal if isinstance(signal, dict) else {}


def _meta(record: dict) -> dict:
    meta = record.get("meta")
    return meta if isinstance(meta, dict) else {}


def _insider_receipt(record: dict) -> Optional[Dict[str, str]]:
    """`★ karpathy +38 insiders` when the AI Insiders are on a repo."""
    n = finite_int(_sig(record).get("smartmoney_starrers") or _sig(record).get("insider_stars"), 0)
    if not n:
        return None
    who = _meta(record).get("insiders") or _meta(record).get("top_starrers") or []
    lead = None
    if isinstance(who, list) and who:
        first = who[0]
        lead = first.get("username") if isinstance(first, dict) else (first if isinstance(first, str) else None)
    lead = _meta(record).get("top_insider") or lead
    label = "★ {} +{} insiders".format(lead, n - 1) if lead and n > 1 else (
        "★ {} · insider".format(lead) if lead else "★ {} insiders".format(n))
    return {"label": label, "kind": "insiders"}


_ENGINE_BADGE_MAP = {
    "fresh": ("fresh", False),
    "smart-money": ("smart-money", False),
    "paper-backed": ("paper-backed", False),
    "viral": ("trending", True),      # viral = trending, turned up
    "rising": ("trending", False),    # rising shows in the receipt number too
    "trending": ("trending", False),
}


def _badges(record: dict) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for raw in record.get("badges") or []:
        mapped = _ENGINE_BADGE_MAP.get(raw)
        if not mapped:
            continue
        label, hot = mapped
        key = label
        if key in seen:
            # if both rising and viral present, keep the hotter one
            if hot:
                for b in out:
                    if b["label"] == label:
                        b["hot"] = True
            continue
        seen.add(key)
        out.append({"label": label, "hot": hot})
    return out


def repo_rows(ranked: List[dict]) -> List[dict]:
    """Fused repo board rows: receipts = the numbers, badges = the verdicts."""
    rows: List[dict] = []
    for i, repo in enumerate(ranked, 1):
        if not isinstance(repo, dict):
            continue
        signal = _sig(repo)
        slug = repo.get("canonical_repo") or repo.get("name") or "?"
        receipts: List[Dict[str, str]] = []
        insider = _insider_receipt(repo)
        if insider:
            receipts.append(insider)
        growth = finite_int(signal.get("stars_growth"), 0)
        if growth:
            receipts.append({"label": "+{} stars".format(_num(growth)), "kind": "stars"})
        elif finite_int(signal.get("stars"), 0):
            receipts.append({"label": "{} stars".format(_num(finite_int(signal.get("stars")))), "kind": "stars"})
        if finite_int(signal.get("hn_points"), 0):
            receipts.append({"label": "{} pts".format(_num(finite_int(signal.get("hn_points")))), "kind": "hn"})
        if finite_float(signal.get("npm_downloads_week"), 0.0):
            receipts.append({"label": "{}/wk".format(_num(finite_float(signal.get("npm_downloads_week")))), "kind": "npm"})
        if finite_int(signal.get("reddit_score"), 0):
            receipts.append({"label": "reddit {}".format(_num(finite_int(signal.get("reddit_score")))), "kind": "reddit"})
        name = repo.get("name") if isinstance(repo.get("name"), str) else slug
        meta = None
        if name and name.casefold() != str(slug).casefold():
            meta = name  # a human title (HN/Reddit) the slug doesn't carry
            name = slug
        rows.append({
            "rank": i, "name": name, "url": repo.get("url"), "meta": meta,
            "receipts": receipts, "badges": _badges(repo),
        })
    return rows


def insider_rows(records: List[dict]) -> List[dict]:
    """`hotin insiders`: repos the AI Insiders are backing, receipts led by names."""
    rows: List[dict] = []
    for i, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            continue
        receipts = []
        insider = _insider_receipt(rec)
        if insider:
            receipts.append(insider)
        rows.append({
            "rank": i, "name": rec.get("canonical_repo") or rec.get("name") or "?",
            "url": rec.get("url"), "meta": None, "receipts": receipts,
            "badges": [{"label": "smart-money", "hot": False}],
        })
    return rows


def model_rows(ranked: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for i, m in enumerate(ranked, 1):
        s = _sig(m)
        receipts = []
        if finite_int(s.get("model_downloads"), 0):
            receipts.append({"label": "{} downloads".format(_num(finite_int(s.get("model_downloads")))), "kind": "npm"})
        if finite_int(s.get("model_likes"), 0):
            receipts.append({"label": "{} likes".format(_num(finite_int(s.get("model_likes")))), "kind": "stars"})
        rows.append({"rank": i, "name": m.get("entity_id") or m.get("name") or "?",
                     "url": m.get("url"), "meta": (_meta(m).get("model_task") or None),
                     "receipts": receipts, "badges": _badges(m)})
    return rows


def paper_rows(ranked: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for i, p in enumerate(ranked, 1):
        up = finite_int(_sig(p).get("paper_upvotes"), 0)
        rows.append({"rank": i, "name": p.get("name") or p.get("entity_id") or "?",
                     "url": p.get("url"), "meta": None,
                     "receipts": ([{"label": "{} upvotes".format(_num(up)), "kind": "paper"}] if up else []),
                     "badges": [{"label": "paper-backed", "hot": False}] if _meta(p).get("linked_repo") else []})
    return rows


def news_rows(items: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # AINews titles are mostly the "not much happened today" filler, so the
        # date is the useful, clickable handle; fall back to the title if dateless.
        date = (_meta(item).get("date") or "")[:16]
        rows.append({"rank": "·", "name": date or item.get("name") or "?",
                     "url": item.get("url"), "meta": None, "receipts": [], "badges": []})
    return rows


def demo() -> None:
    repo = {"canonical_repo": "a/b", "name": "A cool thing", "url": "u",
            "signal": {"smartmoney_starrers": 3, "hn_points": 936, "stars_growth": 2100},
            "meta": {"top_insider": "karpathy"}, "badges": ["fresh", "viral", "smart-money"]}
    rows = repo_rows([repo])
    r = rows[0]
    assert r["rank"] == 1 and r["name"] == "a/b" and r["meta"] == "A cool thing"
    labels = [x["label"] for x in r["receipts"]]
    assert any("karpathy +2 insiders" in x for x in labels), labels
    assert any("+2.1k stars" in x for x in labels) and any("936 pts" in x for x in labels)
    badges = {(b["label"], b["hot"]) for b in r["badges"]}
    assert ("trending", True) in badges and ("fresh", False) in badges and ("smart-money", False) in badges
    ins = insider_rows([{"canonical_repo": "x/y", "url": "u", "signal": {"insider_stars": 5},
                         "meta": {"insiders": ["simonw", "deepfates"], "top_insider": "simonw"}}])
    assert ins[0]["receipts"][0]["label"] == "★ simonw +4 insiders"
    assert news_rows([{"name": "hi", "meta": {"date": "Fri, 18 Jul 2026"}}])[0]["rank"] == "·"
    print("board demo: ok")


if __name__ == "__main__":
    demo()
