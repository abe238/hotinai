"""Freshness ordering for the insiders board.

Before this, repo age was purely a filter: everything inside the 180-day cap
ranked identically and everything outside vanished. A 6-day-old repo and a
178-day-old one were indistinguishable, which is a cliff, not a ranking.

These tests pin the intended trade-off -- "insider consensus matters, but a bit
less than freshness" -- so a later tweak to the curve cannot silently invert it.
"""

from datetime import datetime, timedelta, timezone

from hotin.sources._insider_roster import (
    FRESH_BOOST,
    FRESH_FULL_DECAY_DAYS,
    aggregate_by_repo,
    score_record,
)

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)


def _ago(days):
    return (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z")


def _event(user, repo, age_days):
    return {
        "username": user,
        "canonical_repo": repo,
        "starred_at": _ago(1),
        "repo_created_at": _ago(age_days),
    }


def _order(events):
    return [r["canonical_repo"] for r in aggregate_by_repo(events, now=NOW)]


class TestScoreCurve:
    def test_new_repo_gets_the_full_boost(self):
        assert score_record(1.0, _ago(0), NOW) == 1.0 + FRESH_BOOST

    def test_boost_is_gone_at_the_age_cap(self):
        assert score_record(1.0, _ago(FRESH_FULL_DECAY_DAYS), NOW) == 1.0

    def test_past_the_cap_never_goes_negative(self):
        # Records older than the cap are normally filtered out before ranking,
        # but the curve must not invert if one ever reaches the sort.
        assert score_record(1.0, _ago(3650), NOW) == 1.0

    def test_unknown_creation_date_scores_as_fully_decayed(self):
        # Missing data must never look brand-new. Treating an absent created_at
        # as fresh is what put 1077-day-old repos at the top of the board.
        assert score_record(1.0, None, NOW) == 1.0
        assert score_record(1.0, "", NOW) == 1.0
        assert score_record(1.0, "not-a-date", NOW) == 1.0

    def test_consensus_has_diminishing_returns(self):
        # sqrt: the 4th insider adds less than the 2nd did. Without this the raw
        # weight range (1..6+) swamps the freshness range (1.0..1.66).
        d = _ago(FRESH_FULL_DECAY_DAYS)
        first = score_record(2.0, d, NOW) - score_record(1.0, d, NOW)
        later = score_record(4.0, d, NOW) - score_record(3.0, d, NOW)
        assert later < first


class TestOrdering:
    def test_freshness_outranks_one_extra_insider(self):
        # The headline intent: a fresh solo find beats a stale pair.
        order = _order([
            _event("a", "new/solo", 0),
            _event("b", "old/pair", 175),
            _event("c", "old/pair", 175),
        ])
        assert order[0] == "new/solo"

    def test_but_real_consensus_still_wins(self):
        # "a bit less than freshness" is not "freshness beats everything".
        order = _order(
            [_event("a", "new/solo", 0)]
            + [_event(u, "old/crowd", 175) for u in "bcdef"]
        )
        assert order[0] == "old/crowd"

    def test_equal_consensus_ranks_newer_first(self):
        # The exact case the old filter-only behaviour could not express.
        order = _order([_event("a", "z/newer", 10), _event("b", "a/older", 170)])
        assert order[0] == "z/newer"

    def test_order_is_independent_of_input_order(self):
        forward = _order([_event("a", "x/one", 5), _event("b", "y/two", 5)])
        reverse = _order([_event("b", "y/two", 5), _event("a", "x/one", 5)])
        assert forward == reverse

    def test_undated_records_still_rank_by_consensus(self):
        # A cold store with no creation dates must degrade to the old behaviour
        # rather than scrambling the board.
        events = [
            {"username": "a", "canonical_repo": "solo/repo", "starred_at": _ago(1)},
            {"username": "b", "canonical_repo": "pair/repo", "starred_at": _ago(1)},
            {"username": "c", "canonical_repo": "pair/repo", "starred_at": _ago(1)},
        ]
        assert _order(events)[0] == "pair/repo"

    def test_weight_is_preserved_for_display(self):
        # score is the ranking function; weight is what the receipts claim and
        # what the ledger publishes. They must not be conflated.
        recs = aggregate_by_repo([_event("a", "one/repo", 0)], now=NOW)
        assert recs[0]["weight"] == 1.0
        assert recs[0]["score"] > recs[0]["weight"]
