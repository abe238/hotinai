#!/usr/bin/env python3
"""Fold GA4 select_result clicks into docs/data/clicks.json — a permanent,
small, per-item aggregate. Never stores a raw per-click row or a raw session
id: GA4's own `sessions` metric supplies the unique-session count, aggregated
server-side.

Per-day, idempotent by construction: this runs every 3h against a rolling
WINDOW_DAYS-day GA4 window, so the SAME day's total gets re-queried on every
run. Folding must ASSIGN each day's count, never add to it — `+=` on a
rolling window double/N-counts every click for as many runs as it stays
inside the window (caught in review: a click clicked once inflated to 24x
over a 3-day window at the 3h cadence). Each item's ledger entry carries a
small `days` dict (only the still-in-window days) plus a frozen
`clicks_total`/`sessions_total` that OLD days get rolled into once they age
out of the window — so the ledger never grows unbounded and a re-pull can
never re-add an already-rolled-off day. A reader wanting an item's lifetime
total sums `clicks_total` + every count in `days`.

Two-pass, honest about GA4's processing lag: the `id` custom dimension was
only just registered (L1 of chain/LOOP_CHAIN_2026-07-26.md) and can take
~24-48h before runReport returns rows broken out by it. This script checks
whether select_result events happened at all in the window (a query with NO
id breakdown); if events exist but the id-broken-down report is still empty,
that is BREAKDOWN_PENDING, not zero clicks — the next run naturally retries.

Auth: OAuth refresh-token exchange, GitHub Actions secrets first (CI), local
~/.config files second (manual/dev runs) -- see insights.py for why this
never uses `gcloud auth application-default print-access-token` (it
truncates the token when piped). Every GA4/auth failure is caught and
degrades to "leave clicks.json untouched, exit 0" — an analytics pull must
never cost the board its daily refresh, matching every source adapter's own
fail-soft contract.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROPERTY = "546946466"
QUOTA_PROJECT = "hotin-analytics"
CREDS_PATH = Path.home() / ".config/gcloud/application_default_credentials.json"
CLIENT_PATH = Path.home() / ".config/hotin-analytics/oauth_client.json"
WINDOW_DAYS = 3  # overlaps prior runs so a still-processing window gets retried
MAX_REFERRERS = 10  # bounded — this is a diversity signal, not a full log


class GA4Error(Exception):
    pass


def get_token() -> str:
    try:
        refresh_token = os.environ.get("GA_REFRESH_TOKEN")
        client_id = os.environ.get("GA_CLIENT_ID")
        client_secret = os.environ.get("GA_CLIENT_SECRET")
        if not (refresh_token and client_id and client_secret):
            creds = json.loads(CREDS_PATH.read_text())
            client = json.loads(CLIENT_PATH.read_text())["installed"]
            refresh_token = creds["refresh_token"]
            client_id = client["client_id"]
            client_secret = client["client_secret"]
        data = urllib.parse.urlencode({
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)["access_token"]
    except Exception as exc:  # noqa: BLE001 - any auth failure degrades the same way
        raise GA4Error(f"auth failed: {exc}") from None


def _call(token: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport",
        data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": "Bearer " + token, "x-goog-user-project": QUOTA_PROJECT,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise GA4Error(f"runReport: HTTP {e.code} — {e.read().decode()[:400]}") from None


def total_select_result_count(token: str) -> int:
    """No id breakdown -- just "did select_result fire at all this window."""
    resp = _call(token, {
        "dateRanges": [{"startDate": f"{WINDOW_DAYS}daysAgo", "endDate": "today"}],
        "dimensions": [{"name": "eventName"}],
        "metrics": [{"name": "eventCount"}],
        "dimensionFilter": {"filter": {"fieldName": "eventName",
                                        "stringFilter": {"value": "select_result"}}},
    })
    rows = resp.get("rows") or []
    if not rows:
        return 0
    try:
        return int(rows[0]["metricValues"][0]["value"])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0


def id_breakdown(token: str) -> list:
    resp = _call(token, {
        "dateRanges": [{"startDate": f"{WINDOW_DAYS}daysAgo", "endDate": "today"}],
        "dimensions": [{"name": "customEvent:id"}, {"name": "date"}, {"name": "sessionSource"}],
        "metrics": [{"name": "eventCount"}, {"name": "sessions"}],
        "dimensionFilter": {"filter": {"fieldName": "eventName",
                                        "stringFilter": {"value": "select_result"}}},
        "limit": 5000,
    })
    rows = resp.get("rows") or []
    row_count = resp.get("rowCount", len(rows))
    if row_count > len(rows):
        print(f"pull_clicks: WARNING truncated — {row_count} rows reported, "
              f"only {len(rows)} returned (limit too low)")
    return rows


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def fold_clicks(clicks: dict, tags: dict, rows: list, today: "date | None" = None) -> int:
    """Merge GA4 rows into the per-item ledger. ASSIGNS each day's count
    (idempotent: re-querying the same day's total from GA4 and overwriting is
    correct — GA4's own total for a finished day never changes, and "today"'s
    total naturally grows across the day's 3h runs, which overwrite-not-add is
    exactly right for). Returns the number of (item, day) cells touched.
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    cutoff = (today - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d")
    items = clicks.setdefault("items", {})
    folded = 0
    for row in rows:
        dims = row.get("dimensionValues") or []
        mets = row.get("metricValues") or []
        if len(dims) < 3 or len(mets) < 2:
            continue
        entity_id = dims[0].get("value")
        date_key = dims[1].get("value")
        source = dims[2].get("value") or "(unknown)"
        if not entity_id or entity_id == "(not set)" or not date_key:
            continue
        try:
            event_count = int(mets[0].get("value") or 0)
            sessions = int(mets[1].get("value") or 0)
        except (TypeError, ValueError):
            continue
        tag = (tags.get(entity_id) or {}).get("tag", "uncategorized")
        rec = items.setdefault(entity_id, {
            "tag": tag, "days": {}, "clicks_total": 0, "sessions_total": 0,
            "referrers": [], "first_click_at": date_key, "last_click_at": date_key,
        })
        rec["tag"] = tag  # tags can be re-inferred later (L3); keep current
        rec["days"][date_key] = {"clicks": event_count, "sessions": sessions}
        rec["first_click_at"] = min(rec["first_click_at"] or date_key, date_key)
        rec["last_click_at"] = max(rec["last_click_at"] or date_key, date_key)
        if source not in rec["referrers"] and len(rec["referrers"]) < MAX_REFERRERS:
            rec["referrers"].append(source)
        folded += 1

    # Roll days that have aged out of the window into the frozen totals, for
    # EVERY item (not just ones touched this run — an item that stops getting
    # clicks must still age its old days out, or `days` never shrinks).
    for rec in items.values():
        days = rec.get("days", {})
        for stale_key in [k for k in days if k < cutoff]:
            stale = days.pop(stale_key)
            rec["clicks_total"] = rec.get("clicks_total", 0) + stale.get("clicks", 0)
            rec["sessions_total"] = rec.get("sessions_total", 0) + stale.get("sessions", 0)
    return folded


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    docs = repo_root / "docs"
    tags = load_json(docs / "data" / "tags.json", {"items": {}}).get("items", {})
    clicks = load_json(docs / "data" / "clicks.json", {"_schema_version": 1, "items": {}})

    try:
        token = get_token()
        total = total_select_result_count(token)
        rows = id_breakdown(token)
    except GA4Error as exc:
        print(f"pull_clicks: GA4 call failed, leaving clicks.json untouched: {exc}")
        return 0  # never fail the CI job over an analytics pull

    if total > 0 and not rows:
        print(f"pull_clicks: {total} select_result events this window, "
              "id breakdown not processed yet (BREAKDOWN_PENDING) — will retry next run.")
        return 0

    folded = fold_clicks(clicks, tags, rows)
    (docs / "data").mkdir(parents=True, exist_ok=True)
    (docs / "data" / "clicks.json").write_text(
        json.dumps(clicks, indent=2, allow_nan=False))
    print(f"pull_clicks: folded {folded} (item, day) cells "
          f"({len(clicks.get('items', {}))} items tracked total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
