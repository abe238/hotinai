"""The insider row's clock is the star EVENT, never the repo's creation date.

Gating insiders on repo age empties the section: measured on the live board 2026-09-12,
0 of 13 rows were within 7 days of creation (median repo age 52 days), while the roster
itself polls a 45-day star window. Abe's decision the same day: judge an insider row by
when the insider starred it.
"""

from hotin import board, freshness

OLD_REPO_FRESH_STAR = {
    "entity_id": "owner/ancient",
    "canonical_repo": "owner/ancient",
    "url": "https://github.com/owner/ancient",
    "signal": {"created_at": "2026-01-15T00:00:00Z",      # 80+ days old
               "most_recent_star_at": "2026-09-11T10:00:00+00:00",
               "insider_stars": 2, "stars": 900},
    "meta": {"insiders": ["deepfates"], "description": "d"},
}
OLD_REPO_OLD_STAR = {
    "entity_id": "owner/stale",
    "canonical_repo": "owner/stale",
    "url": "https://github.com/owner/stale",
    "signal": {"created_at": "2026-01-15T00:00:00Z",
               "most_recent_star_at": "2026-08-01T10:00:00+00:00",   # ~6 weeks ago
               "insider_stars": 1, "stars": 900},
    "meta": {"insiders": ["omarsar"], "description": "d"},
}

TODAY = __import__("datetime").date(2026, 9, 12)


def labels(row):
    return [b["label"] for b in row["badges"]]


def test_insider_kind_reads_the_star_event_not_created_at():
    assert freshness.entity_date(OLD_REPO_FRESH_STAR, "insider") == "2026-09-11T10:00:00+00:00"
    assert freshness.entity_date(OLD_REPO_FRESH_STAR, "repo") == "2026-01-15T00:00:00Z"


def test_old_repo_with_a_recent_star_is_fresh():
    assert freshness.is_fresh("insider", freshness.entity_date(OLD_REPO_FRESH_STAR, "insider"), TODAY)
    # the same record judged as a repo is NOT fresh -- that is the bug this kind exists for
    assert not freshness.is_fresh("repo", freshness.entity_date(OLD_REPO_FRESH_STAR, "repo"), TODAY)


def test_old_repo_with_a_stale_star_is_not_fresh():
    assert not freshness.is_fresh("insider", freshness.entity_date(OLD_REPO_OLD_STAR, "insider"), TODAY)


def test_insider_rows_use_the_star_event(monkeypatch):
    # insider_rows reads the clock itself, so this test was a time bomb: the fixture star is
    # dated 2026-09-11 and the insider window is 7 days, so it passed until the wall clock
    # reached 2026-09-18 and then failed every day after, for a reason that has nothing to do
    # with the behaviour under test. Pin the clock through the same seam production uses.
    monkeypatch.setattr(freshness, "_now", lambda: freshness._anchor(TODAY))
    fresh_row, stale_row = board.insider_rows([OLD_REPO_FRESH_STAR, OLD_REPO_OLD_STAR])
    assert fresh_row["date_iso"] == "2026-09-11T10:00:00+00:00"
    assert stale_row["date_iso"] == "2026-08-01T10:00:00+00:00"
    # PIN: if insider_rows ever reverts to kind "repo", both rows take created_at and the
    # recent-star row stops being fresh -- this assertion is what catches that.
    assert "fresh" in labels(fresh_row)
    assert "fresh" not in labels(stale_row)
    assert all(r["section_id"] == "insiders" for r in (fresh_row, stale_row))


def test_missing_star_event_is_ineligible_and_never_falls_back_to_created_at():
    rec = {"entity_id": "owner/nostar", "canonical_repo": "owner/nostar",
           "signal": {"created_at": "2026-09-11T00:00:00Z", "stars": 5}, "meta": {}}
    assert freshness.entity_date(rec, "insider") is None
    assert not freshness.is_fresh("insider", None, TODAY)
    row = board.insider_rows([rec])[0]
    assert row["date_iso"] is None and row["age_days"] is None
    assert "fresh" not in labels(row)


def test_policy_carries_the_insider_window_and_the_version_bumped():
    p = freshness.policy()
    assert p["insider_max_age_days"] == freshness.INSIDER_MAX_AGE_DAYS
    assert "insider" in freshness.KINDS
    assert freshness.window("insider") == freshness.INSIDER_MAX_AGE_DAYS
    # adding a key to the policy block changes the consumer contract, so the version moves
    assert freshness.POLICY_VERSION == 2
