"""HuggingFace trending models (model entity).

Uses the official JSON API (no key). Emits ``entity_type="model"`` records keyed
by the HF model id (``org/name``); never a repo. Never raises.
"""

from __future__ import annotations

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
