"""Map ranked entity records to the shared board Row view-model.

Pure functions (no I/O, never raise) that turn each entity's records into the
Row shape `render_board` consumes: {rank, name, url, meta, receipts, badges}.
Receipts are numbers (who points at it), badges are verdicts. This is the one
place record-shape knowledge meets the renderer, so the console/markdown/html
surfaces stay identical.
"""

from __future__ import annotations

import re
import time
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


_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _age_days(created_at: Any, now: Optional[float] = None) -> int:
    """Whole days since an ISO-8601 creation date; 0 when unknown/invalid."""
    match = _ISO_DATE_RE.match(created_at) if isinstance(created_at, str) else None
    if not match:
        return 0
    try:
        import calendar
        created = calendar.timegm((int(match.group(1)), int(match.group(2)),
                                   int(match.group(3)), 0, 0, 0, 0, 0, 0))
    except (ValueError, OverflowError):
        return 0
    seconds = (time.time() if now is None else now) - created
    return max(0, int(seconds // 86400))


_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _date_label(created_at: Any, now: Optional[float] = None) -> Optional[str]:
    """Compact human release date: 'Jul 14' this year, 'Oct 2024' otherwise."""
    match = _ISO_DATE_RE.match(created_at) if isinstance(created_at, str) else None
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if not 1 <= month <= 12:
        return None
    this_year = time.gmtime(time.time() if now is None else now).tm_year
    return "{} {}".format(_MONTHS[month], day if year == this_year else year)


def _clip(desc: Any, limit: int = 100) -> Optional[str]:
    """Board meta line: a tidy description or None, never an empty string."""
    if not isinstance(desc, str) or not desc.strip():
        return None
    clean = desc.strip()
    return (clean[:limit].rstrip() + "…") if len(clean) > limit else clean


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
        vel = finite_float(_meta(repo).get("velocity_per_day"), 0.0)
        if vel:
            receipts.append({"label": "+{}/day".format(_num(vel)), "kind": "stars"})
        if finite_int(signal.get("hn_points"), 0):
            receipts.append({"label": "{} pts".format(_num(finite_int(signal.get("hn_points")))), "kind": "hn"})
        if finite_float(signal.get("npm_downloads_week"), 0.0):
            receipts.append({"label": "{}/wk".format(_num(finite_float(signal.get("npm_downloads_week")))), "kind": "npm"})
        if finite_int(signal.get("reddit_score"), 0):
            receipts.append({"label": "reddit {}".format(_num(finite_int(signal.get("reddit_score")))), "kind": "reddit"})
        age = _age_days(signal.get("created_at"))
        if age:
            receipts.append({"label": "{}d old".format(age), "kind": "age"})
        raw_name = repo.get("name") if isinstance(repo.get("name"), str) else slug
        # A human title (HN/Reddit) the slug doesn't carry, else the repo's own
        # GitHub description — without this, GitHub-sourced rows (name == slug)
        # showed just the bare owner/repo with no context.
        title = raw_name if raw_name and raw_name.casefold() != str(slug).casefold() else None
        meta = _clip(title or _meta(repo).get("description"))
        rows.append({
            "rank": i, "name": slug, "url": repo.get("url"), "meta": meta,
            "receipts": receipts, "badges": _badges(repo),
        })
    return rows


def insider_rows(records: List[dict]) -> List[dict]:
    """`hotin insiders`: repos the AI Insiders are backing.

    Receipts spell out WHO: one chip per insider in AI-1000 rank order
    (the source already sorts them), capped at six plus a "+N more" tail.
    Meta carries the repo's own description."""
    rows: List[dict] = []
    for i, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            continue
        receipts: List[Dict[str, str]] = []
        names = _meta(rec).get("insiders")
        names = [n for n in names if isinstance(n, str)] if isinstance(names, list) else []
        total = finite_int(_sig(rec).get("insider_stars"), 0) or len(names)
        for j, name in enumerate(names[:6]):
            receipts.append({"label": ("★ " + name) if j == 0 else name, "kind": "insiders"})
        if total > len(names[:6]):
            receipts.append({"label": "+{} more".format(total - len(names[:6])), "kind": ""})
        if not receipts:
            insider = _insider_receipt(rec)
            if insider:
                receipts.append(insider)
        # the same board facts repos/rising carry, whenever the data exists
        s = _sig(rec)
        if finite_int(s.get("stars"), 0):
            receipts.append({"label": "{} stars".format(_num(finite_int(s.get("stars")))), "kind": "stars"})
        vel = finite_float(_meta(rec).get("velocity_per_day"), 0.0)
        if vel:
            receipts.append({"label": "+{}/day".format(_num(vel)), "kind": "stars"})
        if finite_int(s.get("hn_points"), 0):
            receipts.append({"label": "{} pts".format(_num(finite_int(s.get("hn_points")))), "kind": "hn"})
        age = _age_days(s.get("created_at"))
        if age:
            receipts.append({"label": "{}d old".format(age), "kind": "age"})
        rows.append({
            "rank": i, "name": rec.get("canonical_repo") or rec.get("name") or "?",
            "url": rec.get("url"), "meta": _clip(_meta(rec).get("description")),
            "receipts": receipts,
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
        released = _date_label(s.get("created_at"))
        if released:
            receipts.append({"label": "released {}".format(released), "kind": "age"})
        # prefer the card's own intro sentence; fall back to task · library · license;
        # a gated model with neither still gets the honest note
        bits = [_meta(m).get(k) for k in ("model_task", "model_library", "model_license")]
        tags = " · ".join(b for b in bits if isinstance(b, str) and b.strip())
        gated = "gated · access request required" if _meta(m).get("model_gated") else ""
        desc = _clip(_meta(m).get("model_description"), 140) or " · ".join(
            x for x in (tags, gated) if x)
        rows.append({"rank": i, "name": m.get("entity_id") or m.get("name") or "?",
                     "url": m.get("url"), "meta": desc or None,
                     "receipts": receipts, "badges": _badges(m)})
    return rows


def paper_rows(ranked: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for i, p in enumerate(ranked, 1):
        up = finite_int(_sig(p).get("paper_upvotes"), 0)
        receipts: List[Dict[str, str]] = []
        if up:
            receipts.append({"label": "{} upvotes".format(_num(up)), "kind": "paper"})
        published = _date_label(_sig(p).get("created_at"))
        if published:
            receipts.append({"label": "published {}".format(published), "kind": "age"})
        rows.append({"rank": i, "name": p.get("name") or p.get("entity_id") or "?",
                     "url": p.get("url"), "meta": _clip(_meta(p).get("paper_summary"), 140),
                     "receipts": receipts,
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


def rising_rows(ranked: List[dict]) -> List[dict]:
    """`hotin rising`: the freshest repos climbing fastest — velocity, not size.

    Lead receipt is stars/day (why it's rising), then total stars and age so a
    2-day-old rocket reads differently from a steady 60-day climber.
    """
    rows: List[dict] = []
    for i, r in enumerate(ranked, 1):
        if not isinstance(r, dict):
            continue
        s = _sig(r)
        receipts: List[Dict[str, str]] = []
        vel = finite_float(s.get("velocity_per_day"), 0.0)
        if vel:
            receipts.append({"label": "+{}/day".format(_num(vel)), "kind": "stars"})
        stars = finite_int(s.get("stars"), 0)
        if stars:
            receipts.append({"label": "{} stars".format(_num(stars)), "kind": "stars"})
        age = finite_int(s.get("age_days"), 0)
        if age:
            receipts.append({"label": "{}d old".format(age), "kind": "age"})
        desc = _meta(r).get("description")
        meta = desc.strip()[:80] if isinstance(desc, str) and desc.strip() else None
        rows.append({
            "rank": i, "name": r.get("canonical_repo") or r.get("name") or "?",
            "url": r.get("url"), "meta": meta,
            "receipts": receipts, "badges": [{"label": "fresh", "hot": False}],
        })
    return rows


def demo() -> None:
    import time as _t
    five_days_ago = _t.strftime("%Y-%m-%dT00:00:00Z", _t.gmtime(_t.time() - 5 * 86400))
    repo = {"canonical_repo": "a/b", "name": "A cool thing", "url": "u",
            "signal": {"smartmoney_starrers": 3, "hn_points": 936, "stars_growth": 2100,
                       "created_at": five_days_ago},
            "meta": {"top_insider": "karpathy", "velocity_per_day": 457.0},
            "badges": ["fresh", "viral", "smart-money"]}
    rows = repo_rows([repo])
    r = rows[0]
    assert r["rank"] == 1 and r["name"] == "a/b" and r["meta"] == "A cool thing"
    labels = [x["label"] for x in r["receipts"]]
    assert any("karpathy +2 insiders" in x for x in labels), labels
    assert any("+2.1k stars" in x for x in labels) and any("936 pts" in x for x in labels)
    assert any("+457/day" in x for x in labels), labels
    assert any(x == "5d old" for x in labels), labels
    badges = {(b["label"], b["hot"]) for b in r["badges"]}
    assert ("trending", True) in badges and ("fresh", False) in badges and ("smart-money", False) in badges
    ins = insider_rows([{"canonical_repo": "x/y", "url": "u",
                         "signal": {"insider_stars": 5, "stars": 18400, "hn_points": 937},
                         "meta": {"insiders": ["simonw", "deepfates"], "top_insider": "simonw",
                                  "velocity_per_day": 432.0,
                                  "description": "a local whisper wrapper"}}])
    ins_labels = [x["label"] for x in ins[0]["receipts"]]
    # names in rank order + honest remainder, then the shared board facts
    assert ins_labels == ["★ simonw", "deepfates", "+3 more",
                          "18.4k stars", "+432/day", "937 pts"], ins_labels
    assert ins[0]["meta"] == "a local whisper wrapper"
    mod = model_rows([{"entity_id": "org/m", "url": "u",
                       "signal": {"model_downloads": 10, "model_likes": 2},
                       "meta": {"model_task": "text-generation",
                                "model_library": "transformers", "model_license": "mit"}}])
    assert mod[0]["meta"] == "text-generation · transformers · mit"
    dated = model_rows([{"entity_id": "o/d", "url": "u",
                         "signal": {"model_likes": 1, "created_at": "2024-10-03T00:00:00Z"},
                         "meta": {}}])
    assert any(r["label"] == "released Oct 2024" for r in dated[0]["receipts"])
    assert _date_label("2026-07-14T13:23:14.000Z", now=1784900000.0) == "Jul 14"
    assert _date_label("junk") is None
    gated = model_rows([{"entity_id": "g/m", "url": "u", "signal": {},
                         "meta": {"model_gated": True, "model_description": ""}}])
    assert gated[0]["meta"] == "gated · access request required"
    pap = paper_rows([{"entity_id": "1", "url": "u",
                       "signal": {"paper_upvotes": 3, "created_at": "2026-07-13T00:00:00.000Z"},
                       "meta": {"paper_summary": "  A short abstract. ", "linked_repo": "a/b"}}])
    assert pap[0]["meta"] == "A short abstract."
    assert any(r["label"].startswith("published Jul") for r in pap[0]["receipts"])
    assert news_rows([{"name": "hi", "meta": {"date": "Fri, 18 Jul 2026"}}])[0]["rank"] == "·"
    print("board demo: ok")


if __name__ == "__main__":
    demo()
