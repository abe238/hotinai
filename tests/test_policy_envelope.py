"""The board export envelope + per-row freshness fields (T2).

Two other repos (hotin-web's newsletter, working-models' video publisher)
consume this JSON shape by field name -- `date_iso`, `age_days`, `section_id`
on every row, and `schema_version`/`policy_version`/`policy`/`generated_at`
at the top level. This file is the contract test for that shape, plus the
PIN that guards against the fake-success mode of emitting the new fields
while `_badges` still lets the engine's own (differently-defined) "fresh"
badge through untouched.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from hotin import board, cli, freshness

# freshness owns Pacific, and it falls back to a computed US rule when the machine
# has no IANA database -- importing ZoneInfo here reintroduced the exact failure
# 0.9.15 fixed, and broke CI collection on this one file.
_PT = freshness._PT_ZONE


def _iso(days_ago: int) -> str:
    # anchored to the SAME PT "today" freshness.age_days uses, so an exact
    # `age_days == N` assertion doesn't flake near a UTC/PT day boundary
    pt_today = datetime.now(_PT).date()
    return (pt_today - timedelta(days=days_ago)).isoformat() + "T00:00:00Z"


def _all_rows() -> dict:
    """One representative record per row builder, each carrying a real date
    so date_iso/age_days are non-null and section_id can be checked."""
    repo = {"canonical_repo": "a/b", "url": "u",
            "signal": {"stars": 10, "created_at": _iso(3)}, "meta": {}}
    rising = {"canonical_repo": "c/d", "url": "u",
              "signal": {"stars": 5, "age_days": 2, "created_at": _iso(2)}, "meta": {}}
    insider = {"canonical_repo": "e/f", "url": "u",
               "signal": {"insider_stars": 1, "created_at": _iso(1)},
               "meta": {"insiders": ["someone"]}}
    model = {"entity_id": "org/m", "url": "u",
             "signal": {"model_likes": 1, "created_at": _iso(4)}, "meta": {}}
    paper = {"entity_id": "p1", "name": "P1", "url": "u",
             "signal": {"paper_upvotes": 1, "created_at": _iso(5)}, "meta": {}}
    curated = {"entity_id": "p2", "name": "P2", "url": "u",
               "signal": {"paper_upvotes": 2, "created_at": _iso(6)},
               "meta": {"curated_by": "ANF", "digest_date": "2026-09-10", "digest_rank": 1}}
    news = {"name": "story", "url": "u", "signal": {}, "meta": {"date": _iso(1)}}
    return {
        "repos": board.repo_rows([repo]),
        "rising": board.rising_rows([rising]),
        "insiders": board.insider_rows([insider]),
        "models": board.model_rows([model]),
        "papers": board.paper_rows([paper]),
        "curated": board.curated_paper_rows([curated]),
        "news": board.news_rows([news], note="swept 1/1 feeds"),
    }


_EXPECTED_SECTION_ID = {
    "repos": "repos", "rising": "rising", "insiders": "insiders",
    "models": "models", "papers": "papers", "curated": "curated", "news": "news",
}


def test_every_row_carries_the_frozen_freshness_fields():
    rows = _all_rows()
    for list_name, section_id in _EXPECTED_SECTION_ID.items():
        entity_rows = rows[list_name]
        assert entity_rows, list_name  # fixture sanity: the list must not be empty
        for row in entity_rows:
            assert "date_iso" in row and "age_days" in row and "section_id" in row, row
            assert row["section_id"] == section_id, row


def test_export_envelope_carries_schema_and_policy(tmp_path):
    rows = _all_rows()
    cli._write_latest_json(tmp_path, "2026-09-12", "2026-09-12 09:00 PT", rows)
    written = json.loads((tmp_path / "data" / "latest.json").read_text())

    assert written["schema_version"] == freshness.SCHEMA_VERSION == 2
    assert written["policy_version"] == freshness.POLICY_VERSION == 2
    assert written["policy"] == freshness.policy()
    # existing keys hotin-web reads today must survive untouched
    assert written["generated"] == "2026-09-12"
    assert written["generated_pt"] == "2026-09-12 09:00 PT"
    assert "entities" in written

    generated_at = written["generated_at"]
    assert generated_at.endswith("Z")
    parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def test_old_but_recently_active_repo_is_not_fresh():
    """The fake-success mode this PINs: new fields present, but `_badges`
    still lets the engine's `fresh` (young OR re-seen recently) through
    unfiltered -- so a 40-day-old repo a source re-saw yesterday would still
    show the visitor-facing `fresh` badge. It must not."""
    old_but_active = {"canonical_repo": "a/b", "url": "u",
                       "signal": {"stars": 100, "created_at": _iso(40)},
                       "badges": ["fresh"], "meta": {}}
    row = board.repo_rows([old_but_active])[0]
    labels = [b["label"] for b in row["badges"]]
    assert "fresh" not in labels, labels
    assert row["age_days"] == 40

    genuinely_recent = {"canonical_repo": "c/d", "url": "u",
                         "signal": {"stars": 5, "created_at": _iso(3)},
                         "badges": ["fresh"], "meta": {}}
    row2 = board.repo_rows([genuinely_recent])[0]
    assert "fresh" in [b["label"] for b in row2["badges"]]
