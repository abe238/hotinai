#!/usr/bin/env python3
"""Promote a pending exemplar candidate to a confirmed exemplar. Run LOCALLY
by Abe (not in CI) after reviewing a candidate surfaced in
docs/data/exemplars_pending.json: `python3 scripts/approve_exemplar.py
<entity_id> <tag>`. Modifies docs/data/embeddings.json and
docs/data/exemplars_pending.json in the current checkout — commit + push
yourself afterward, same as any other local edit.

This is deliberately NOT a `hotin` subcommand: it's an internal instrumentation
admin action, not something the public CLI's users would ever run, and hotin's
own design keeps the public command surface to discovery/ranking only.
"""

import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("usage: python3 scripts/approve_exemplar.py <entity_id> <tag>", file=sys.stderr)
        return 2
    entity_id, tag = argv[0], argv[1]

    repo_root = Path(__file__).resolve().parents[1]
    data = repo_root / "docs" / "data"
    emb_path = data / "embeddings.json"
    pending_path = data / "exemplars_pending.json"

    embeddings = json.loads(emb_path.read_text()) if emb_path.exists() else {"_schema_version": 1, "items": {}, "exemplars": {}}
    items = embeddings.get("items", {})
    if entity_id not in items:
        print(f"error: {entity_id!r} has no computed embedding — run "
              "scripts/compute_embeddings.py first", file=sys.stderr)
        return 1

    exemplars = embeddings.setdefault("exemplars", {})
    tag_list = exemplars.setdefault(tag, [])
    if entity_id in tag_list:
        print(f"{entity_id!r} is already a confirmed exemplar for {tag!r} — nothing to do")
    else:
        tag_list.append(entity_id)
        emb_path.write_text(json.dumps(embeddings, indent=2, allow_nan=False))
        print(f"confirmed: {entity_id!r} is now an exemplar for {tag!r} "
              f"({len(tag_list)} confirmed for this tag)")

    pending = json.loads(pending_path.read_text()) if pending_path.exists() else {"_schema_version": 1, "candidates": []}
    before = len(pending.get("candidates", []))
    pending["candidates"] = [c for c in pending.get("candidates", [])
                              if c.get("entity_id") != entity_id]
    if len(pending["candidates"]) != before:
        pending_path.write_text(json.dumps(pending, indent=2, allow_nan=False))
        print(f"removed {entity_id!r} from the pending queue")

    print("Now commit + push docs/data/embeddings.json (and exemplars_pending.json if changed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
