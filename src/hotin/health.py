"""Source-result health reporting with a deliberately tiny exit contract."""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple


@dataclass
class SourceStatus:
    source: str
    status: Literal["ok", "empty", "error"]
    detail: Optional[str] = None
    items: int = 0


def summarize(statuses: List[SourceStatus], cache_has_data: bool = False) -> Tuple[int, str]:
    """Turn source outcomes into a process exit code and a concise message."""
    if cache_has_data or any(item.status == "ok" for item in statuses):
        return 0, "sources completed"
    # No cache and nothing succeeded. If anything actually errored, the run
    # failed to deliver and something is broken -> exit 1. (We cannot require
    # EVERY status to be an error: permanently-inert sources like the x stub
    # and unconfigured reddit/youtube are always "empty", so keying off
    # len(errors)==len(statuses) would make the failure signal unreachable.)
    errors = [item for item in statuses if item.status == "error"]
    if errors:
        detail = "; ".join(
            "{}: {}".format(item.source, item.detail or "failed") for item in errors
        )
        return 1, "no usable results; source errors: {}".format(detail)
    return 0, "no results from available sources"


# --- Scout health: record one row per source per refresh cycle, and report ---

# How many recorded cycles a scout needs before "it has never returned ok" is evidence of
# permanent inertness rather than one bad run.
INERT_MIN_CYCLES = 5
# whether each has EVER returned "ok" (inert sources like the x stub or
# unconfigured reddit/youtube never have, and must never count as healthy).
#
# Reuses the cache's existing generic observation store (record_observations /
# recent_observations) instead of inventing a second persistence mechanism:
# entity_type distinguishes these rows from real board data, `metric` carries
# the status string, and `value` carries the item count.
SCOUT_ENTITY_TYPE = "scout_health"
# ponytail: fixed window, not configurable — raise if a source's flap cadence
# outgrows 10 cycles.
SCOUT_HISTORY_WINDOW = 10


def scout_observations(statuses: List[SourceStatus], run_id: str, observed_at: float) -> List[Dict[str, Any]]:
    """Turn one refresh cycle's statuses into rows for `cache.record_observations`."""
    return [
        {
            "run_id": run_id,
            "entity_type": SCOUT_ENTITY_TYPE,
            "entity_id": status.source,
            "source": status.source,
            "metric": status.status,
            "value": float(status.items),
            "observed_at": observed_at,
        }
        for status in statuses
    ]


@dataclass
class ScoutRecord:
    source: str
    latest_status: str
    latest_items: int
    latest_observed_at: float
    ok_in_window: int
    cycles_in_window: int
    inert: bool
    cycles_recorded: int = 0


def scout_history(cache: Any, window: int = SCOUT_HISTORY_WINDOW) -> List[ScoutRecord]:
    """Read every recorded scout cycle back and reduce it to one record per source."""
    rows = [row for row in cache.recent_observations(0.0) if row.get("entity_type") == SCOUT_ENTITY_TYPE]
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row)
    records: List[ScoutRecord] = []
    for source, source_rows in by_source.items():
        source_rows.sort(key=lambda row: row["observed_at"], reverse=True)
        latest = source_rows[0]
        windowed = source_rows[:window]
        records.append(ScoutRecord(
            source=source,
            latest_status=latest["metric"],
            latest_items=int(latest["value"]),
            latest_observed_at=latest["observed_at"],
            ok_in_window=sum(1 for row in windowed if row["metric"] == "ok"),
            cycles_in_window=len(windowed),
            # "never returned ok" only means something once there is enough history to say
            # it. After a single cycle it would brand any scout that merely had a bad run as
            # permanently inert -- verified live 2026-09-13, where one real refresh labelled
            # insiders, smartmoney and trends "inert" when they had simply errored or come back
            # empty that once. Below the threshold a scout is UNKNOWN, never inert, and never
            # counted as healthy either.
            inert=(len(source_rows) >= INERT_MIN_CYCLES
                   and not any(row["metric"] == "ok" for row in source_rows)),
            cycles_recorded=len(source_rows),
        ))
    records.sort(key=lambda record: record.source)
    return records


def scout_summary_line(records: List[ScoutRecord], checked_label: str) -> str:
    """The one line `hotin brief` prints. Silence is not trustworthy; this is."""
    if not records:
        return "scouts: no history recorded yet"
    inert = [r for r in records if r.inert]
    unknown = [r for r in records
               if not r.inert and r.cycles_recorded < INERT_MIN_CYCLES and r.latest_status != "ok"]
    live = [r for r in records if r not in inert and r not in unknown]
    ok_count = sum(1 for r in live if r.latest_status == "ok")
    line = "scouts: {}/{} live ok".format(ok_count, len(live))
    if unknown:
        # not yet enough history to judge; say so rather than quietly counting them either way
        line += " · {} unproven ({})".format(len(unknown), ", ".join(r.source for r in unknown))
    if inert:
        line += " · {} inert ({})".format(len(inert), ", ".join(r.source for r in inert))
    line += " · checked {}".format(checked_label)
    return line
