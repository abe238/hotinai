#!/usr/bin/env python3
"""L3 propagation (chain/LOOP_CHAIN_2026-07-26.md): cosine-match every item
against confirmed exemplars and write inferred tags into docs/data/tags.json.
Four guardrails, all required (from the ideate deepen's rescue children plus
the L3 tracer's own finding — see docs/evidence/l3-embedding-tracer/):

1. ONE-HOP CAP — enforced structurally, not by a runtime check alone: this
   script only ever READS embeddings.json's "exemplars" map, never writes to
   it. Only scripts/approve_exemplar.py (run locally by a human) can mint a
   new exemplar, so an inferred tag can never itself become an anchor for
   further propagation. `propagate()` also asserts this at runtime (belt AND
   braces — a review caught that "structural" alone is a convention, not a
   guarantee against a future bug in an unrelated script).
2. MULTI-EXEMPLAR CONSENSUS — an item only inherits a tag if its best
   similarity to THAT tag's exemplars exceeds its best similarity to every
   OTHER tag's exemplars by at least CONSENSUS_MARGIN (not just any margin,
   however tiny — a near-tie can flip across runs on a trivial vector nudge
   and churn tags.json for no real reason).
3. RE-VERIFICATION LOOP — a passing match below HIGH_CONFIDENCE still
   propagates (it cleared the floor), but also gets queued back into
   exemplars_pending.json for a human spot-check, same bounded queue new
   click-sourced candidates use (MAX_PENDING shared with
   surface_exemplar_candidates.py, so propagation can't starve it).
4. NEAR-DUPLICATE FLAG — a match above NEAR_DUP_THRESHOLD almost certainly
   means "the same underlying item under a different id" (verified in the
   tracer: duplicate pairs scored 0.77-0.92 vs ~0.32-0.58 for genuine
   same-category matches). NEAR_DUP_THRESHOLD is set at 0.70, well below the
   observed duplicate floor of 0.77 and above the observed genuine-match
   ceiling of 0.58 — a review caught the original 0.85 sitting INSIDE the
   duplicate band, which would have let most duplicates through unflagged.
   The tag still propagates (a near-duplicate legitimately shares its
   twin's tag), but the entry is flagged `near_duplicate_of` so L4's
   independence count can exclude it from being treated as a second,
   independent corroborator.
"""

import json
import sys
from pathlib import Path

PROPAGATION_THRESHOLD = 0.40  # tracer: dev-tools' cross-category noise topped out ~0.36
HIGH_CONFIDENCE = 0.55        # tracer: agents' weakest genuine same-tag match was 0.459
NEAR_DUP_THRESHOLD = 0.70     # tracer: genuine matches topped out ~0.58, duplicates started at 0.77
CONSENSUS_MARGIN = 0.03       # a near-tie must not decide a tag; damps cross-run flapping
MAX_PENDING = 50              # shared bound with surface_exemplar_candidates.py


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def dot(a: list, b: list) -> float:
    if len(a) != len(b):
        return -1.0  # a dimension mismatch (mixed models, a hand-edited vector) is never a match
    return sum(x * y for x, y in zip(a, b))


def best_match_per_tag(vector: list, exemplar_vectors: dict) -> dict:
    """{tag: (best_sim, best_exemplar_id)} across every confirmed tag."""
    result = {}
    for tag, entries in exemplar_vectors.items():
        best_sim, best_id = -1.0, None
        for exemplar_id, exemplar_vec in entries:
            sim = dot(vector, exemplar_vec)
            if sim > best_sim:
                best_sim, best_id = sim, exemplar_id
        if best_id is not None:
            result[tag] = (best_sim, best_id)
    return result


def propagate(embeddings: dict, tags: dict, pending: dict) -> int:
    """Mutates `tags` and `pending` in place. Returns count of items tagged."""
    exemplars = embeddings.get("exemplars", {})
    items = embeddings.get("items", {})
    exemplar_ids = {eid for id_list in exemplars.values() if isinstance(id_list, list) for eid in id_list}

    exemplar_vectors = {}
    for tag, id_list in exemplars.items():
        if not isinstance(id_list, list):
            continue
        entries = []
        for eid in id_list:
            vec = items.get(eid, {}).get("vector") if isinstance(items.get(eid), dict) else None
            if isinstance(vec, list):
                entries.append((eid, vec))
        if entries:
            exemplar_vectors[tag] = entries
    if not exemplar_vectors:
        return 0  # no confirmed exemplars yet — nothing to propagate from

    pending_ids = {c.get("entity_id") for c in pending.setdefault("candidates", [])}
    tagged = 0
    for entity_id, entry in items.items():
        # guardrail 1 (runtime half): an exemplar's own vector is never
        # matched against the exemplar set it belongs to.
        if entity_id in exemplar_ids:
            continue
        vector = entry.get("vector") if isinstance(entry, dict) else None
        if not isinstance(vector, list):
            continue  # a malformed item entry is skipped, never a crash
        matches = best_match_per_tag(vector, exemplar_vectors)
        if not matches:
            continue
        best_tag = max(matches, key=lambda t: matches[t][0])
        best_sim, best_exemplar_id = matches[best_tag]
        if best_sim < PROPAGATION_THRESHOLD:
            continue
        # guardrail 2: multi-exemplar consensus with a real margin, not a
        # bare tie-break — a razor-thin lead must not decide a tag.
        conflicting = [sim for tag, (sim, _eid) in matches.items() if tag != best_tag]
        if conflicting and (best_sim - max(conflicting)) < CONSENSUS_MARGIN:
            continue

        record = {"tag": best_tag, "source": "exemplar-inferred",
                  "confidence": round(best_sim, 4), "matched_exemplar": best_exemplar_id}
        if best_sim >= NEAR_DUP_THRESHOLD:
            record["near_duplicate_of"] = best_exemplar_id  # guardrail 4
        tags[entity_id] = record
        tagged += 1

        # guardrail 3, bounded: a low-confidence pass still gets queued for a
        # human spot-check, but never past the shared queue cap — propagation
        # must not be able to starve click-sourced candidates.
        if (best_sim < HIGH_CONFIDENCE and entity_id not in pending_ids
                and len(pending["candidates"]) < MAX_PENDING):
            pending["candidates"].append({
                "entity_id": entity_id, "suggested_tag": best_tag,
                "tag_source": "exemplar-inferred",  # flags this suggestion as a machine
                                                     # guess to a human reviewer, so approving
                                                     # it isn't a laundered second hop
                "reason": "low-confidence-inference", "confidence": round(best_sim, 4),
            })
            pending_ids.add(entity_id)
    return tagged


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    docs = repo_root / "docs"
    embeddings = load_json(docs / "data" / "embeddings.json", {"items": {}, "exemplars": {}})
    tags_doc = load_json(docs / "data" / "tags.json", {"_schema_version": 1, "items": {}})
    tags = tags_doc.setdefault("items", {})
    pending = load_json(docs / "data" / "exemplars_pending.json", {"_schema_version": 1, "candidates": []})

    tagged = propagate(embeddings, tags, pending)
    if tagged:
        (docs / "data").mkdir(parents=True, exist_ok=True)
        (docs / "data" / "tags.json").write_text(json.dumps(tags_doc, indent=2, allow_nan=False))
        (docs / "data" / "exemplars_pending.json").write_text(json.dumps(pending, indent=2, allow_nan=False))
    print(f"propagate_tags: {tagged} item(s) tagged via exemplar propagation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
