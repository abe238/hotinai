#!/usr/bin/env python3
"""L3 tracer (chain/LOOP_CHAIN_2026-07-26.md): compute an embedding for every
tagged item and write docs/data/embeddings.json as a READ-ONLY artifact — no
propagation/matching logic here by design. The whole point of the tracer is
to let a human inspect whether the embedding space actually clusters on the
*editorial* dimension (agent-orchestration vs not) before any code writes an
inferred tag from it.

Local, free model (sentence-transformers/all-MiniLM-L6-v2 — a small, fast,
widely-used default) per an explicit choice to avoid a new paid API key/
secret; the cost is a heavier CI dependency and a slower job, accepted
knowingly. This script is intentionally NOT wired into refresh.yml yet — it
runs standalone until the tracer evidence is reviewed and approved.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def item_text(entity_id: str, entity_type: str, meta: dict, name: str) -> str:
    """The same text classify() would see, roughly — name + the most
    descriptive field available for this entity type."""
    desc = (meta.get("description") or meta.get("model_description")
            or meta.get("paper_summary") or "")
    return f"{name} {desc}".strip()


def load_corpus(latest_path: Path) -> list:
    """Pull (entity_id, entity_type, name, text) for every item across every
    tab, deduped by entity_id (a repo can appear in repos/rising/insiders)."""
    latest = json.loads(latest_path.read_text())
    entities = latest.get("entities", {})
    seen = {}
    type_by_tab = {"repos": "repo", "repos7": "repo", "rising": "repo", "rising7": "repo",
                   "insiders": "repo", "insiders7": "repo", "models": "model", "models7": "model",
                   "papers": "paper", "papers7": "paper", "news": "news", "news7": "news"}
    for tab, rows in entities.items():
        entity_type = type_by_tab.get(tab, "repo")
        for row in rows:
            if not isinstance(row, dict):
                continue
            entity_id = row.get("id")
            if not entity_id or entity_id in seen:
                continue
            name = row.get("name") or entity_id
            meta_text = row.get("meta") or ""  # board rows carry a short rendered meta string, not the raw dict
            text = f"{name} {meta_text}".strip()
            if text:
                seen[entity_id] = (entity_id, entity_type, name, text)
    return list(seen.values())


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    docs = repo_root / "docs"
    corpus = load_corpus(docs / "data" / "latest.json")
    if not corpus:
        print("compute_embeddings: no items with a stable id found — nothing to embed")
        return 0

    from sentence_transformers import SentenceTransformer
    model_name = "all-MiniLM-L6-v2"
    model = SentenceTransformer(model_name)
    texts = [c[3] for c in corpus]
    vectors = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

    now = datetime.now(timezone.utc).isoformat()
    items = {
        entity_id: {"vector": vec.tolist(), "entity_type": entity_type, "name": name,
                    "model": model_name, "computed_at": now}
        for (entity_id, entity_type, name, _text), vec in zip(corpus, vectors)
    }
    out = {"_schema_version": 1, "items": items, "exemplars": {}}
    (docs / "data").mkdir(parents=True, exist_ok=True)
    (docs / "data" / "embeddings.json").write_text(json.dumps(out, indent=2, allow_nan=False))
    print(f"compute_embeddings: wrote {len(items)} vectors ({model_name}, dim={len(vectors[0])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
