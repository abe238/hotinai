#!/usr/bin/env python3
"""Surface items with strong click evidence as exemplar candidates for Abe to
review, into docs/data/exemplars_pending.json. Read-only with respect to
tags/embeddings -- this never confirms an exemplar itself, only queues
candidates; scripts/approve_exemplar.py (run locally) is the only thing that
promotes one to confirmed. No new secret needed: reads/writes only the
already-committed JSON ledgers.

CI prints a summary so a scheduled human check (or a future notify step) has
something to read; the mechanism doesn't depend on being pinged to work,
only to be noticed promptly.
"""

import json
import sys
from pathlib import Path

EXEMPLAR_CLICK_THRESHOLD = 5  # total clicks (days + clicks_total) to become a candidate
MAX_PENDING = 50  # bounded queue -- a runaway click spike shouldn't flood the review list


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def item_total_clicks(rec: dict) -> int:
    days_total = sum(d.get("clicks", 0) for d in (rec.get("days") or {}).values())
    return rec.get("clicks_total", 0) + days_total


def surface(clicks: dict, tags: dict, embeddings: dict, pending: dict) -> int:
    """Mutates `pending` in place. Returns the number of new candidates added."""
    already_pending = {c.get("entity_id") for c in pending.setdefault("candidates", [])}
    already_confirmed = {eid for tag_list in embeddings.get("exemplars", {}).values() for eid in tag_list}
    added = 0
    for entity_id, rec in (clicks.get("items") or {}).items():
        if entity_id in already_pending or entity_id in already_confirmed:
            continue
        if len(pending["candidates"]) >= MAX_PENDING:
            break
        total = item_total_clicks(rec)
        if total < EXEMPLAR_CLICK_THRESHOLD:
            continue
        tag_entry = tags.get(entity_id) or {}
        suggested_tag = tag_entry.get("tag", "uncategorized")
        pending["candidates"].append({
            "entity_id": entity_id, "suggested_tag": suggested_tag, "clicks": total,
            # flags whether the suggestion came from the deterministic keyword
            # classifier or an earlier exemplar-inferred pass, so a human
            # approving it can see they'd be confirming a machine's own guess
            # (the one-hop cap's structural guarantee only holds if humans
            # don't rubber-stamp an inference into a fresh exemplar).
            "tag_source": tag_entry.get("source", "keyword"),
        })
        added += 1
    return added


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    docs = repo_root / "docs"
    clicks = load_json(docs / "data" / "clicks.json", {"items": {}})
    tags = load_json(docs / "data" / "tags.json", {"items": {}}).get("items", {})
    embeddings = load_json(docs / "data" / "embeddings.json", {"exemplars": {}})
    pending = load_json(docs / "data" / "exemplars_pending.json", {"_schema_version": 1, "candidates": []})

    added = surface(clicks, tags, embeddings, pending)
    if added:
        (docs / "data").mkdir(parents=True, exist_ok=True)
        (docs / "data" / "exemplars_pending.json").write_text(
            json.dumps(pending, indent=2, allow_nan=False))
    print(f"surface_exemplar_candidates: {added} new candidate(s), "
          f"{len(pending['candidates'])} pending total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
