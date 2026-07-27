"""Repositories the AI Insiders are engaging with (repository entity).

The "smart-money" signal: GitHub repositories that a curated cohort of
influential AI accounts (the "AI Insiders") have recently starred. Formerly
scraped from a third-party page; now read directly from the sanctioned GitHub
API via the shared roster-polling core (:mod:`hotin.sources._insider_roster`),
which holds the roster and reads each member's own recently-starred repos.

This module is a thin shape-mapper: it calls the shared core (memoized, so the
sibling ``smartmoney`` adapter shares the single poll) and renders the aggregate
into the record shape the board and engine already expect — ``meta.insiders``
(the starrer usernames), ``meta.top_insider``, ``signal.insider_stars``. Its
output contract is unchanged from the scraper era, so ``board.insider_rows`` and
the ``hotin insiders`` command need no edits.

Best-effort like every adapter: never raises; a missing token or transport
failure returns a result dict with an error status, not an exception.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict, List, Optional

from hotin.coerce import finite_int
from hotin.sources import _insider_roster

SOURCE = "insiders"
USER_AGENT = _insider_roster._USER_AGENT


def _to_records(config: Optional[dict]) -> List[Dict[str, Any]]:
    """Poll the roster (shared, memoized) and map to insiders record shape."""
    events = _insider_roster.poll_roster(config)
    weights, default_weight = _insider_roster.load_weights(config)
    aggs = _insider_roster.aggregate_by_repo(events, weights, default_weight)
    records: List[Dict[str, Any]] = []
    for agg in aggs:
        canonical = agg["canonical_repo"]
        # Show the heaviest starrer first: with no weights this is unchanged
        # (all equal, original order preserved by the stable sort).
        usernames = sorted(
            agg["starrers"],
            key=lambda u: -weights.get(u.lower(), default_weight))
        records.append({
            "entity_type": "repo",
            "entity_id": canonical,
            "canonical_repo": canonical,
            "url": "https://github.com/{}".format(canonical),
            "name": canonical,
            "source": SOURCE,
            "signal": {
                "insider_stars": len(usernames),
                # Weighted score. Equals insider_stars when no weights are
                # configured, so nothing downstream has to special-case it.
                "insider_weight": agg.get("weight", float(len(usernames))),
                "stars": finite_int(agg.get("stargazers_count"), 0),
                "most_recent_star_at": agg.get("most_recent_star_at"),
                # Repo age, captured at poll time rather than backfilled.
                "created_at": agg.get("repo_created_at"),
            },
            "meta": {
                "insiders": usernames,
                "top_insider": usernames[0] if usernames else None,
                "description": agg.get("description"),
            },
        })
    return records


def _normalise_limit(limit: Any) -> int:
    value = finite_int(limit)
    return 50 if value is None else max(0, value)


def fetch_created_at(repo_id: Any, token: Optional[str] = None) -> Optional[str]:
    """One repo's immutable creation date from the GitHub API, or None."""
    if not isinstance(repo_id, str) or "/" not in repo_id:
        return None
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = "Bearer {}".format(token)
    try:
        request = urllib.request.Request(
            "https://api.github.com/repos/{}".format(repo_id.strip()), headers=headers)
        _insider_roster._THROTTLE.wait()
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        created = payload.get("created_at") if isinstance(payload, dict) else None
        return created.strip() if isinstance(created, str) and created.strip() else None
    except Exception:
        return None


def backfill_created_at(cache: Any, token: Optional[str] = None, *, max_calls: int = 40) -> int:
    """Heal cached insiders rows missing the repo creation date (needed for the
    site's 7d/60d windows). Dates are immutable, so each repo costs one API call
    ever; 404/private cache '' so we never refetch. Bounded per run; never
    raises; returns rows healed."""
    healed = 0
    try:
        for raw in cache.get_all():
            if healed >= max_calls:
                break
            if not isinstance(raw, dict) or raw.get("entity_type") != "repo":
                continue
            if raw.get("source") != SOURCE:
                continue
            payload = raw.get("signal_json")
            try:
                payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            signal = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}
            if signal.get("created_at") is not None:
                continue
            signal["created_at"] = fetch_created_at(raw.get("entity_id"), token) or ""
            payload["signal"] = signal
            updated = dict(raw)
            updated["signal_json"] = payload
            updated["fetched_at"] = raw.get("fetched_at")  # heal, keep age
            cache.upsert(updated)
            healed += 1
    except Exception:
        return healed
    return healed


def fetch(
    query: Optional[str] = None, *, limit: int = 50, config: Optional[dict] = None
) -> Dict[str, Any]:
    """Return repositories the AI Insiders are engaging with (top ``limit``)."""
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
            return {"records": [], "status": "empty",
                    "detail": "no roster stars in window"}
        return {"records": records[:requested_limit], "status": "ok", "detail": None}
    except Exception:
        return {"records": [], "status": "error", "detail": "insiders fetch failed"}


def selftest() -> None:
    """Map shared-core events to insiders records; dedupe across roster members."""
    _insider_roster._reset_memo()
    events = [
        {"username": "karpathy", "canonical_repo": "owner/repo",
         "starred_at": "2026-07-24T00:00:00Z", "stargazers_count": 311,
         "description": "an agent harness"},
        {"username": "simonw", "canonical_repo": "owner/repo",  # same repo, 2nd starrer
         "starred_at": "2026-07-25T00:00:00Z", "stargazers_count": 311, "description": None},
        {"username": "simonw", "canonical_repo": "solo/pick",
         "starred_at": "2026-07-20T00:00:00Z", "stargazers_count": 4, "description": "solo"},
    ]
    records = [
        {
            "entity_id": agg["canonical_repo"],
            "insider_stars": len(agg["starrers"]),
            "insiders": agg["starrers"],
            "most_recent": agg["most_recent_star_at"],
        }
        for agg in _insider_roster.aggregate_by_repo(events)
    ]
    top = records[0]
    assert top["entity_id"] == "owner/repo", records
    assert top["insider_stars"] == 2, top          # both roster members counted once
    assert top["insiders"] == ["karpathy", "simonw"], top
    assert top["most_recent"] == "2026-07-25T00:00:00Z", top  # most-recent wins
    assert records[1]["entity_id"] == "solo/pick" and records[1]["insider_stars"] == 1
    assert fetch(limit=0)["status"] == "empty"
    assert fetch(config={})["status"] == "error"   # missing token is loud
    print("insiders selftest: ok")


if __name__ == "__main__":
    selftest()
