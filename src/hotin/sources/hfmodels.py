"""HuggingFace trending models (model entity).

Uses the official JSON API (no key). Emits ``entity_type="model"`` records keyed
by the HF model id (``org/name``); never a repo. Never raises.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from hotin.coerce import finite_int
from hotin.sources import _hf


SOURCE = "hfmodels"
ENDPOINT = "https://huggingface.co/api/models"


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def parse_models(payload: Any) -> List[Dict[str, Any]]:
    """Purely parse an HF ``/api/models`` response into model-entity Records."""
    if not isinstance(payload, list):
        return []
    records: List[Dict[str, Any]] = []
    try:
        for item in payload:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id") or item.get("modelId")
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            model_id = model_id.strip()

            signal: Dict[str, Any] = {
                "model_downloads": finite_int(item.get("downloads"), 0),
                "model_likes": finite_int(item.get("likes"), 0),
            }
            trending = item.get("trendingScore")
            trending_int = finite_int(trending)
            if trending_int is not None:
                signal["model_trending_score"] = trending_int

            meta: Dict[str, Any] = {}
            task = item.get("pipeline_tag")
            if isinstance(task, str) and task.strip():
                meta["model_task"] = task.strip()
            library = item.get("library_name")
            if isinstance(library, str) and library.strip():
                meta["model_library"] = library.strip()
            for tag in item.get("tags") or []:
                if isinstance(tag, str) and tag.startswith("license:"):
                    meta["model_license"] = tag[len("license:"):]
                    break
            created = item.get("createdAt")
            if isinstance(created, str) and created.strip():
                signal["created_at"] = created.strip()

            records.append({
                "entity_type": "model",
                "entity_id": model_id,
                "url": "https://huggingface.co/{}".format(model_id),
                "canonical_repo": None,
                "name": model_id,
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
    """Fetch HuggingFace trending models. No key required."""
    del query, config
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        params = urllib.parse.urlencode({
            "sort": "trendingScore", "direction": "-1", "limit": str(min(requested_limit, 100)),
        })
        payload = _hf.request_json("{}?{}".format(ENDPOINT, params))
        if payload is None:
            return {"records": [], "status": "error", "detail": "huggingface models request failed"}
        if not isinstance(payload, list):
            # A dict/error body is a schema change, not an empty result.
            return {"records": [], "status": "error", "detail": "huggingface models response malformed"}
        records = parse_models(payload)
        if not records:
            return {"records": [], "status": "empty", "detail": "no trending models found"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "hfmodels fetch failed"}


_CODE_LINE_RE = re.compile(r"^(from |import |def |class )|[=;]\s*\S+\(|\)\s*$")
# Doc-section openers are setup text, not a description of the model itself.
_DOC_OPENER_RE = re.compile(
    r"^(inference|installation|install|usage|quick\s*start|requirements|setup|set up|"
    r"getting started|download|how to|please|refer|see)\b", re.I)


_SKIP_LINE_PREFIXES = ("#", "!", "<", "|", "---", "=", ">", "- ", "* ", "+ ")


def card_first_paragraph(text: Any) -> Optional[str]:
    """First prose paragraph of a model-card README.

    Skips YAML frontmatter and fenced code, then judges each blank-line
    paragraph on its own: one heading/badge/table/bullet/code line disqualifies
    that paragraph only (a stray badge must not nuke the good prose after it).
    Accepted prose reads like a sentence: >=40 chars with a real full stop
    (version numbers like "13.0" do not count). Pure."""
    if not isinstance(text, str) or not text.strip():
        return None
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            text = text[end + 4:]
    kept: List[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    # only the top of the card: real descriptions lead; anything qualifying
    # deeper (deployment notes, acknowledgments) is not a description.
    for block in re.split(r"\n\s*\n", "\n".join(kept))[:8]:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if any(ln.startswith(_SKIP_LINE_PREFIXES) or re.match(r"^\d+[.)] ", ln)
               or _CODE_LINE_RE.search(ln) for ln in lines):
            continue
        # markdown links are fine ("[GLM](...) is our..."), link-ONLY lines are not
        if any(re.fullmatch(r"\[[^\]]*\]\([^)]*\)[.:]?", ln) for ln in lines):
            continue
        para = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", " ".join(lines))  # unlink
        para = re.sub(r"[*_`]", "", para)
        para = para.replace(" — ", ", ").replace("—", "-")  # house style: no em dashes
        para = re.sub(r"\s+", " ", para).strip()
        if _DOC_OPENER_RE.match(para):
            continue
        if para.endswith(":") and len(para) < 80:
            continue  # a short lead-in to code/docs
        if len(para) >= 40 and re.search(r"(?<!\d)\.(?:\s|$)", para):
            return para
    return None


def fetch_description(model_id: str) -> Optional[str]:
    """One model's card intro from its README, or None. Throttled with the host."""
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    text = _hf.request_text(
        "https://huggingface.co/{}/raw/main/README.md".format(model_id.strip()))
    return card_first_paragraph(text[:20000] if isinstance(text, str) else None)


def backfill_descriptions(cache: Any, *, max_calls: int = 20) -> int:
    """Heal cached model rows lacking a card description (same convergence
    story as hfpapers.backfill_summaries: bounded per refresh, any cache).
    Never raises; returns how many rows were healed."""
    healed = 0
    try:
        for raw in cache.get_all():
            if healed >= max_calls:
                break
            if not isinstance(raw, dict) or raw.get("entity_type") != "model":
                continue
            if raw.get("source") not in (None, "", SOURCE):
                continue
            payload = raw.get("signal_json")
            try:
                payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            if meta.get("model_description") is not None:
                continue
            desc = fetch_description(raw.get("entity_id"))
            # cache "" for cards with no usable prose so we don't refetch forever
            meta["model_description"] = desc or ""
            payload["meta"] = meta
            updated = dict(raw)
            updated["signal_json"] = payload
            updated["fetched_at"] = raw.get("fetched_at")  # heal meta, keep age
            cache.upsert(updated)
            healed += 1
    except Exception:
        return healed
    return healed


def selftest() -> None:
    """Parser-only checks against a realistic and hostile fixture (no network)."""
    payload = [
        {"id": "zai-org/GLM-5.2", "downloads": 536177, "likes": 4180, "pipeline_tag": "text-generation", "trendingScore": 91},
        {"id": "  ", "downloads": 5},          # blank id -> skipped
        {"downloads": 1, "likes": 2},          # no id -> skipped
        {"id": "org/hostile", "downloads": 1e309, "likes": "bad"},
    ]
    records = parse_models(payload)
    assert [r["entity_id"] for r in records] == ["zai-org/GLM-5.2", "org/hostile"]
    assert records[0]["entity_type"] == "model"
    assert records[0]["signal"] == {"model_downloads": 536177, "model_likes": 4180, "model_trending_score": 91}
    assert records[0]["meta"]["model_task"] == "text-generation"
    assert records[0]["url"] == "https://huggingface.co/zai-org/GLM-5.2"
    # hostile numerics coerce to safe defaults, never raise
    assert records[1]["signal"]["model_downloads"] == 0 and records[1]["signal"]["model_likes"] == 0
    assert parse_models({"error": "nope"}) == []
    print("hfmodels selftest: ok")


if __name__ == "__main__":
    selftest()
