"""Shared roster-polling core: memoization, resilience, windowing, and the
hard constraint that the RESTRICTED stargazers endpoint is never touched."""

import json
import urllib.error

import pytest

from hotin.sources import _insider_roster as core


class _Resp:
    def __init__(self, entries):
        self._body = json.dumps(entries).encode("utf-8")
        self.headers = {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False




# --- GraphQL transport fake -------------------------------------------------
# poll_roster batches accounts into ONE GraphQL request, so a fake answers per
# BATCH. The REST path is still live as the fallback and is tested directly
# against _poll_one further down.

import io as _io
import re as _re


class _GqlResp(_io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
    headers = {}


def _gql_fake(state_of):
    """``state_of(login)`` -> ('ok', [(repo, starred_at), ...]) | 'not_found'
    | 'forbidden'."""
    def fake(request, timeout=None):
        logins = _re.findall(r'user\(login: "([^"]+)"\)',
                             json.loads(request.data.decode())["query"])
        data, errors = {}, []
        for i, login in enumerate(logins):
            alias = "u{}".format(i)
            state = state_of(login)
            if state == "not_found":
                data[alias] = None
                errors.append({"type": "NOT_FOUND", "path": [alias]})
            elif state == "forbidden":
                data[alias] = None
                errors.append({"type": "FORBIDDEN", "path": [alias]})
            else:
                _, stars = state
                data[alias] = {"login": login, "starredRepositories": {
                    "pageInfo": {"hasNextPage": False},
                    "edges": [{"starredAt": at, "node": {
                        "nameWithOwner": repo, "createdAt": "2026-07-01T00:00:00Z",
                        "stargazerCount": 10, "description": None}}
                        for repo, at in stars]}}
        data["rateLimit"] = {"cost": 1, "remaining": 4999}
        payload = {"data": data}
        if errors:
            payload["errors"] = errors
        return _GqlResp(json.dumps(payload).encode())
    return fake


def _entry(repo, starred_at, stars=10, desc=None):
    return {"starred_at": starred_at,
            "repo": {"full_name": repo, "stargazers_count": stars, "description": desc}}


def test_missing_token_raises_loudly():
    core._reset_memo()
    with pytest.raises(core.MissingTokenError):
        core.poll_roster(config={})


def test_poll_is_memoized_per_process(monkeypatch):
    core._reset_memo()
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        # The poll batches, so the count is per REQUEST, not per user. What is
        # pinned here is that a second poll_roster costs ZERO further requests.
        return _GqlResp(json.dumps({"data": {"rateLimit": {"remaining": 4999}}}).encode())

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(core, "_roster", lambda config: ("alice", "bob"))
    cfg = {"GITHUB_TOKEN": "x"}
    first = core.poll_roster(config=cfg)
    n_after_first = calls["n"]
    second = core.poll_roster(config=cfg)          # same key -> served from memo
    assert second is first                          # identical object, no re-poll
    # ONE request for both users: the poll batches now, so the count is per
    # request, not per account. That is the migration's whole point, and the
    # memo property is that a second poll_roster adds nothing to it.
    assert n_after_first == 1
    assert calls["n"] == n_after_first


def test_a_bad_user_does_not_crash_the_whole_poll(monkeypatch):
    core._reset_memo()

    monkeypatch.setattr(core.urllib.request, "urlopen", _gql_fake(
        lambda who: "not_found" if who == "gone"
        else ("ok", [("real/repo", "2026-07-25T00:00:00Z")])))
    monkeypatch.setattr(core, "_roster", lambda config: ("gone", "good"))
    events = core.poll_roster(config={"GITHUB_TOKEN": "x"},
                              now=__import__("datetime").datetime(2026, 7, 26,
                                  tzinfo=__import__("datetime").timezone.utc))
    # the 404 user contributes nothing; the good user's star still lands
    assert [e["username"] for e in events] == ["good"]
    assert events[0]["canonical_repo"] == "real/repo"


def test_all_users_401_is_a_loud_error_not_silent_empty(monkeypatch):
    # Regression: a revoked/expired token 401s every request. That must raise
    # RosterAuthError (which the adapters surface as status "error"), NOT return
    # an empty list that reads like "nobody starred anything".
    core._reset_memo()

    def always_401(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Bad creds", {}, None)

    monkeypatch.setattr(core.urllib.request, "urlopen", always_401)
    monkeypatch.setattr(core, "_roster", lambda config: ("alice", "bob"))
    with pytest.raises(core.RosterAuthError):
        core.poll_roster(config={"GITHUB_TOKEN": "revoked"})


def test_one_user_401_among_many_is_tolerated(monkeypatch):
    # A single 401 (odd, but possible) must NOT trip the all-failed guard.
    core._reset_memo()
    import datetime as dt
    now = dt.datetime(2026, 7, 26, tzinfo=dt.timezone.utc)

    # Per-account auth failure is FORBIDDEN in GraphQL; a transport 401 is
    # all-or-nothing and is covered by the all-401 test above.
    mixed = _gql_fake(lambda who: "forbidden" if who == "alice"
                      else ("ok", [("good/repo", "2026-07-25T00:00:00Z")]))

    monkeypatch.setattr(core.urllib.request, "urlopen", mixed)
    monkeypatch.setattr(core, "_roster", lambda config: ("alice", "bob"))
    events = core.poll_roster(config={"GITHUB_TOKEN": "x"}, now=now)
    assert [e["username"] for e in events] == ["bob"]  # no raise; bob's star lands


def test_http_date_retry_after_does_not_crash_the_poll(monkeypatch):
    # Retry-After may be an HTTP-date, not seconds. float() on it would raise and,
    # unguarded, escape the whole poll. It must be ignored, not fatal.
    core._reset_memo()
    import datetime as dt
    now = dt.datetime(2026, 7, 26, tzinfo=dt.timezone.utc)

    class _RespWithDateRetry(_Resp):
        def __init__(self, entries):
            super().__init__(entries)
            self.headers = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}

    monkeypatch.setattr(core.urllib.request, "urlopen",
                        lambda request, timeout=None: _RespWithDateRetry(
                            [_entry("ok/repo", "2026-07-25T00:00:00Z")]))
    # Retry-After lives on the REST fallback path, so exercise _poll_one directly.
    events, outcome = core._poll_one("solo", "x", window_days=30, now=now)
    assert outcome == core._OK
    assert events[0]["canonical_repo"] == "ok/repo"


def test_default_window_is_30_days(monkeypatch):
    # Pinned deliberately. 7 days sampled almost nobody (4.5% of the cohort
    # active, one account = 43% of the signal); 30 days more than doubled
    # participation and diluted that concentration to 30%. Narrowing this again
    # should be a conscious decision with fresh numbers, not a drive-by edit.
    core._reset_memo()
    seen = {}

    def spy(request, timeout=None):
        return _GqlResp(json.dumps({"data": {"rateLimit": {"remaining": 4999}}}).encode())

    monkeypatch.setattr(core.urllib.request, "urlopen", spy)
    monkeypatch.setattr(core, "_roster", lambda config: ("solo",))
    real_parse = core._gql.parse_batch

    def capture(payload, requested, *, window_days, now=None, fresh_fn=None):
        seen["window_days"] = window_days
        return real_parse(payload, requested, window_days=window_days,
                          now=now, fresh_fn=fresh_fn)

    monkeypatch.setattr(core._gql, "parse_batch", capture)
    core.poll_roster(config={"GITHUB_TOKEN": "x"})
    assert seen["window_days"] == 30


def test_pagination_stops_at_the_window_edge(monkeypatch):
    core._reset_memo()
    import datetime as dt
    now = dt.datetime(2026, 7, 26, tzinfo=dt.timezone.utc)
    # descending by starred_at: one in-window, then one out-of-window -> stop
    page = [
        _entry("in/window", "2026-07-25T00:00:00Z"),
        _entry("too/old", "2026-01-01T00:00:00Z"),
    ]
    monkeypatch.setattr(core.urllib.request, "urlopen",
                        lambda request, timeout=None: _Resp(page))
    # REST pagination is the FALLBACK path now (truncated in-window pages and
    # the bisection floor route to it), so test it where it lives.
    events, outcome = core._poll_one("solo", "x", window_days=7, now=now)
    assert outcome == core._OK
    assert [e["canonical_repo"] for e in events] == ["in/window"]  # old one dropped


def test_never_constructs_the_restricted_stargazers_url(monkeypatch):
    # THE load-bearing constraint: GitHub restricted /repos/{o}/{r}/stargazers to
    # admins/collaborators (2026-06-30). This core must ONLY use the forward
    # direction (/users/{u}/starred). Fail loudly if a stargazers URL is ever built.
    core._reset_memo()
    seen_urls = []

    def spy_urlopen(request, timeout=None):
        seen_urls.append(request.full_url)
        return _Resp([])

    bodies = []

    def spy_body(request, timeout=None):
        seen_urls.append(request.full_url)
        if request.data:
            bodies.append(request.data.decode())
        return _Resp([])

    monkeypatch.setattr(core.urllib.request, "urlopen", spy_body)
    monkeypatch.setattr(core, "_roster", lambda config: ("alice", "bob"))
    core.poll_roster(config={"GITHUB_TOKEN": "x"})
    assert seen_urls, "expected at least one request"
    for url in seen_urls:
        assert "/stargazers" not in url, "must never hit the restricted endpoint: " + url
        # The primary path is now the GraphQL endpoint; REST /users/{u}/starred
        # survives as the fallback. Both are the FORWARD direction.
        assert url.endswith("/graphql") or ("/users/" in url and "/starred" in url), url
    # Same constraint at the query level: the restricted REVERSE lookup is the
    # `stargazers` connection on a Repository. `stargazerCount` is a scalar and
    # is fine; requesting `stargazers(` would not be.
    for body in bodies:
        assert "stargazers(" not in body, "must never request the reverse lookup"
        assert "starredRepositories(" in body, "must use the forward direction"


def test_roster_override_parses_a_literal_list(monkeypatch):
    core._reset_memo()
    roster = core._roster({"HOTIN_INSIDER_ROSTER_PATH": "alice, bob\ncarol"})
    assert roster == ("alice", "bob", "carol")


def test_roster_override_from_a_file_strips_comments(tmp_path):
    # Regression: a roster FILE normally has a header. Splitting on whitespace
    # before stripping '#' comments turned every comment word into a handle
    # (this produced 26 phantom entries against the real private roster).
    core._reset_memo()
    f = tmp_path / "roster.txt"
    f.write_text(
        "# hotin insider roster -- PRIVATE, do not publish\n"
        "# consumed via HOTIN_INSIDER_ROSTER_PATH\n"
        "alice\n"
        "bob   # trailing comment on a real entry\n"
        "carol\n"
    )
    roster = core._roster({"HOTIN_INSIDER_ROSTER_PATH": str(f)})
    assert roster == ("alice", "bob", "carol"), roster
    assert not any(h.startswith("#") for h in roster)
    assert "PRIVATE" not in roster and "hotin" not in roster


def test_seed_roster_is_used_when_no_override():
    assert core._roster({}) == core.SEED_ROSTER
    assert len(core.SEED_ROSTER) >= 20  # a real starting set, not a 5-name stub


def test_no_weights_means_weight_equals_starrer_count():
    # Back-compat pin: absent a weights table, nothing changes -- weight is the
    # plain count and ordering is the old count-ordering.
    events = [
        {"username": "a", "canonical_repo": "two/starrers", "starred_at": "2026-07-25T00:00:00Z"},
        {"username": "b", "canonical_repo": "two/starrers", "starred_at": "2026-07-25T00:00:00Z"},
        {"username": "a", "canonical_repo": "one/starrer", "starred_at": "2026-07-25T00:00:00Z"},
    ]
    aggs = core.aggregate_by_repo(events)
    assert [a["canonical_repo"] for a in aggs] == ["two/starrers", "one/starrer"]
    assert aggs[0]["weight"] == 2.0 and aggs[1]["weight"] == 1.0


def test_weights_can_outrank_raw_starrer_count():
    # The point of weighting: one heavily-weighted account should be able to beat
    # two lightly-weighted ones, otherwise the table is decorative.
    events = [
        {"username": "nobody1", "canonical_repo": "many/light", "starred_at": "2026-07-25T00:00:00Z"},
        {"username": "nobody2", "canonical_repo": "many/light", "starred_at": "2026-07-25T00:00:00Z"},
        {"username": "heavyweight", "canonical_repo": "one/heavy", "starred_at": "2026-07-25T00:00:00Z"},
    ]
    weights = {"heavyweight": 8.0, "nobody1": 1.0, "nobody2": 1.0}
    aggs = core.aggregate_by_repo(events, weights, 1.0)
    assert aggs[0]["canonical_repo"] == "one/heavy", [a["canonical_repo"] for a in aggs]
    assert aggs[0]["weight"] == 8.0 and aggs[1]["weight"] == 2.0


def test_unlisted_members_get_the_default_weight():
    events = [{"username": "unlisted", "canonical_repo": "x/y", "starred_at": "2026-07-25T00:00:00Z"}]
    assert core.aggregate_by_repo(events, {"someone": 5.0}, 2.5)[0]["weight"] == 2.5


def test_load_weights_accepts_both_shapes_and_survives_junk(tmp_path):
    nested = tmp_path / "n.json"
    nested.write_text('{"default": 3.0, "weights": {"Alice": 7.5}}')
    w, d = core.load_weights({"HOTIN_INSIDER_WEIGHTS_PATH": str(nested)})
    assert w == {"alice": 7.5} and d == 3.0          # handles are case-folded

    flat = tmp_path / "f.json"
    flat.write_text('{"bob": 2}')
    w, d = core.load_weights({"HOTIN_INSIDER_WEIGHTS_PATH": str(flat)})
    assert w == {"bob": 2.0} and d == 1.0

    bad = tmp_path / "bad.json"
    bad.write_text("not json at all")
    assert core.load_weights({"HOTIN_INSIDER_WEIGHTS_PATH": str(bad)}) == ({}, 1.0)
    assert core.load_weights({}) == ({}, 1.0)
    assert core.load_weights({"HOTIN_INSIDER_WEIGHTS_PATH": "/no/such/file"}) == ({}, 1.0)


def test_aggregate_dedupes_and_ranks():
    events = [
        {"username": "a", "canonical_repo": "shared/repo",
         "starred_at": "2026-07-24T00:00:00Z", "stargazers_count": 5, "description": "d"},
        {"username": "b", "canonical_repo": "shared/repo",
         "starred_at": "2026-07-25T00:00:00Z", "stargazers_count": 9, "description": None},
        {"username": "a", "canonical_repo": "solo/repo",
         "starred_at": "2026-07-20T00:00:00Z", "stargazers_count": 1, "description": None},
    ]
    aggs = core.aggregate_by_repo(events)
    assert [a["canonical_repo"] for a in aggs] == ["shared/repo", "solo/repo"]  # 2 starrers first
    shared = aggs[0]
    assert shared["starrers"] == ["a", "b"]
    assert shared["most_recent_star_at"] == "2026-07-25T00:00:00Z"
    assert shared["stargazers_count"] == 9   # max across events
    assert shared["description"] == "d"       # first non-null wins
