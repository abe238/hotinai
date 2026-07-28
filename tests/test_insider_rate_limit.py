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



# --- GraphQL transport fakes ------------------------------------------------
# The poll batches accounts into ONE GraphQL request now, so a fake must answer
# per BATCH, not per user. These helpers read the logins back out of the query
# so each test can keep expressing itself in per-account terms -- the incidents
# these tests pin are about aggregation, and must hold on whatever transport is
# underneath.

import io
import json as _json
import re as _re


def _logins_in(request):
    body = _json.loads(request.data.decode())["query"]
    return _re.findall(r'user\(login: "([^"]+)"\)', body)


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _graphql(outcome_of):
    """Fake urlopen answering a batch. ``outcome_of(login)`` -> one of
    'ok' | 'rate_limited' | 'not_found'."""
    def fake(request, timeout=None):
        logins = _logins_in(request)
        data, errors = {}, []
        for i, login in enumerate(logins):
            state = outcome_of(login)
            if state == "rate_limited":
                data["u{}".format(i)] = None
                errors.append({"type": "RATE_LIMITED", "path": ["u{}".format(i)]})
            elif state == "not_found":
                data["u{}".format(i)] = None
                errors.append({"type": "NOT_FOUND", "path": ["u{}".format(i)]})
            else:
                data["u{}".format(i)] = {"login": login, "starredRepositories": {
                    "pageInfo": {"hasNextPage": False}, "edges": []}}
        data["rateLimit"] = {"cost": 1, "remaining": 4999}
        payload = {"data": data}
        if errors:
            payload["errors"] = errors
        return _Resp(_json.dumps(payload).encode())
    return fake


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
    monkeypatch.setattr(core.urllib.request, "urlopen", _graphql(
        lambda who: "rate_limited" if who in limited else "not_found"))
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

    monkeypatch.setattr(core.urllib.request, "urlopen", _graphql(
        lambda who: "rate_limited" if who in limited else "not_found"))
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


def test_partial_limiting_below_the_threshold_still_publishes(monkeypatch):
    # 30% limited: degraded, but still the majority of the cohort. This must NOT
    # raise. The hard gate in CI already refuses a collapsed board, so a tight
    # threshold here would only trade a silent failure for a noisy one and block
    # healthy runs. The guard exists to name the cause of a real collapse.
    core._reset_memo()
    roster = _roster_of(100)
    limited = set(roster[:30])

    monkeypatch.setattr(core.urllib.request, "urlopen", _graphql(
        lambda who: "rate_limited" if who in limited else "not_found"))
    monkeypatch.setattr(core, "_roster", lambda config: roster)
    assert core.poll_roster(config={"GITHUB_TOKEN": "t"}) == []


def test_the_error_reports_githubs_own_quota(monkeypatch):
    # The threshold is not derived from an assumed hourly budget -- that number
    # could not be verified from outside CI. The poll reports what GitHub said.
    core._reset_memo()
    core._RATE_LIMIT_SEEN.clear()

    class Headers(dict):
        pass

    def limited(request, timeout=None):
        h = Headers({"X-RateLimit-Limit": "1000", "X-RateLimit-Remaining": "0"})
        raise urllib.error.HTTPError(request.full_url, 403, "rate", h, None)

    monkeypatch.setattr(core.urllib.request, "urlopen", limited)
    monkeypatch.setattr(core, "_roster", lambda config: _roster_of(50))
    with pytest.raises(core.RosterRateLimitError) as exc:
        core.poll_roster(config={"GITHUB_TOKEN": "t"})
    assert "limit=1000" in str(exc.value) and "remaining=0" in str(exc.value)
