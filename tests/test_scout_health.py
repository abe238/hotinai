import json

import pytest

from hotin import cli
from hotin.cache import MemoryCache
from hotin.cli import main
from hotin.health import SourceStatus, scout_history, scout_observations, scout_summary_line


@pytest.fixture(autouse=True)
def prevent_hot_process_exit(monkeypatch):
    """Keep main() testable while production hot/update commands exit immediately."""
    monkeypatch.setattr(cli.os, "_exit", lambda exit_code: None)


def test_source_status_carries_items_and_defaults_to_zero():
    assert SourceStatus("github", "ok", "fine", 12).items == 12
    assert SourceStatus("github", "ok").items == 0


def test_recorded_cycle_round_trips():
    cache = MemoryCache()
    statuses = [SourceStatus("github", "ok", None, 5), SourceStatus("x", "empty", "not implemented", 0)]
    cache.record_observations(scout_observations(statuses, "run-1", 1000.0))

    records = {r.source: r for r in scout_history(cache)}

    assert records["github"].latest_status == "ok"
    assert records["github"].latest_items == 5
    assert records["x"].latest_status == "empty"


def test_scouts_json_reports_live_and_inert():
    cache = MemoryCache()
    # enough cycles that "never returned ok" is evidence of inertness rather than one bad run
    for cycle in range(6):
        cache.record_observations(scout_observations(
            [SourceStatus("github", "ok", None, 5),
             SourceStatus("x", "empty", "not implemented", 0)],
            "run-{}".format(cycle), 1000.0 + cycle))

    records = {r.source: r for r in scout_history(cache)}

    assert records["github"].inert is False
    assert records["x"].inert is True


def test_healthy_denominator_excludes_inert_sources():
    cache = MemoryCache()
    # enough cycles that "never returned ok" is evidence of inertness rather than one bad run
    for cycle in range(6):
        cache.record_observations(scout_observations(
            [SourceStatus("github", "ok", None, 5),
             SourceStatus("x", "empty", "not implemented", 0)],
            "run-{}".format(cycle), 1000.0 + cycle))

    records = scout_history(cache)
    live = [r for r in records if not r.inert]

    assert len(live) == 1
    assert live[0].source == "github"


def test_brief_line_renders_with_right_counts():
    cache = MemoryCache()
    # enough cycles that "never returned ok" is evidence of inertness rather than one bad run
    for cycle in range(6):
        cache.record_observations(scout_observations(
            [SourceStatus("github", "ok", None, 5),
             SourceStatus("x", "empty", "not implemented", 0)],
            "run-{}".format(cycle), 1000.0 + cycle))

    line = scout_summary_line(scout_history(cache), "14:05 PT")

    assert line == "scouts: 1/1 live ok · 1 inert (x) · checked 14:05 PT"


def test_no_history_says_so_instead_of_a_fake_all_clear():
    assert scout_summary_line([], "14:05 PT") == "scouts: no history recorded yet"


def test_inert_scout_is_never_counted_healthy():
    """PIN: a scout that never reports must never be counted as healthy.

    One source returns ok every cycle, another returns empty every cycle.
    The summary must read 1/1 live ok plus one inert -- never 1/2, never 2/2.
    """
    cache = MemoryCache()
    for cycle, observed_at in enumerate((100.0, 200.0, 300.0, 400.0, 500.0, 600.0)):
        cache.record_observations(scout_observations(
            [SourceStatus("github", "ok", None, 3),
             SourceStatus("reddit", "empty", "no SCRAPECREATORS_API_KEY configured", 0)],
            "run-{}".format(cycle), observed_at))

    records = scout_history(cache)
    line = scout_summary_line(records, "14:05 PT")

    live = [r for r in records if not r.inert]
    assert len(live) == 1 and live[0].source == "github"
    assert line == "scouts: 1/1 live ok · 1 inert (reddit) · checked 14:05 PT"


def test_scouts_cmd_json_runs_against_local_store(capsys):
    assert main(["scouts", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert "sources" in output
    assert "window" in output
