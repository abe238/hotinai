"""hotin declares zero dependencies, so it must work on a Python with no IANA database.

0.9.13 put `ZoneInfo("America/Los_Angeles")` at module scope in freshness.py, which
board.py imports, which nearly every module imports. On a slim Python (the CI image, a
minimal container, Windows) that raises at IMPORT time, so `import hotin.board` -- and the
whole CLI -- died. It passed locally only because macOS ships a system zoneinfo. This file
pins the fallback so the regression cannot come back.
"""

import builtins
import importlib
from datetime import date, datetime, timedelta

import pytest

from hotin import freshness


def _reload_without_zoneinfo(monkeypatch):
    """Re-import freshness with `zoneinfo` unavailable, as on a machine with no tzdata."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "zoneinfo":
            raise ModuleNotFoundError("No module named 'zoneinfo'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    return importlib.reload(freshness)


def test_module_imports_and_works_with_no_iana_database(monkeypatch):
    mod = _reload_without_zoneinfo(monkeypatch)
    try:
        assert isinstance(mod._PT_ZONE, mod._USPacific)
        # the whole point: the policy still answers correctly
        assert mod.is_fresh("repo", "2026-09-09T00:00:00Z", date(2026, 9, 12)) is True
        assert mod.is_fresh("repo", "2026-06-22T00:00:00Z", date(2026, 9, 12)) is False
        assert mod.age_days("2026-09-05T00:00:00Z", date(2026, 9, 12)) == 7
    finally:
        importlib.reload(freshness)


def test_fallback_tracks_daylight_saving_not_a_fixed_offset(monkeypatch):
    mod = _reload_without_zoneinfo(monkeypatch)
    try:
        assert mod._anchor(date(2026, 8, 20)).utcoffset() == timedelta(hours=-7)   # PDT
        assert mod._anchor(date(2026, 1, 20)).utcoffset() == timedelta(hours=-8)   # PST
    finally:
        importlib.reload(freshness)


@pytest.mark.parametrize("day", [
    date(2026, 3, 7), date(2026, 3, 8), date(2026, 3, 9),      # around DST start
    date(2026, 11, 1), date(2026, 11, 2),                       # around DST end
    date(2026, 6, 15), date(2026, 12, 15),                      # mid-season
])
def test_fallback_agrees_with_zoneinfo_on_the_real_answer(monkeypatch, day):
    """The fallback is only worth having if it gives the SAME age as the real database."""
    real = freshness.age_days("2026-01-01T00:00:00Z", day)
    mod = _reload_without_zoneinfo(monkeypatch)
    try:
        assert mod.age_days("2026-01-01T00:00:00Z", day) == real
    finally:
        importlib.reload(freshness)


def test_nth_weekday_picks_the_right_sundays():
    assert freshness._nth_weekday(2026, 3, 6, 2) == date(2026, 3, 8)    # 2nd Sunday in March
    assert freshness._nth_weekday(2026, 11, 6, 1) == date(2026, 11, 1)  # 1st Sunday in November
