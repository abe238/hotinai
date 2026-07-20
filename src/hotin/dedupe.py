"""Shared repository deduplication for free-text source adapters."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


def dedupe_by_metric(
    records: Iterable[Dict[str, Any]],
    limit: int,
    metric_key: str,
    coerce: Callable[[Any], Optional[int]],
) -> List[Dict[str, Any]]:
    """Keep the highest-``metric_key`` record for each canonical repository."""
    winners: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}
    try:
        for position, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            canonical_repo = record.get("canonical_repo")
            signal = record.get("signal")
            if not isinstance(canonical_repo, str) or not isinstance(signal, dict):
                continue
            metric = coerce(signal.get(metric_key))
            if metric is None:
                continue
            current = winners.get(canonical_repo)
            if current is None or metric > current[0]:
                winners[canonical_repo] = (metric, position, record)
        ordered = sorted(winners.values(), key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ordered[:max(0, limit)]]
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
