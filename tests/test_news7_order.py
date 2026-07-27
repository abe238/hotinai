"""The 7-day news tab must not be the news tab truncated.

Measured on the live board 2026-07-27: news7 shared 33 of 33 rows with news
and 32 of them sat at an identical rank. That is guaranteed, not unlucky --
the main tab is ranked date-first, so a date filter over it returns its own
prefix. These tests pin the ranking, which is the part that had to change.
"""

from hotin.cli import _news7_order


def _story(name, points=0, day=0, rising=False):
    return {"name": name,
            "signal": {"hn_points": points, "hn_rising": rising},
            "meta": {"day": day}}


def _by_date(record):
    """Stand-in for the production date-first rank: newest day first."""
    return -(record.get("meta") or {}).get("day", 0)


def _names(records):
    return [r["name"] for r in _news7_order(records, _by_date)]


def test_the_week_is_ranked_by_points_not_by_date():
    """The whole defect: the newest story is not automatically first."""
    stories = [_story("newest-but-ignored", points=3, day=10),
               _story("older-but-huge", points=800, day=1)]
    assert _names(stories) == ["older-but-huge", "newest-but-ignored"]


def test_it_diverges_from_a_date_ordered_list():
    """A date-sorted input must come back in a genuinely different order."""
    stories = [_story("d5", points=10, day=5),
               _story("d4", points=90, day=4),
               _story("d3", points=50, day=3)]
    assert _names(stories) == ["d4", "d3", "d5"]


def test_a_rising_story_beats_a_flat_one_at_equal_points():
    stories = [_story("flat", points=100, day=9),
               _story("rising", points=100, day=1, rising=True)]
    assert _names(stories) == ["rising", "flat"]


def test_date_breaks_ties_when_the_crowd_is_silent():
    """Unscored stories still need a stable, sensible order."""
    stories = [_story("old", day=1), _story("new", day=9), _story("mid", day=5)]
    assert _names(stories) == ["new", "mid", "old"]


def test_ordering_does_not_depend_on_input_order():
    stories = [_story("a", points=5, day=1), _story("b", points=90, day=2),
               _story("c", points=40, day=3)]
    assert _names(stories) == _names(list(reversed(stories)))


def test_it_keeps_every_story():
    stories = [_story(str(i), points=i) for i in range(12)]
    assert len(_news7_order(stories, _by_date)) == 12


def test_missing_and_malformed_signals_never_raise():
    stories = [{"name": "no-signal", "meta": {"day": 1}},
               {"name": "signal-is-a-string", "signal": "nope", "meta": {"day": 2}},
               {"name": "points-are-junk", "signal": {"hn_points": "many"}, "meta": {"day": 3}},
               {"name": "points-are-none", "signal": {"hn_points": None}, "meta": {"day": 4}},
               _story("real", points=7, day=5)]
    assert _news7_order(stories, _by_date)[0]["name"] == "real"


def test_non_dict_rows_are_dropped_rather_than_crashing():
    stories = [None, 42, "story", _story("real", points=1)]
    assert [r["name"] for r in _news7_order(stories, _by_date)] == ["real"]


def test_an_empty_week_stays_empty():
    assert _news7_order([], _by_date) == []
