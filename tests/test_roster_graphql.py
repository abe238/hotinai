"""The GraphQL roster poller, tested against REAL captured GitHub responses.

The property under test is not "does it parse JSON". It is: **can any input
produce a fabricated empty result?** A non-OK account must never look like an
account that simply starred nothing, because that exact conflation once shipped
a small, plausible, entirely fictional board.
"""

import pytest

from hotin.sources import _roster_graphql as G
from fixtures_graphql import (CLEAN, CLEAN_REQUESTED,
                              RESOURCE_LIMITS, RESOURCE_LIMITS_REQUESTED,
                              NULL_USER, NULL_USER_REQUESTED)


def _always_fresh(starred_at, *, window_days, now=None):
    return True


def _never_fresh(starred_at, *, window_days, now=None):
    return False


def parse(payload, requested, fresh=_always_fresh):
    return G.parse_batch(payload, requested, window_days=30, fresh_fn=fresh)


# --- the measured hazard --------------------------------------------------

def test_the_real_resource_limits_response_never_yields_ok():
    """HTTP 200, cost 1, every user present, no null nodes -- and corrupt.

    This is the captured 40x20 response. Every cheap success metric reads
    perfect; the damage is nulled edges. If any account here comes back OK,
    the board would silently under-report those insiders.
    """
    got = parse(RESOURCE_LIMITS, RESOURCE_LIMITS_REQUESTED)
    assert set(got) == set(RESOURCE_LIMITS_REQUESTED)
    for login, entry in got.items():
        assert entry["outcome"] != G.OK, login
        assert entry["events"] == [], login


def test_the_corrupt_fixture_really_does_look_successful():
    """Guard the guard: prove the fixture has the properties that make it lethal."""
    data = RESOURCE_LIMITS["data"]
    assert data["rateLimit"]["cost"] == 1
    users = [k for k in data if k.startswith("u")]
    assert users, "fixture must contain user aliases"
    assert all(data[u] is not None for u in users), "no null user nodes"
    assert any(e["type"] == "RESOURCE_LIMITS_EXCEEDED" for e in RESOURCE_LIMITS["errors"])
    # the actual damage: edges present in the list, but null
    assert None in data["u0"]["starredRepositories"]["edges"]


def test_completeness_gate_alone_catches_it_with_error_parsing_disabled():
    """The two defences must be genuinely independent.

    Strip `errors[]` entirely, leaving only the corrupt `data`. The completeness
    gate must still refuse it -- because error `path` shapes vary by origin and
    a global error has no path at all, so parsing them cannot be the only guard.
    """
    stripped = {"data": RESOURCE_LIMITS["data"]}
    got = parse(stripped, RESOURCE_LIMITS_REQUESTED)
    assert all(e["outcome"] != G.OK for e in got.values())


def test_is_resource_limited_flags_the_shrink_signal():
    assert G.is_resource_limited(RESOURCE_LIMITS) is True
    assert G.is_resource_limited(CLEAN) is False


# --- the clean path -------------------------------------------------------

def test_a_clean_batch_resolves_every_account():
    got = parse(CLEAN, CLEAN_REQUESTED)
    assert set(got) == set(CLEAN_REQUESTED)
    assert all(e["outcome"] == G.OK for e in got.values()), \
        {k: v["outcome"] for k, v in got.items()}


def test_events_carry_the_fields_the_board_ranks_on():
    got = parse(CLEAN, CLEAN_REQUESTED)
    events = [ev for e in got.values() for ev in e["events"]]
    assert events, "the clean fixture should yield star events"
    for ev in events:
        assert ev["username"] in CLEAN_REQUESTED
        assert "/" in ev["canonical_repo"]
        assert isinstance(ev["starred_at"], str) and ev["starred_at"]
        # repo_created_at drives the 180-day age cap; missing it is what made an
        # earlier version of this tab erratic and often empty
        assert isinstance(ev["repo_created_at"], str) and ev["repo_created_at"]
        assert isinstance(ev["stargazers_count"], int)


def test_out_of_window_stars_are_dropped_but_the_account_is_still_ok():
    """"Looked, found nothing recent" is a legitimate OK. Only that."""
    got = parse(CLEAN, CLEAN_REQUESTED, fresh=_never_fresh)
    assert all(e["outcome"] == G.OK for e in got.values())
    assert all(e["events"] == [] for e in got.values())


# --- the relocated failure signals ----------------------------------------

def test_a_null_user_node_is_not_found_never_ok():
    got = parse(NULL_USER, NULL_USER_REQUESTED)
    entry = got[NULL_USER_REQUESTED[0]]
    assert entry["outcome"] == G.NOT_FOUND
    assert entry["events"] == []


def test_a_null_node_without_any_error_entry_is_still_not_ok():
    payload = {"data": {"u0": None, "rateLimit": {"remaining": 4999}}}
    got = parse(payload, ["someone"])
    assert got["someone"]["outcome"] == G.NOT_FOUND


def test_a_global_error_with_no_path_condemns_the_whole_batch():
    """Error-path attribution cannot help here; nothing may stay OK."""
    payload = {"data": {"u0": None, "u1": None},
               "errors": [{"type": "RATE_LIMITED", "message": "over quota"}]}
    got = parse(payload, ["a", "b"])
    assert [e["outcome"] for e in got.values()] == [G.RATE_LIMITED, G.RATE_LIMITED]


def test_an_unnamed_global_error_leaves_the_batch_unresolved():
    payload = {"data": {}, "errors": [{"message": "something we have never seen"}]}
    got = parse(payload, ["a", "b"])
    assert all(e["outcome"] == G.UNRESOLVED for e in got.values())


def test_a_typed_rate_limit_error_marks_only_its_own_account():
    payload = {"data": {"u0": None, "u1": None},
               "errors": [{"type": "RATE_LIMITED", "path": ["u1"]}]}
    got = parse(payload, ["a", "b"])
    assert got["b"]["outcome"] == G.RATE_LIMITED


def test_forbidden_maps_to_auth_failed():
    payload = {"data": {"u0": None}, "errors": [{"type": "FORBIDDEN", "path": ["u0"]}]}
    assert parse(payload, ["a"])["a"]["outcome"] == G.AUTH_FAILED


def test_an_alias_absent_from_both_data_and_errors_is_unresolved():
    """The silent-omission case. Absence is not evidence of an empty list."""
    payload = {"data": {"u0": None, "rateLimit": {}}}
    got = parse(payload, ["a", "b", "c"])
    assert got["b"]["outcome"] == G.UNRESOLVED
    assert got["c"]["outcome"] == G.UNRESOLVED


# --- identity attribution -------------------------------------------------

def _one_user(login, edges, has_next=False):
    return {"data": {"u0": {"login": login, "starredRepositories": {
        "pageInfo": {"hasNextPage": has_next}, "edges": edges}},
        "rateLimit": {"remaining": 4999}}}


def _edge(repo="acme/widget", starred="2026-07-27T00:00:00Z",
          created="2026-07-01T00:00:00Z"):
    return {"starredAt": starred, "node": {"nameWithOwner": repo,
            "createdAt": created, "stargazerCount": 5, "description": "d"}}


def test_canonical_casing_from_github_still_matches():
    """GitHub echoes its own casing; that is not a mismatch.

    Synthetic handle on purpose: the roster is private and this repo is public,
    so a real member's name here would confirm membership.
    """
    got = parse(_one_user("SomeDev", [_edge()]), ["somedev"])
    assert got["somedev"]["outcome"] == G.OK


def test_a_genuinely_different_echoed_login_is_a_mismatch_not_a_silent_swap():
    """Positional mapping would have attributed these stars to the wrong person."""
    got = parse(_one_user("someone-else", [_edge()]), ["expected-user"])
    entry = got["expected-user"]
    assert entry["outcome"] == G.MISMATCH
    assert entry["events"] == []


def test_a_missing_echoed_login_is_a_mismatch():
    payload = {"data": {"u0": {"starredRepositories": {"edges": [_edge()]}}}}
    assert parse(payload, ["a"])["a"]["outcome"] == G.MISMATCH


# --- the count-cap vs date-cap truncation ---------------------------------

def test_a_truncated_in_window_page_falls_back_to_rest():
    """`first: K` caps by COUNT; the window is a DATE. Never accept a short list."""
    got = parse(_one_user("a", [_edge(), _edge()], has_next=True), ["a"])
    entry = got["a"]
    assert entry["needs_rest"] is True
    assert entry["outcome"] != G.OK


def test_more_pages_but_oldest_already_out_of_window_is_fine():
    """The normal case: we paged past the window, so nothing was cut off."""
    got = parse(_one_user("a", [_edge()], has_next=True), ["a"], fresh=_never_fresh)
    assert got["a"]["outcome"] == G.OK
    assert got["a"]["needs_rest"] is False


def test_a_full_page_with_no_next_page_is_not_truncated():
    got = parse(_one_user("a", [_edge(), _edge()], has_next=False), ["a"])
    assert got["a"]["outcome"] == G.OK


# --- completeness gate, field by field ------------------------------------

@pytest.mark.parametrize("edges", [
    [None],
    [{"starredAt": None, "node": {"nameWithOwner": "a/b", "createdAt": "2026-01-01T00:00:00Z"}}],
    [{"starredAt": "", "node": {"nameWithOwner": "a/b", "createdAt": "2026-01-01T00:00:00Z"}}],
    [{"starredAt": "2026-07-27T00:00:00Z", "node": None}],
    [{"starredAt": "2026-07-27T00:00:00Z", "node": {"nameWithOwner": "a/b"}}],
    [{"starredAt": "2026-07-27T00:00:00Z", "node": {"createdAt": "2026-01-01T00:00:00Z"}}],
    ["not-a-dict"],
])
def test_any_incomplete_edge_invalidates_the_whole_account(edges):
    got = parse(_one_user("a", edges), ["a"])
    assert got["a"]["outcome"] != G.OK
    assert got["a"]["events"] == []


def test_one_bad_edge_poisons_the_account_rather_than_being_skipped():
    """Silently skipping the bad edge would under-report, which is the bug."""
    got = parse(_one_user("a", [_edge("acme/good"), None]), ["a"])
    assert got["a"]["outcome"] != G.OK
    assert got["a"]["events"] == []


# --- malformed everything -------------------------------------------------

@pytest.mark.parametrize("payload", [
    None, 42, "a string", [], {}, {"data": None}, {"data": "nope"},
    {"data": {}, "errors": "not a list"}, {"errors": [None, 42]},
])
def test_malformed_payloads_never_raise_and_never_yield_ok(payload):
    got = G.parse_batch(payload, ["a", "b"], window_days=30, fresh_fn=_always_fresh)
    assert set(got) == {"a", "b"}
    assert all(e["outcome"] != G.OK for e in got.values())


def test_an_empty_roster_batch_is_empty_not_an_error():
    assert G.parse_batch(CLEAN, [], window_days=30, fresh_fn=_always_fresh) == {}


# --- query construction ---------------------------------------------------

def test_the_query_pins_the_sort_order_explicitly():
    """Truncation detection assumes STARRED_AT DESC. Pin it, do not inherit it."""
    q = G.build_query(["a", "b"])
    assert "orderBy: {field: STARRED_AT, direction: DESC}" in q


def test_the_query_requests_the_echoed_login():
    assert "login" in G.build_query(["a"])


def test_the_query_requests_page_info_for_truncation_detection():
    assert "hasNextPage" in G.build_query(["a"])


def test_the_query_batches_and_cannot_be_broken_out_of():
    q = G.build_query(['ev"il', "b"])
    assert q.count("user(login:") == 2
    assert 'ev"il' not in q.replace('\\"', "")


def test_default_batch_size_is_the_measured_safe_one():
    """25x20 was clean 5/5; 40x20 corrupted 5/5. Do not raise these casually."""
    assert G.BATCH_USERS == 25
    assert G.BATCH_STARS == 20


def test_batches_covers_every_item_exactly_once():
    items = [str(i) for i in range(53)]
    out = [x for b in G.batches(items, 25) for x in b]
    assert out == items


# --- rate limit reading ---------------------------------------------------

def test_points_remaining_is_read_from_the_response():
    assert G.points_remaining({"data": {"rateLimit": {"remaining": 4321}}}) == 4321


@pytest.mark.parametrize("payload", [None, {}, {"data": {}}, {"data": {"rateLimit": {}}},
                                     {"data": {"rateLimit": {"remaining": "lots"}}}])
def test_points_remaining_is_none_when_absent_not_zero(payload):
    """Returning 0 would look like exhaustion and stop the run for no reason."""
    assert G.points_remaining(payload) is None


# --- telling a rate limit from a capability rejection ---------------------

@pytest.mark.parametrize("body", [
    None, "", "   ", b"bytes", 42,
    "You have exceeded a secondary rate limit",
    "API rate limit exceeded for user",
    "Too Many Requests",
    "please try again later",
])
def test_unknown_or_limit_like_bodies_are_treated_as_rate_limits(body):
    """Conservative by design: adding load to a limited endpoint is the worse
    error, so anything unknown counts as a limit."""
    assert G.is_secondary_rate_limit(body) is True


@pytest.mark.parametrize("body", [
    "Resource not accessible by personal access token",
    "This endpoint requires one of the following scopes: read:user",
    "Bad credentials",
])
def test_a_capability_rejection_is_not_a_rate_limit(body):
    """A 403 that means 'this credential cannot do that' should route to REST,
    which serves public reads fine with an unscoped classic token."""
    assert G.is_secondary_rate_limit(body) is False
