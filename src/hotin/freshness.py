"""The single definition of "fresh": pure policy shared by board, newsletter,
and video publisher.

No I/O, no network, no clock reads except an injectable `now`/`on_date`. A
repo/model/paper/news record is fresh when its *creation* date falls inside
a small per-kind age window, anchored to PT noon of the reference date.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Optional

SCHEMA_VERSION = 2
POLICY_VERSION = 2
REPO_MAX_AGE_DAYS = 7
MODEL_MAX_AGE_DAYS = 7
PAPER_MAX_AGE_DAYS = 7
NEWS_MAX_AGE_DAYS = 2
# An insider row answers "who is backing this", so the clock that matters is when the
# insider starred it, never when the repo was created: gating insiders on repo age empties
# the section outright (measured 2026-09-12 on the live board: 0 of 13 within 7 days,
# median repo age 52 days). Abe's call, same day.
INSIDER_MAX_AGE_DAYS = 7
MAX_APPEARANCES = 3
KINDS = ("repo", "model", "paper", "news", "insider")

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    """The nth <weekday> of a month (weekday: Monday=0 .. Sunday=6)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return date(year, month, 1 + offset + 7 * (nth - 1))


class _USPacific(tzinfo):
    """Pacific time computed from the US rule, for Pythons with no IANA database.

    hotin declares ZERO dependencies, so `tzdata` cannot be required; and slim
    Pythons (CI images, minimal containers, Windows) ship no system zoneinfo. A
    module-level ZoneInfo lookup therefore breaks `import hotin.board` outright on
    those machines -- which is exactly what 0.9.13/0.9.14 did. DST runs from the
    second Sunday in March to the first Sunday in November, 02:00 local.
    """

    def utcoffset(self, dt):
        return timedelta(hours=-7 if self._is_dst(dt) else -8)

    def dst(self, dt):
        return timedelta(hours=1) if self._is_dst(dt) else timedelta(0)

    def tzname(self, dt):
        return "PDT" if self._is_dst(dt) else "PST"

    @staticmethod
    def _is_dst(dt) -> bool:
        if dt is None:
            return False
        naive = dt.replace(tzinfo=None)
        start = datetime.combine(_nth_weekday(naive.year, 3, 6, 2), datetime.min.time()).replace(hour=2)
        end = datetime.combine(_nth_weekday(naive.year, 11, 6, 1), datetime.min.time()).replace(hour=2)
        return start <= naive < end


def _pacific() -> tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/Los_Angeles")
    except Exception:  # no IANA database on this machine
        return _USPacific()


_PT_ZONE = _pacific()


def policy() -> dict:
    return {
        "repo_max_age_days": REPO_MAX_AGE_DAYS,
        "model_max_age_days": MODEL_MAX_AGE_DAYS,
        "paper_max_age_days": PAPER_MAX_AGE_DAYS,
        "news_max_age_days": NEWS_MAX_AGE_DAYS,
        "insider_max_age_days": INSIDER_MAX_AGE_DAYS,
        "max_appearances": MAX_APPEARANCES,
    }


def window(kind: str) -> int:
    if kind == "repo":
        return REPO_MAX_AGE_DAYS
    if kind == "model":
        return MODEL_MAX_AGE_DAYS
    if kind == "paper":
        return PAPER_MAX_AGE_DAYS
    if kind == "news":
        return NEWS_MAX_AGE_DAYS
    if kind == "insider":
        return INSIDER_MAX_AGE_DAYS
    raise ValueError("unknown kind: {!r}".format(kind))


def entity_date(record: dict, kind: str) -> Optional[str]:
    if kind in ("repo", "model", "paper"):
        signal = record.get("signal")
        value = signal.get("created_at") if isinstance(signal, dict) else None
    elif kind == "news":
        meta = record.get("meta")
        value = meta.get("date") if isinstance(meta, dict) else None
    elif kind == "insider":
        # the star EVENT, not the repo's birthday; never fall back to created_at, which is
        # exactly what would let 52-day-old repos back into the section
        signal = record.get("signal")
        value = signal.get("most_recent_star_at") if isinstance(signal, dict) else None
    else:
        raise ValueError("unknown kind: {!r}".format(kind))
    return value if isinstance(value, str) and value else None


def _now() -> datetime:
    return datetime.now(_PT_ZONE)


def _anchor(on_date: date) -> datetime:
    """PT-noon anchor for on_date. Shared by production and tests."""
    return datetime(on_date.year, on_date.month, on_date.day, 12, tzinfo=_PT_ZONE)


def age_days(date_iso: Optional[str], on_date: Optional[date] = None) -> Optional[int]:
    match = _ISO_DATE_RE.match(date_iso) if isinstance(date_iso, str) else None
    if not match:
        return None
    try:
        created = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)),
                            tzinfo=timezone.utc)
    except ValueError:
        return None
    anchor_date = _now().date() if on_date is None else on_date
    anchor = _anchor(anchor_date)
    seconds = (anchor - created).total_seconds()
    return max(0, int(seconds // 86400))


def is_fresh(kind: str, date_iso: Optional[str], on_date: Optional[date] = None) -> bool:
    days = age_days(date_iso, on_date)
    return days is not None and days <= window(kind)
