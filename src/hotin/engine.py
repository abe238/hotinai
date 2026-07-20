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
from .health import SourceStatus
from .sources import github, hn, npm, trends, reddit, smartmoney, x, youtube


SOURCES = (github, trends, hn, npm, reddit, youtube, smartmoney, x)
_CACHE_SIGNAL_KEY = "__hotin_signal"
_CACHE_META_KEY = "__hotin_meta"
# At 12, smart-money alone remains influential but cannot exceed modest
# corroborated OSS momentum from three independent sources.
CREDIBILITY_CAP = 12.0


def _finite_number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _timestamp(value: Any) -> Optional[float]:
    """Parse an ISO timestamp or a finite Unix timestamp, returning UTC seconds."""
    number = _finite_number(value, float("nan"))
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
        _CACHE_SIGNAL_KEY: record.get("signal") if isinstance(record.get("signal"), dict) else {},
        _CACHE_META_KEY: record.get("meta") if isinstance(record.get("meta"), dict) else {},
    }
    return stored


def _source_name(source: Any) -> str:
    name = getattr(source, "SOURCE", None)
    if isinstance(name, str) and name:
        return name
    module_name = getattr(source, "__name__", "unknown")
    return module_name.rsplit(".", 1)[-1]


def _source_is_fresh(records: Iterable[Any], source_name: str, cutoff: float) -> bool:
    for record in records:
        if not isinstance(record, dict) or record.get("source") != source_name:
            continue
        fetched_at = _timestamp(record.get("fetched_at"))
        if fetched_at is not None and fetched_at >= cutoff:
            return True
    return False


def fetch_all(
    config: dict, *, limit: int = 50, timeout: float = 25.0, ttl: float = 300, cache: Any = None
) -> List[SourceStatus]:
    """Run every adapter concurrently and store any returned records in ``cache``."""
    owned_cache = cache is None
    cache = open_cache() if owned_cache else cache
    cutoff = time.time() - max(0.0, _finite_number(ttl))
    try:
        cached_records = cache.get_all()
    except Exception:
        cached_records = []
    statuses_by_source: Dict[str, SourceStatus] = {}
    pending = []
    for source in SOURCES:
        source_name = _source_name(source)
        if _source_is_fresh(cached_records, source_name, cutoff):
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
        if isinstance(payload, dict) and isinstance(payload.get(_CACHE_SIGNAL_KEY), dict):
            signal = payload[_CACHE_SIGNAL_KEY]
        elif isinstance(payload, dict):  # compatibility with pre-engine cache entries
            signal = payload
        else:
            signal = {}
    if not isinstance(meta, dict):
        meta = payload.get(_CACHE_META_KEY, {}) if isinstance(payload, dict) else {}
    result["signal"] = signal
    result["meta"] = meta if isinstance(meta, dict) else {}
    return result


def merge_by_repo(records: List[dict]) -> Dict[str, dict]:
    """Merge source records by their canonical GitHub owner/repository name."""
    merged: Dict[str, dict] = {}
    for raw_record in records:
        record = _decoded_record(raw_record)
        if record is None:
            continue
        canonical = canonicalize(record.get("canonical_repo") or record.get("url") or "")
        if canonical is None:
            continue
        current = merged.get(canonical)
        name = record.get("name") if isinstance(record.get("name"), str) else canonical
        url = record.get("url") if isinstance(record.get("url"), str) else ""
        source = record.get("source") if isinstance(record.get("source"), str) else ""
        fetched_at = _timestamp(record.get("fetched_at"))
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
    reference = _finite_number(now, time.time()) if now is not None else time.time()
    young = _is_young(signal.get("created_at"), reference)
    oss_score = (_finite_number(signal.get("trend_stars")) or
                 _finite_number(signal.get("trend_total_score")) or
                 _finite_number(signal.get("trend_collection_score")))
    momentum = math.log1p(max(0.0, oss_score)) * 2.0
    momentum += math.log1p(max(0.0, _finite_number(signal.get("npm_growth")))) * 1.0
    momentum += math.log1p(max(0.0, _finite_number(signal.get("stars")))) * (1.5 if young else 0.3)

    rank_bonus = 0.0
    starrers = meta.get("top_starrers")
    if isinstance(starrers, list):
        for starrer in starrers:
            if isinstance(starrer, dict):
                rank = _finite_number(starrer.get("rank"), 1000.0)
                rank_bonus += max(0.0, (1000.0 - rank) / 1000.0) * 0.5
    credibility = math.log1p(max(0.0, _finite_number(signal.get("smartmoney_starrers")))) * 3.0
    credibility += max(0.0, _finite_number(signal.get("smartmoney_ai1000"))) * 1.2 + rank_bonus
    # A single smart-money source must not eclipse independently corroborated momentum.
    credibility = min(credibility, CREDIBILITY_CAP)

    signal_score = math.log1p(max(0.0, _finite_number(signal.get("hn_points")))) * 1.5
    signal_score += math.log1p(max(0.0, _finite_number(signal.get("reddit_score")))) * 1.2
    signal_score += math.log1p(max(0.0, _finite_number(signal.get("youtube_views")))) * 0.3
    corroboration = 1.0 + 0.25 * max(0, source_count - 1)

    timestamps = [_timestamp(merged.get("fetched_at")), _timestamp(signal.get("pushed_at")),
                  _timestamp(signal.get("smartmoney_most_recent_star_at"))]
    known = [timestamp for timestamp in timestamps if timestamp is not None]
    freshness_days = max(0.0, (reference - max(known)) / 86400.0) if known else 9999.0
    freshness_factor = 1.0 if freshness_days <= 30 else max(0.2, 1.0 - (freshness_days - 30) / 120.0)
    category = categories.classify(result.get("name", ""), meta.get("description"), meta.get("topics"))
    score = (momentum + credibility + signal_score) * corroboration * freshness_factor
    score = score if math.isfinite(score) else 0.0

    badges: List[str] = []
    if young:
        badges.append("new")
    if freshness_days <= 30:
        badges.append("fresh")
    if _finite_number(signal.get("smartmoney_starrers")) >= 2:
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
