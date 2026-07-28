"""Batching, bisection, the budget floor, and drift visibility (L4/L5).

The parser is tested in test_roster_graphql.py. This file tests the loop around
it: what happens when a batch is too heavy, when the pool runs low, and whether
an operator can tell that the roster is quietly eroding.
"""

import io
import json
import re

import pytest

from hotin.sources import _insider_roster as core
from hotin.sources import _roster_graphql as G


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(core._THROTTLE, "wait", lambda: None)
    monkeypatch.setattr(core._THROTTLE, "wait_for_retry_after", lambda *a, **k: None)
    core._reset_memo()
    core._RATE_LIMIT_SEEN.clear()


class _Resp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _logins(request):
    return re.findall(r'user\(login: "([^"]+)"\)',
                      json.loads(request.data.decode())["query"])


def _ok_payload(logins, remaining=4999):
    data = {"u{}".format(i): {"login": u, "starredRepositories": {
        "pageInfo": {"hasNextPage": False}, "edges": []}}
        for i, u in enumerate(logins)}
    data["rateLimit"] = {"cost": 1, "remaining": remaining}
    return _Resp(json.dumps({"data": data}).encode())


def _roster_of(n):
    return tuple("user{}".format(i) for i in range(n))


def _poll(n, fake, monkeypatch, **kw):
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)
    monkeypatch.setattr(core, "_roster", lambda config: _roster_of(n))
    return core.poll_roster(config={"GITHUB_TOKEN": "t"}, **kw)


# --- batching -------------------------------------------------------------

def test_the_roster_is_split_into_batches_not_one_request_per_account(monkeypatch):
    seen = []

    def fake(request, timeout=None):
        logins = _logins(request)
        seen.append(len(logins))
        return _ok_payload(logins)

    _poll(60, fake, monkeypatch)
    # 60 accounts at 25/batch = 3 requests, not 60
    assert len(seen) == 3
    assert seen == [25, 25, 10]


def test_every_account_is_accounted_for_exactly_once(monkeypatch):
    seen = []

    def fake(request, timeout=None):
        logins = _logins(request)
        seen.extend(logins)
        return _ok_payload(logins)

    _poll(53, fake, monkeypatch)
    assert sorted(seen) == sorted(_roster_of(53))
    assert core.LAST_OUTCOMES.get(G.OK) == 53


# --- bisection on a too-heavy batch ---------------------------------------

def test_a_too_heavy_batch_is_halved_not_abandoned(monkeypatch):
    """502 means 'shrink', not 'the run is over'."""
    sizes = []

    def fake(request, timeout=None):
        logins = _logins(request)
        sizes.append(len(logins))
        if len(logins) > 10:
            raise core.urllib.error.HTTPError(
                request.full_url, 502, "bad gateway", {}, None)
        return _ok_payload(logins)

    _poll(25, fake, monkeypatch)
    assert sizes[0] == 25, "first attempt uses the full batch"
    assert any(s <= 13 for s in sizes), "it halved"
    assert core.LAST_OUTCOMES.get(G.OK) == 25, "everyone still resolved"


def test_resource_limits_also_triggers_a_shrink(monkeypatch):
    """The measured corruption mode is a shrink signal, not a failure."""
    sizes = []

    def fake(request, timeout=None):
        logins = _logins(request)
        sizes.append(len(logins))
        if len(logins) > 8:
            data = {"u{}".format(i): {"login": u, "starredRepositories": {
                "pageInfo": {"hasNextPage": False}, "edges": [None]}}
                for i, u in enumerate(logins)}
            data["rateLimit"] = {"cost": 1, "remaining": 4999}
            return _Resp(json.dumps({"data": data, "errors": [
                {"type": "RESOURCE_LIMITS_EXCEEDED",
                 "path": ["u0", "starredRepositories", "edges", 0, "starredAt"]}]}).encode())
        return _ok_payload(logins)

    _poll(16, fake, monkeypatch)
    assert sizes[0] == 16
    assert min(sizes) <= 8
    assert core.LAST_OUTCOMES.get(G.OK) == 16


def test_bisection_bottoms_out_in_rest_rather_than_looping(monkeypatch):
    """At the floor, the REST poller takes over: per-account isolation."""
    rest_calls = []

    def always_heavy(request, timeout=None):
        raise core.urllib.error.HTTPError(request.full_url, 502, "x", {}, None)

    def fake_rest(username, token, *, window_days, now):
        rest_calls.append(username)
        return [], core._OK

    monkeypatch.setattr(core, "_poll_one", fake_rest)
    _poll(8, always_heavy, monkeypatch)
    assert sorted(rest_calls) == sorted(_roster_of(8)), \
        "every account should reach the REST backstop"
    assert core.LAST_OUTCOMES.get(G.OK) == 8


def test_a_401_aborts_the_batch_without_bisecting(monkeypatch):
    """One token serves everyone; halving cannot fix a revoked credential."""
    attempts = []

    def unauthorized(request, timeout=None):
        attempts.append(1)
        raise core.urllib.error.HTTPError(request.full_url, 401, "bad", {}, None)

    monkeypatch.setattr(core.urllib.request, "urlopen", unauthorized)
    monkeypatch.setattr(core, "_roster", lambda config: _roster_of(25))
    with pytest.raises(core.RosterAuthError):
        core.poll_roster(config={"GITHUB_TOKEN": "revoked"})
    assert len(attempts) == 1, "must not bisect a credential failure"


def test_http_403_is_rate_limited_not_a_shrink_signal(monkeypatch):
    """Bisecting while over quota spends more budget to learn the same thing."""
    attempts = []

    def limited(request, timeout=None):
        attempts.append(1)
        raise core.urllib.error.HTTPError(request.full_url, 403, "rate", {}, None)

    monkeypatch.setattr(core.urllib.request, "urlopen", limited)
    monkeypatch.setattr(core, "_roster", lambda config: _roster_of(25))
    with pytest.raises(core.RosterRateLimitError):
        core.poll_roster(config={"GITHUB_TOKEN": "t"})
    assert len(attempts) == 1


# --- the budget floor (L4) ------------------------------------------------

def test_running_low_marks_the_remainder_rate_limited_not_skipped(monkeypatch):
    """Skipping would make 'not looked at' identical to 'starred nothing'."""
    def fake(request, timeout=None):
        logins = _logins(request)
        # first response reports a nearly-exhausted pool
        return _ok_payload(logins, remaining=G.POINTS_FLOOR - 1)

    # 40 accounts: 25 polled, 15 cut off = 37.5%, under the 50% tolerance, so
    # this degrades rather than raising.
    _poll(40, fake, monkeypatch)
    tally = core.LAST_OUTCOMES
    assert tally.get(G.OK) == 25, "the first batch completed"
    assert tally.get(G.RATE_LIMITED) == 15, "the rest are explicitly marked"
    assert sum(tally.values()) == 40, "every account has an outcome"


def test_the_floor_and_the_tolerance_guard_compose(monkeypatch):
    """Cut off past half the cohort and the run must refuse to publish.

    The floor writes honest rate_limited rows; the existing >50% guard then
    turns that honesty into a refusal. Neither works alone: without the floor
    the rows would be missing, and without the guard a third of a board would
    publish as if whole.
    """
    def fake(request, timeout=None):
        return _ok_payload(_logins(request), remaining=G.POINTS_FLOOR - 1)

    monkeypatch.setattr(core.urllib.request, "urlopen", fake)
    monkeypatch.setattr(core, "_roster", lambda config: _roster_of(75))
    with pytest.raises(core.RosterRateLimitError):
        core.poll_roster(config={"GITHUB_TOKEN": "t"})


def test_a_healthy_budget_does_not_stop_the_run(monkeypatch):
    def fake(request, timeout=None):
        return _ok_payload(_logins(request), remaining=4000)

    _poll(75, fake, monkeypatch)
    assert core.LAST_OUTCOMES.get(G.OK) == 75


def test_an_absent_rate_limit_block_is_not_treated_as_exhaustion(monkeypatch):
    """Missing != zero. Reading absence as empty would halt every run."""
    def fake(request, timeout=None):
        logins = _logins(request)
        data = {"u{}".format(i): {"login": u, "starredRepositories": {
            "pageInfo": {"hasNextPage": False}, "edges": []}}
            for i, u in enumerate(logins)}
        return _Resp(json.dumps({"data": data}).encode())

    _poll(75, fake, monkeypatch)
    assert core.LAST_OUTCOMES.get(G.OK) == 75


# --- truncation falls back to REST (L3, at the loop level) ----------------

def test_a_truncated_account_is_re_polled_over_rest(monkeypatch):
    rest_calls = []

    def fake(request, timeout=None):
        logins = _logins(request)
        data = {}
        for i, u in enumerate(logins):
            data["u{}".format(i)] = {"login": u, "starredRepositories": {
                "pageInfo": {"hasNextPage": True},
                "edges": [{"starredAt": "2026-07-27T00:00:00Z", "node": {
                    "nameWithOwner": "a/b", "createdAt": "2026-07-01T00:00:00Z",
                    "stargazerCount": 1, "description": None}}]}}
        data["rateLimit"] = {"cost": 1, "remaining": 4999}
        return _Resp(json.dumps({"data": data}).encode())

    def fake_rest(username, token, *, window_days, now):
        rest_calls.append(username)
        return [{"username": username, "canonical_repo": "from/rest",
                 "starred_at": "2026-07-27T00:00:00Z", "repo_created_at": None,
                 "stargazers_count": 0, "description": None}], core._OK

    monkeypatch.setattr(core, "_poll_one", fake_rest)
    events = _poll(3, fake, monkeypatch)
    assert sorted(rest_calls) == sorted(_roster_of(3))
    assert all(e["canonical_repo"] == "from/rest" for e in events)


# --- drift visibility (L5) ------------------------------------------------

def test_the_summary_names_every_outcome_that_occurred():
    line = core.summarize_outcomes(
        {G.OK: 700, G.NOT_FOUND: 12, G.MISMATCH: 1, G.UNRESOLVED: 80}, 793)
    assert "700/793" in line
    for token in ("ok=700", "not_found=12", "mismatch=1", "unresolved=80"):
        assert token in line


def test_the_summary_hides_outcomes_that_did_not_happen():
    line = core.summarize_outcomes({G.OK: 793}, 793)
    assert "ok=793" in line
    assert "mismatch" not in line and "unresolved" not in line


def test_the_summary_survives_an_empty_tally():
    assert "nothing" in core.summarize_outcomes({}, 0)


def test_the_tally_is_published_after_a_poll(monkeypatch):
    """Aggregate erosion is invisible unless each run publishes its counts."""
    def fake(request, timeout=None):
        logins = _logins(request)
        data = {"u0": None}
        for i, u in enumerate(logins[1:], start=1):
            data["u{}".format(i)] = {"login": u, "starredRepositories": {
                "pageInfo": {"hasNextPage": False}, "edges": []}}
        data["rateLimit"] = {"cost": 1, "remaining": 4999}
        return _Resp(json.dumps({"data": data, "errors": [
            {"type": "NOT_FOUND", "path": ["u0"]}]}).encode())

    _poll(5, fake, monkeypatch)
    assert core.LAST_OUTCOMES.get(G.NOT_FOUND) == 1
    assert core.LAST_OUTCOMES.get(G.OK) == 4
    assert "not_found=1" in core.summarize_outcomes(core.LAST_OUTCOMES, 5)


def test_rest_fallbacks_are_counted_so_the_gain_can_be_watched(monkeypatch):
    """If most accounts route back to REST, the migration stopped paying.

    No single account is at fault when that happens, so it is invisible without
    a counter. This is the early-warning signal for the whole change.
    """
    def truncating(request, timeout=None):
        logins = _logins(request)
        data = {}
        for i, u in enumerate(logins):
            data["u{}".format(i)] = {"login": u, "starredRepositories": {
                "pageInfo": {"hasNextPage": True},
                "edges": [{"starredAt": "2026-07-27T00:00:00Z", "node": {
                    "nameWithOwner": "a/b", "createdAt": "2026-07-01T00:00:00Z",
                    "stargazerCount": 1, "description": None}}]}}
        data["rateLimit"] = {"cost": 1, "remaining": 4999}
        return _Resp(json.dumps({"data": data}).encode())

    monkeypatch.setattr(core, "_poll_one",
                        lambda username, token, **kw: ([], core._OK))
    _poll(5, truncating, monkeypatch)
    assert core.LAST_OUTCOMES.get("rest_fallback") == 5
    assert "rest_fallback=5" in core.summarize_outcomes(core.LAST_OUTCOMES, 5)


def test_a_clean_run_reports_no_fallbacks(monkeypatch):
    _poll(10, lambda r, timeout=None: _ok_payload(_logins(r)), monkeypatch)
    assert "rest_fallback" not in core.summarize_outcomes(core.LAST_OUTCOMES, 10)
