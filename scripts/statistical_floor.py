#!/usr/bin/env python3
"""L4 statistical floor (chain/LOOP_CHAIN_2026-07-26.md): the trust gate
nothing downstream (least of all a future newsletter) is allowed to bypass.
Runs weekly (separate from the 3h refresh.yml), reads docs/data/{clicks,
tags}.json, writes docs/data/patterns.json.

A tag becomes a named "confirmed" pattern only when:
  1. >= MIN_ITEMS distinct entity_ids each individually clear
     MIN_SESSIONS_PER_ITEM total sessions (summed across clicks.json's
     per-day buckets plus any rolled-off frozen total) -- N independent
     items, not one item clicked N times. Entity_ids are compared
     case/whitespace-normalized so a case-variant duplicate (a real gap
     found in the L3 tracer) can't silently count as a second item.
  2. Those qualifying items collectively span >= MIN_REFERRER_DOMAINS
     distinct referrer sources, EXCLUDING GA4's own placeholder values
     ("(direct)", "(not set)", etc — not real distinct sources) -- the
     referrer-diversity gate. Stops one viral burst (a single HN post
     driving clicks on 3 items from the same referrer, plus ordinary direct
     traffic filling the second "domain") from faking independent
     corroboration.

Everything that clears (1) but not (2), or gets close to (1), lands in a
labeled `watchlist` with its raw counts shown -- never phrased as confirmed.
The weekly cadence itself is what satisfies "spans multiple CI bakes": by
the time this runs, refresh.yml has baked ~56 times since the last run, so
no separate per-item bake-count check is needed on top of the click data
clicks.json already accumulates continuously.

A tag is read from tags.json (L1/L3's live output) when available, falling
back to clicks.json's own cached copy only for an item tags.json no longer
lists — tags.json is authoritative because L3's propagation can retag an
item after clicks.json last saw fresh traffic for it; without this, a
retagged item's frozen historical sessions would keep silently corroborating
its OLD tag forever.
"""

import json
import sys
from pathlib import Path

MIN_ITEMS = 3              # N independent items required to name a pattern
MIN_SESSIONS_PER_ITEM = 3  # each item must individually clear this many sessions
MIN_REFERRER_DOMAINS = 2   # collectively, across the qualifying items

# GA4 placeholder values -- not real distinct sources, must never satisfy
# the referrer-diversity gate on their own.
_NON_DOMAINS = {"(direct)", "(none)", "(not set)", "(unknown)", ""}
_MAX_FIELD_LEN = 120  # untrusted text (repo/paper/news names) gets bounded, not just labeled


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def normalize_tag(value) -> str:
    text = str(value).strip() if value else ""
    return text if text else "uncategorized"


def normalize_entity_key(entity_id: str) -> str:
    """Case/whitespace-insensitive dedup key -- collapses a case-variant
    duplicate entity_id (e.g. `baidu/unlimited-ocr` vs `baidu/Unlimited-OCR`,
    the exact pattern the L3 tracer found) into one corroborator instead of
    two. Does not catch a base-model-vs-quantized-variant duplicate (that
    needs L3's own similarity data); recorded as `_caveats` in the output."""
    return entity_id.strip().lower()


def item_sessions(rec: dict) -> int:
    days_total = sum(d.get("sessions", 0) for d in (rec.get("days") or {}).values())
    return rec.get("sessions_total", 0) + days_total


def resolve_tag(entity_id: str, rec: dict, tags: dict) -> str:
    live = (tags.get(entity_id) or {}).get("tag") if isinstance(tags.get(entity_id), dict) else None
    return normalize_tag(live if live is not None else rec.get("tag"))


def qualifying_items_by_tag(clicks: dict, tags: dict) -> dict:
    """{tag: [(entity_id, sessions, referrers), ...]} for items individually
    clearing MIN_SESSIONS_PER_ITEM, deduped by normalized entity key (the
    higher-session duplicate wins when two keys collide)."""
    by_key: dict = {}
    for entity_id, rec in (clicks.get("items") or {}).items():
        if not isinstance(rec, dict) or not isinstance(entity_id, str):
            continue
        sessions = item_sessions(rec)
        if sessions < MIN_SESSIONS_PER_ITEM:
            continue
        tag = resolve_tag(entity_id, rec, tags)
        referrers = [r for r in (rec.get("referrers") or [])
                     if isinstance(r, str) and r.strip().lower() not in _NON_DOMAINS]
        key = normalize_entity_key(entity_id)
        existing = by_key.get(key)
        if existing is None or sessions > existing[2]:
            by_key[key] = (entity_id[:_MAX_FIELD_LEN], tag, sessions, referrers)

    by_tag: dict = {}
    for entity_id, tag, sessions, referrers in by_key.values():
        by_tag.setdefault(tag, []).append((entity_id, sessions, referrers))
    return by_tag


def compute_floor(clicks: dict, tags: dict = None) -> dict:
    """Returns {"confirmed": [...], "watchlist": [...]}. Pure function of
    clicks.json/tags.json's content -- no I/O, easily testable."""
    by_tag = qualifying_items_by_tag(clicks, tags or {})
    confirmed, watchlist = [], []

    for tag, qualifying in by_tag.items():
        if tag == "uncategorized":
            continue  # a pattern needs a real topic, not the fallback bucket
        referrer_domains = {r for _eid, _sess, refs in qualifying for r in refs}
        entry = {
            "tag": tag[:_MAX_FIELD_LEN],
            "qualifying_items": len(qualifying),
            "referrer_domains": sorted(referrer_domains),
            "items": [{"entity_id": eid, "sessions": sess} for eid, sess, _refs in qualifying],
        }
        meets_items = len(qualifying) >= MIN_ITEMS
        meets_referrers = len(referrer_domains) >= MIN_REFERRER_DOMAINS
        if meets_items and meets_referrers:
            confirmed.append(entry)
        else:
            entry["near_miss_reason"] = (
                "referrer_diversity" if meets_items and not meets_referrers
                else "item_count" if not meets_items and meets_referrers
                else "item_count_and_referrer_diversity"
            )
            watchlist.append(entry)

    confirmed.sort(key=lambda e: e["tag"])
    watchlist.sort(key=lambda e: e["tag"])
    return {"confirmed": confirmed, "watchlist": watchlist}


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    docs = repo_root / "docs"
    clicks_path = docs / "data" / "clicks.json"
    if not clicks_path.exists():
        print("statistical_floor: clicks.json missing -- refusing to overwrite patterns.json")
        return 1
    try:
        clicks = json.loads(clicks_path.read_text())
    except (ValueError, OSError) as exc:
        # unlike load_json's silent-default fallback (fine for optional
        # inputs), the primary input failing to parse must NOT fall through
        # to "treat as empty" -- that would silently erase a prior week's
        # confirmed patterns over a bad/truncated read.
        print(f"statistical_floor: clicks.json failed to parse ({exc}) -- "
              "refusing to overwrite patterns.json")
        return 1
    if not isinstance(clicks, dict):
        print("statistical_floor: clicks.json is not a JSON object -- "
              "refusing to overwrite patterns.json")
        return 1
    tags = load_json(docs / "data" / "tags.json", {"items": {}}).get("items", {})

    result = compute_floor(clicks, tags)
    out = {
        "_schema_version": 1,
        "_caveats": ["near-duplicate entity_ids across different tags/sources "
                     "(e.g. a base model vs its own quantized release) are not detected "
                     "and could each count as an independent corroborator"],
        "_untrusted_fields": ["tag", "entity_id", "referrer_domains"],
        "confirmed": result["confirmed"], "watchlist": result["watchlist"],
    }
    (docs / "data").mkdir(parents=True, exist_ok=True)
    (docs / "data" / "patterns.json").write_text(json.dumps(out, indent=2, allow_nan=False))
    print(f"statistical_floor: {len(result['confirmed'])} confirmed pattern(s), "
          f"{len(result['watchlist'])} on the watchlist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
