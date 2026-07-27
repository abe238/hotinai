"""A rate-limited roster poll must be loud, not a small plausible board.

The failure this pins actually shipped. hotin.ai's CI authenticates with
``github.token`` (1,000 REST req/hour/repo) while one cycle polls the ~793
account roster twice, once in `refresh` and once in `export`. On the normal
3-hour cadence that fits. Two runs inside one hour does not, and the second run
produced 3 insider rows where the first produced 60 -- while every status line
read "insiders ok", because a 403 returned an empty list that was indis-
tinguishable from "this person starred nothing".

401 was loud from the start. 403/429 was not. That asymmetry cost three
misdiagnoses (a "cold store", a "cap-then-filter" bug, an "ordering" bug) before
anyone traced the actual data.
"""

import urllib.error

import pytest

from hotin.sources import _insider_roster as core
from hotin.sources import insiders, smartmoney


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """The real throttle paces 0.2s/request. At roster scale that is minutes of
    wall clock for tests that only care about counting outcomes."""
    monkeypatch.setattr(core._THROTTLE, "wait", lambda: None)
    monkeypatch.setattr(core._THROTTLE, "wait_for_retry_after", lambda *a, **k: None)


def _roster_of(n):
    return tuple("user{}".format(i) for i in range(n))


def _http(code):
    def raiser(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, code, "denied", {}, None)
    return raiser


@pytest.mark.parametrize("code", [403, 429])
def test_whole_roster_rate_limited_raises(monkeypatch, code):
    core._reset_memo()
    monkeypatch.setattr(core.urllib.request, "urlopen", _http(code))
    monkeypatch.setattr(core, "_roster", lambda config: _roster_of(50))
    with pytest.raises(core.RosterRateLimitError):
        core.poll_roster(config={"GITHUB_TOKEN": "t"})


def test_the_real_incident_shape(monkeypatch):
    # 790 of 793 rate-limited: the exact case that published 3 rows as if real.
    core._reset_memo()
    roster = _roster_of(793)
    limited = set(roster[:790])

    def selective(request, timeout=None):
        who = request.full_url.split("/users/")[1].split("/")[0]
        if who in limited:
            raise urllib.error.HTTPError(request.full_url, 403, "rate", {}, None)
        raise urllib.error.HTTPError(request.full_url, 404, "gone", {}, None)

    monkeypatch.setattr(core.urllib.request, "urlopen", selective)
    monkeypatch.setattr(core, "_roster", lambda config: roster)
    with pytest.raises(core.RosterRateLimitError) as exc:
        core.poll_roster(config={"GITHUB_TOKEN": "t"})
    assert "790 of 793" in str(exc.value)


def test_a_few_rate_limited_is_tolerated(monkeypatch):
    # Occasional 403s are ordinary. The guard is about whether the RESULT is
    # still trustworthy, not about whether anything went wrong at all.
    core._reset_memo()
    roster = _roster_of(100)
    limited = set(roster[:5])          # 5% -- under the 10% tolerance

    def selective(request, timeout=None):
        who = request.full_url.split("/users/")[1].split("/")[0]
        code = 403 if who in limited else 404
        raise urllib.error.HTTPError(request.full_url, code, "x", {}, None)

    monkeypatch.setattr(core.urllib.request, "urlopen", selective)
    monkeypatch.setattr(core, "_roster", lambda config: roster)
    assert core.poll_roster(config={"GITHUB_TOKEN": "t"}) == []


def test_404s_alone_never_trip_the_guard(monkeypatch):
    # Renamed/suspended/deleted accounts are expected and must stay silent, or
    # roster rot would page someone every cycle.
    core._reset_memo()
    monkeypatch.setattr(core.urllib.request, "urlopen", _http(404))
    monkeypatch.setattr(core, "_roster", lambda config: _roster_of(50))
    assert core.poll_roster(config={"GITHUB_TOKEN": "t"}) == []


@pytest.mark.parametrize("adapter", [insiders, smartmoney])
def test_adapters_report_error_not_empty(monkeypatch, adapter):
    # The board must see status "error" and refuse to publish, rather than an
    # "ok" with a handful of rows that looks like a real but quiet day.
    core._reset_memo()
    monkeypatch.setattr(core.urllib.request, "urlopen", _http(403))
    monkeypatch.setattr(core, "_roster", lambda config: _roster_of(50))
    result = adapter.fetch(limit=60, config={"GITHUB_TOKEN": "t"})
    assert result["status"] == "error", result
    assert result["records"] == []
    assert "rate-limited" in (result["detail"] or "")


def test_a_poisoned_poll_is_never_memoized(monkeypatch):
    # The memo is process-wide and shared by both adapters. Caching a truncated
    # poll would spread one rate-limited moment across the whole run.
    core._reset_memo()
    monkeypatch.setattr(core.urllib.request, "urlopen", _http(403))
    monkeypatch.setattr(core, "_roster", lambda config: _roster_of(50))
    with pytest.raises(core.RosterRateLimitError):
        core.poll_roster(config={"GITHUB_TOKEN": "t"})
    assert core._MEMO == {}
