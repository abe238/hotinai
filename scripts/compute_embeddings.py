#!/usr/bin/env python3
"""Compute an embedding for every item in the live corpus and MERGE it into
docs/data/embeddings.json — wired into refresh.yml, running every 3h
alongside tag propagation (chain/LOOP_CHAIN_2026-07-26.md L3).

MERGE, never overwrite: both `items` and `exemplars` accumulate across runs.
`latest.json` is a *trending* board that churns constantly, so a wholesale
rewrite would (a) wipe every human-confirmed exemplar in `exemplars` the
moment this script's own output replaced the file, and (b) silently drop the
vector for any exemplar whose repo scrolled off the board, breaking its
propagation anchor with no warning (both caught in review before this
shipped). Accumulating `items` forever means an item embedded once keeps its
vector even after it's no longer trending — the same "never prune" pattern
tags.json/clicks.json already use.

Local, free model (sentence-transformers/all-MiniLM-L6-v2 — a small, fast,
widely-used default) per an explicit choice to avoid a new paid API key.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


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


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def load_existing(embeddings_path: Path) -> tuple:
    """(items, exemplars) from the current file, defaulting to empty dicts --
    the two structures a merge must preserve and never wholesale-replace."""
    existing = load_json(embeddings_path, {"_schema_version": 1, "items": {}, "exemplars": {}})
    items = existing.get("items") if isinstance(existing.get("items"), dict) else {}
    exemplars = existing.get("exemplars") if isinstance(existing.get("exemplars"), dict) else {}
    return items, exemplars


def select_uncomputed(corpus: list, items: dict, model_name: str) -> list:
    """Corpus entries not yet embedded with the current model -- an
    unchanged corpus re-run is then a fast no-op instead of a full re-embed."""
    return [c for c in corpus if items.get(c[0], {}).get("model") != model_name]


def merge_vectors(items: dict, to_embed: list, vectors: list, model_name: str, now: str) -> None:
    """Mutates `items` in place. Adds/overwrites only the entity_ids in
    `to_embed` -- every other entry in `items` (including exemplars whose
    repo has since scrolled off the trending board) is left untouched."""
    for (entity_id, entity_type, name, _text), vec in zip(to_embed, vectors):
        raw = vec.tolist() if hasattr(vec, "tolist") else list(vec)
        # 5 decimals is far below any precision that changes a cosine-
        # similarity comparison, and roughly halves the committed file size
        # across 8 writes/day.
        vec_list = [round(x, 5) for x in raw]
        items[entity_id] = {"vector": vec_list, "entity_type": entity_type, "name": name,
                             "model": model_name, "computed_at": now}


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    docs = repo_root / "docs"
    corpus = load_corpus(docs / "data" / "latest.json")
    items, exemplars = load_existing(docs / "data" / "embeddings.json")

    model_name = "all-MiniLM-L6-v2"
    to_embed = select_uncomputed(corpus, items, model_name)
    if to_embed:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        texts = [c[3] for c in to_embed]
        vectors = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        merge_vectors(items, to_embed, vectors, model_name, datetime.now(timezone.utc).isoformat())

    out = {"_schema_version": 1, "items": items, "exemplars": exemplars}
    (docs / "data").mkdir(parents=True, exist_ok=True)
    (docs / "data" / "embeddings.json").write_text(json.dumps(out, indent=2, allow_nan=False))
    print(f"compute_embeddings: {len(to_embed)} newly embedded, "
          f"{len(items)} items total, {sum(len(v) for v in exemplars.values())} exemplars preserved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
