"""Fetch, combine, and rank repository signals from all source adapters."""

from __future__ import annotations

import concurrent.futures
import json
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import categories
from .cache import open_cache
from .canonical import canonicalize
from .coerce import finite_float
from .health import SourceStatus
from .sources import github, hn, npm, trends, reddit, smartmoney, x, youtube


SOURCES = (github, trends, hn, npm, reddit, youtube, smartmoney, x)
# At 12, smart-money alone remains influential but cannot exceed modest
# corroborated OSS momentum from three independent sources.
CREDIBILITY_CAP = 12.0
# Corroboration should mean "hot across sources recently", not "ever mentioned".
# A source observation older than this (i.e. the source stopped re-surfacing the
# repo) no longer counts toward the ranked view. The CLI passes this to
# merge_by_repo; direct callers/tests default to no window.
EVIDENCE_WINDOW_DAYS = 21.0


def _timestamp(value: Any) -> Optional[float]:
    """Parse an ISO timestamp or a finite Unix timestamp, returning UTC seconds."""
    number = finite_float(value, float("nan"))
    if math.isfinite(number):
        return number
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        result = parsed.timestamp()
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _is_young(created_at: Any, now: Optional[float] = None) -> bool:
    created = _timestamp(created_at)
    if created is None:
        return False
    reference = time.time() if now is None else now
    return 0 <= reference - created <= 90 * 86400


def _cache_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve adapter signal and meta in L0's single JSON cache payload."""
    stored = dict(record)
    stored["signal_json"] = {
        "signal": record.get("signal") if isinstance(record.get("signal"), dict) else {},
        "meta": record.get("meta") if isinstance(record.get("meta"), dict) else {},
    }
    return stored


def _source_name(source: Any) -> str:
    name = getattr(source, "SOURCE", None)
    if isinstance(name, str) and name:
        return name
    module_name = getattr(source, "__name__", "unknown")
    return module_name.rsplit(".", 1)[-1]


def _latest_fetch_by_source(records: Iterable[Any]) -> Dict[str, float]:
    """One pass over the cache, not one pass per source."""
    latest: Dict[str, float] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        source_name = record.get("source")
        fetched_at = _timestamp(record.get("fetched_at"))
        if not isinstance(source_name, str) or fetched_at is None:
            continue
        if fetched_at > latest.get(source_name, float("-inf")):
            latest[source_name] = fetched_at
    return latest


def fetch_all(
    config: dict, *, limit: int = 50, timeout: float = 25.0, ttl: float = 300, cache: Any = None
) -> List[SourceStatus]:
    """Run every adapter concurrently and store any returned records in ``cache``."""
    owned_cache = cache is None
    cache = open_cache() if owned_cache else cache
    cutoff = time.time() - max(0.0, finite_float(ttl, 0.0))
    try:
        cached_records = cache.get_all()
    except Exception:
        cached_records = []
    latest_fetch = _latest_fetch_by_source(cached_records)
    statuses_by_source: Dict[str, SourceStatus] = {}
    pending = []
    for source in SOURCES:
        source_name = _source_name(source)
        if latest_fetch.get(source_name, float("-inf")) >= cutoff:
            statuses_by_source[source_name] = SourceStatus(source_name, "ok", "served from cache")
        else:
            pending.append(source)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(pending))) if pending else None
    futures = {
        executor.submit(source.fetch, limit=limit, config=config): source
        for source in pending
    } if executor is not None else {}
    try:
        done, _ = concurrent.futures.wait(futures, timeout=timeout)
        for future, source in futures.items():
            source_name = _source_name(source)
            if future not in done:
                statuses_by_source[source_name] = SourceStatus(source_name, "error", "timed out")
                continue
            try:
                result = future.result()
                if not isinstance(result, dict):
                    raise ValueError("invalid adapter result")
                status = result.get("status")
                if status not in ("ok", "empty", "error"):
                    raise ValueError("invalid adapter status")
                detail = result.get("detail")
                detail = detail if isinstance(detail, str) else None
                if status == "ok":
                    records = result.get("records")
                    if not isinstance(records, list):
                        raise ValueError("invalid adapter records")
                    for record in records:
                        if isinstance(record, dict):
                            cache.upsert(_cache_record(record))
                statuses_by_source[source_name] = SourceStatus(source_name, status, detail)
            except Exception as exc:
                statuses_by_source[source_name] = SourceStatus(source_name, "error", str(exc) or "failed")
    finally:
        if executor is not None:
            # Running ThreadPoolExecutor workers cannot be killed mid-network-call;
            # cancel_futures only cancels work that has not started yet.
            executor.shutdown(wait=False, cancel_futures=True)
        if owned_cache:
            cache.close()
    return [statuses_by_source[_source_name(source)] for source in SOURCES]


def _decoded_record(record: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(record, dict):
        return None
    result = dict(record)
    signal = result.get("signal")
    meta = result.get("meta")
    payload = result.get("signal_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            payload = {}
    if not isinstance(signal, dict):
        signal = payload.get("signal", {}) if isinstance(payload, dict) else {}
        signal = signal if isinstance(signal, dict) else {}
    if not isinstance(meta, dict):
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    result["signal"] = signal
    result["meta"] = meta if isinstance(meta, dict) else {}
    return result


def merge_by_repo(
    records: List[dict], *, max_age_days: Optional[float] = None, now: Optional[float] = None
) -> Dict[str, dict]:
    """Merge source records by their canonical GitHub owner/repository name.

    When ``max_age_days`` is given, observations a source has not re-seen within
    that window are dropped before merging, so corroboration means "hot across
    sources recently" rather than "co-mentioned at any time in cache history".
    (``fetched_at`` is refreshed each time a source re-feeds a repo, so a source
    that stopped surfacing a repo leaves a stale row that this filter excludes.)
    """
    reference = time.time() if now is None else now
    cutoff = reference - max_age_days * 86400.0 if max_age_days else None
    merged: Dict[str, dict] = {}
    for raw_record in records:
        record = _decoded_record(raw_record)
        if record is None:
            continue
        # Repo views are repo-only: papers/models live in the same cache but are
        # ranked separately and must never leak into hot/search/show. (Rows with
        # no entity_type predate the entity model and are repos.)
        if record.get("entity_type", "repo") != "repo":
            continue
        canonical = canonicalize(record.get("canonical_repo") or record.get("url") or "")
        if canonical is None:
            continue
        fetched_at = _timestamp(record.get("fetched_at"))
        if cutoff is not None and fetched_at is not None and fetched_at < cutoff:
            continue  # stale evidence: not re-seen by this source within the window
        current = merged.get(canonical)
        name = record.get("name") if isinstance(record.get("name"), str) else canonical
        url = record.get("url") if isinstance(record.get("url"), str) else ""
        source = record.get("source") if isinstance(record.get("source"), str) else ""
        if current is None:
            current = {
                "canonical_repo": canonical, "url": url, "name": name, "sources": set(),
                "signal": {}, "signal_by_source": {}, "meta": {}, "fetched_at": fetched_at,
            }
            merged[canonical] = current
        if len(name) > len(current["name"]):
            current["name"] = name
        if not current["url"] and url:
            current["url"] = url
        if source:
            current["sources"].add(source)
        current["signal"].update(record["signal"])
        if source:
            current["signal_by_source"][source] = dict(record["signal"])
        current["meta"].update(record["meta"])
        if fetched_at is not None and (current["fetched_at"] is None or fetched_at > current["fetched_at"]):
            current["fetched_at"] = fetched_at
    return merged


def score_repo(merged: dict, now: Optional[float] = None) -> dict:
    """Apply the documented momentum, credibility, corroboration and freshness formula."""
    result = dict(merged)
    signal = merged.get("signal") if isinstance(merged.get("signal"), dict) else {}
    meta = merged.get("meta") if isinstance(merged.get("meta"), dict) else {}
    sources = merged.get("sources")
    source_count = len(sources) if isinstance(sources, (set, list, tuple)) else 0
    reference = finite_float(now, time.time()) if now is not None else time.time()
    young = _is_young(signal.get("created_at"), reference)
    oss_score = (finite_float(signal.get("trend_stars"), 0.0) or
                 finite_float(signal.get("trend_total_score"), 0.0) or
                 finite_float(signal.get("trend_collection_score"), 0.0))
    momentum = math.log1p(max(0.0, oss_score)) * 2.0
    momentum += math.log1p(max(0.0, finite_float(signal.get("npm_growth"), 0.0))) * 1.0
    momentum += math.log1p(max(0.0, finite_float(signal.get("stars"), 0.0))) * (1.5 if young else 0.3)

    rank_bonus = 0.0
    starrers = meta.get("top_starrers")
    if isinstance(starrers, list):
        for starrer in starrers:
            if isinstance(starrer, dict):
                rank = finite_float(starrer.get("rank"), 1000.0)
                rank_bonus += max(0.0, (1000.0 - rank) / 1000.0) * 0.5
    credibility = math.log1p(max(0.0, finite_float(signal.get("smartmoney_starrers"), 0.0))) * 3.0
    credibility += max(0.0, finite_float(signal.get("smartmoney_ai1000"), 0.0)) * 1.2 + rank_bonus
    # A single smart-money source must not eclipse independently corroborated momentum.
    credibility = min(credibility, CREDIBILITY_CAP)

    signal_score = math.log1p(max(0.0, finite_float(signal.get("hn_points"), 0.0))) * 1.5
    signal_score += math.log1p(max(0.0, finite_float(signal.get("reddit_score"), 0.0))) * 1.2
    signal_score += math.log1p(max(0.0, finite_float(signal.get("youtube_views"), 0.0))) * 0.3
    corroboration = 1.0 + 0.25 * max(0, source_count - 1)

    # Freshness reflects real repository activity (last push, last smart-money
    # star) — NOT when we happened to fetch it. Using fetch time made every
    # currently-surfaced repo look fresh and left the decay branch dead. When no
    # activity timestamp is available we neither penalize the repo nor claim a
    # freshness we cannot verify: neutral factor, no "fresh" badge.
    activity = [_timestamp(signal.get("pushed_at")),
                _timestamp(signal.get("smartmoney_most_recent_star_at"))]
    known = [timestamp for timestamp in activity if timestamp is not None]
    freshness_days = max(0.0, (reference - max(known)) / 86400.0) if known else None
    freshness_factor = (
        1.0 if freshness_days is None or freshness_days <= 30
        else max(0.2, 1.0 - (freshness_days - 30) / 120.0)
    )
    category = categories.classify(result.get("name", ""), meta.get("description"), meta.get("topics"))
    # A repo surfaced by a curated YouTube channel earns a bounded credibility
    # nudge. It is a flag, NOT a source: capped tiny (min 5% of the base, 1.0
    # absolute) so it stays well below the 25% independent-source increment.
    base = momentum + credibility + signal_score
    curated_bonus = min(1.0, 0.05 * base) if meta.get("youtube_curated") else 0.0
    score = (base + curated_bonus) * corroboration * freshness_factor
    score = score if math.isfinite(score) else 0.0

    badges: List[str] = []
    if young:
        badges.append("new")
    if freshness_days is not None and freshness_days <= 30:
        badges.append("fresh")
    if finite_float(signal.get("smartmoney_starrers"), 0.0) >= 2:
        badges.append("smart-money")
    if source_count >= 3:
        badges.append("corroborated")
    for source in ("hn", "reddit", "npm"):
        if isinstance(sources, (set, list, tuple)) and source in sources:
            badges.append(source)
    result.update({"momentum": momentum, "credibility": credibility, "signal_score": signal_score,
                   "corroboration": corroboration, "freshness_days": freshness_days,
                   "freshness_factor": freshness_factor, "category": category, "score": score,
                   "badges": badges})
    return result


def rank(merged_repos: Dict[str, dict], *, limit: int = 50) -> List[dict]:
    """Score and stably rank merged repositories."""
    scored = [score_repo(repo) for repo in merged_repos.values() if isinstance(repo, dict)]
    scored.sort(key=lambda repo: (-repo["score"], -repo["momentum"], str(repo.get("name", "")).casefold()))
    return scored[:max(0, int(limit))]


def merge_by_entity(
    records: List[dict], entity_type: str, *, max_age_days: Optional[float] = None, now: Optional[float] = None
) -> Dict[str, dict]:
    """Merge non-repo entity records (paper, model) by their ``entity_id``.

    Type-scoped: only records of ``entity_type`` are considered, so repos and
    other entity types in the same cache never bleed in. The evidence window
    applies identically to repos (see merge_by_repo).
    """
    reference = time.time() if now is None else now
    cutoff = reference - max_age_days * 86400.0 if max_age_days else None
    merged: Dict[str, dict] = {}
    for raw_record in records:
        record = _decoded_record(raw_record)
        if record is None or record.get("entity_type") != entity_type:
            continue
        entity_id = record.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id:
            continue
        fetched_at = _timestamp(record.get("fetched_at"))
        if cutoff is not None and fetched_at is not None and fetched_at < cutoff:
            continue
        current = merged.get(entity_id)
        name = record.get("name") if isinstance(record.get("name"), str) else entity_id
        url = record.get("url") if isinstance(record.get("url"), str) else ""
        source = record.get("source") if isinstance(record.get("source"), str) else ""
        if current is None:
            current = {
                "entity_type": entity_type, "entity_id": entity_id, "url": url, "name": name,
                "sources": set(), "signal": {}, "signal_by_source": {}, "meta": {}, "fetched_at": fetched_at,
            }
            merged[entity_id] = current
        if len(name) > len(current["name"]):
            current["name"] = name
        if not current["url"] and url:
            current["url"] = url
        if source:
            current["sources"].add(source)
        current["signal"].update(record["signal"])
        if source:
            current["signal_by_source"][source] = dict(record["signal"])
        current["meta"].update(record["meta"])
        if fetched_at is not None and (current["fetched_at"] is None or fetched_at > current["fetched_at"]):
            current["fetched_at"] = fetched_at
    return merged


def score_entity(merged: dict, metric_weights: Dict[str, float]) -> dict:
    """Score a paper/model: sum of log-scaled metric fields x corroboration."""
    result = dict(merged)
    signal = merged.get("signal") if isinstance(merged.get("signal"), dict) else {}
    sources = merged.get("sources")
    source_count = len(sources) if isinstance(sources, (set, list, tuple)) else 0
    base = 0.0
    for key, weight in metric_weights.items():
        base += math.log1p(max(0.0, finite_float(signal.get(key), 0.0))) * weight
    corroboration = 1.0 + 0.25 * max(0, source_count - 1)
    score = base * corroboration
    result["score"] = score if math.isfinite(score) else 0.0
    result["corroboration"] = corroboration
    return result


def rank_entities(merged_entities: Dict[str, dict], metric_weights: Dict[str, float], *, limit: int = 50) -> List[dict]:
    """Score and stably rank merged paper/model entities."""
    scored = [score_entity(entity, metric_weights) for entity in merged_entities.values() if isinstance(entity, dict)]
    scored.sort(key=lambda entity: (-entity["score"], str(entity.get("name", "")).casefold()))
    return scored[:max(0, int(limit))]
