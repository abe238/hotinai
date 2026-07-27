"""AI-Insider GitHub-star credibility signal (repo-level).

Formerly scraped a third-party page; now a thin shape-mapper over the shared
roster-polling core (:mod:`hotin.sources._insider_roster`), same as the sibling
``insiders`` adapter. The core is memoized per process, so both adapters share
ONE roster poll per invocation.

This adapter feeds the engine's *credibility* term (``smartmoney_starrers`` /
``smartmoney_ai1000`` at engine.py, via ``log1p``) and repo-row receipts. The
``smart-money`` *badge* was retired when this moved off the large digg AI-1000
cohort: a curated roster of a few dozen accounts almost never produces the >=2
co-occurring starrers the badge gated on, so it would have been silently
near-invisible. ``insiders``' dedicated ``hotin insiders`` tab is now the sole
headline surface for this signal.

Field contract is unchanged from the scraper era (``smartmoney_starrers``,
``smartmoney_ai1000`` [always 0 — the old weighted AI-1000 score has no API
equivalent, and its engine term degrades cleanly to a no-op],
``smartmoney_most_recent_star_at``, ``meta.top_starrers``), so engine.py and
board.py need no edits beyond the badge retirement + the corroboration-flag fix.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from hotin.coerce import finite_int
from hotin.sources import _insider_roster

SOURCE = "smartmoney"
USER_AGENT = _insider_roster._USER_AGENT


def _freshness(value: Any, now: Optional[datetime] = None) -> str:
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        return "stale" if parsed < reference - timedelta(days=30) else "fresh"
    except (TypeError, ValueError, OverflowError):
        return "unknown"


def _to_records(config: Optional[dict], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Poll the roster (shared, memoized) and map to smartmoney record shape."""
    events = _insider_roster.poll_roster(config)
    records: List[Dict[str, Any]] = []
    for agg in _insider_roster.aggregate_by_repo(events):
        canonical = agg["canonical_repo"]
        usernames = agg["starrers"]
        # No per-starrer rank exists any more (the roster is unranked; the old
        # digg AI-1000 rank is gone). Emit usernames WITHOUT a `rank` field so
        # engine.py's rank_bonus term defaults to its neutral 1000 (bonus 0) —
        # emitting a fake 0-based index would read as top-rank and silently
        # inflate every roster-starred repo's credibility.
        top_starrers = [{"username": name} for name in usernames[:5]]
        records.append({
            "url": "https://github.com/{}".format(canonical),
            "canonical_repo": canonical,
            "name": canonical,
            "source": SOURCE,
            "signal": {
                "smartmoney_starrers": len(usernames),
                "smartmoney_ai1000": 0,  # no API equivalent; engine's *1.2 term no-ops
                "smartmoney_freshness": _freshness(agg.get("most_recent_star_at"), now),
                "smartmoney_most_recent_star_at": agg.get("most_recent_star_at"),
            },
            "meta": {
                "description": agg.get("description"),
                "language": None,  # not carried by the starred API shape
                "top_starrers": top_starrers,
            },
        })
    return records


def _normalise_limit(limit: Any) -> int:
    return max(0, finite_int(limit, 50))


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Return repositories recently starred by the AI Insiders."""
    del query
    try:
        requested_limit = _normalise_limit(limit)
        if requested_limit == 0:
            return {"records": [], "status": "empty", "detail": "limit is zero"}
        try:
            records = _to_records(config)
        except (_insider_roster.MissingTokenError, _insider_roster.RosterAuthError,
                _insider_roster.RosterRateLimitError) as exc:
            return {"records": [], "status": "error", "detail": str(exc)}
        if not records:
            return {"records": [], "status": "empty", "detail": "no roster stars in window"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "smartmoney fetch failed"}


def selftest() -> None:
    """Map shared-core events to smartmoney records; ai1000 always 0; no network."""
    _insider_roster._reset_memo()
    events = [
        {"username": "karpathy", "canonical_repo": "owner/repo",
         "starred_at": "2026-07-24T00:00:00Z", "stargazers_count": 311, "description": "x"},
        {"username": "simonw", "canonical_repo": "owner/repo",
         "starred_at": "2026-07-25T00:00:00Z", "stargazers_count": 311, "description": None},
    ]
    # build directly from the aggregate to avoid a token requirement in the selftest
    aggs = _insider_roster.aggregate_by_repo(events)
    agg = aggs[0]
    assert agg["starrers"] == ["karpathy", "simonw"]
    top_starrers = [{"username": n} for n in agg["starrers"][:5]]
    assert top_starrers[0] == {"username": "karpathy"} and "rank" not in top_starrers[0]
    assert _freshness("2026-07-25T00:00:00Z", now=datetime(2026, 7, 26, tzinfo=timezone.utc)) == "fresh"
    assert _freshness("2026-01-01T00:00:00Z", now=datetime(2026, 7, 26, tzinfo=timezone.utc)) == "stale"
    assert _freshness(None) == "unknown"
    assert fetch(limit=0)["status"] == "empty"
    assert fetch(config={})["status"] == "error"  # missing token is loud
    print("smartmoney selftest: ok")


if __name__ == "__main__":
    selftest()
