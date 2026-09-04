"""OPT-2: `hotin export` reuses the roster poll `hotin refresh` just persisted.

The two commands are separate processes, so the in-memory memo cannot span
them; a completed poll is written next to cache.db as insiders_poll.json and
reused within HOTIN_INSIDERS_REUSE_S when roster, token, and window match.
"""

import json

import pytest

from hotin import cli
from hotin.cache import MemoryCache
from hotin.cli import main
from hotin.sources import _insider_roster as core

_EVENTS = [{"username": "alice", "canonical_repo": "owner/repo",
            "starred_at": "2026-07-25T00:00:00Z", "stargazers_count": 3,
            "description": "x", "repo_created_at": "2026-07-01T00:00:00Z"}]
_TALLY = {"ok": 2}
_CFG = {"GITHUB_TOKEN": "ghp_secret_value"}


@pytest.fixture
def polls(monkeypatch):
    """Stub the network layer; count real polls."""
    core._reset_memo()
    calls = []
    monkeypatch.setattr(core, "_roster", lambda config: ("alice", "bob"))
    monkeypatch.setattr(core, "_poll_via_graphql",
                        lambda *a, **kw: (calls.append(1), (list(_EVENTS), dict(_TALLY)))[1])
    return calls


def _second_process():
    core._MEMO.clear()   # the memo dies with the process; the file does not


def test_write_then_read_within_ttl_is_identical_with_zero_fetches(polls, capsys):
    first = core.poll_roster(config=_CFG)
    _second_process()
    second = core.poll_roster(config=_CFG)
    assert second == first == _EVENTS
    assert len(polls) == 1
    assert core.LAST_OUTCOMES == _TALLY
    assert "insiders: reused poll from 0 min ago" in capsys.readouterr().err
    saved = json.loads(core._persist_path().read_text())
    assert "ghp_secret_value" not in json.dumps(saved) and len(saved["token_fp"]) == 8


@pytest.mark.parametrize("change", ["roster", "token", "window", "age"])
def test_any_mismatch_forces_a_real_poll(polls, monkeypatch, change):
    core.poll_roster(config=_CFG)
    _second_process()
    cfg = dict(_CFG)
    if change == "roster":
        monkeypatch.setattr(core, "_roster", lambda config: ("alice", "carol"))
    elif change == "token":
        cfg["GITHUB_TOKEN"] = "rotated"
    elif change == "window":
        cfg["HOTIN_INSIDER_WINDOW_DAYS"] = "30"
    elif change == "age":
        monkeypatch.setattr(core.time, "time", lambda: 1e12)  # far past the TTL
    core.poll_roster(config=cfg)
    assert len(polls) == 2


def test_reuse_disabled_by_ttl_zero(polls):
    core.poll_roster(config=_CFG)
    _second_process()
    core.poll_roster(config=dict(_CFG, HOTIN_INSIDERS_REUSE_S="0"))
    assert len(polls) == 2


def test_corrupt_file_falls_back_to_a_real_poll(polls):
    core.poll_roster(config=_CFG)
    _second_process()
    core._persist_path().write_text("{not json")
    assert core.poll_roster(config=_CFG) == _EVENTS
    assert len(polls) == 2
    core._persist_path().write_text(json.dumps({"events": "nope", "saved_at": 0}))
    _second_process()
    core.poll_roster(config=_CFG)
    assert len(polls) == 3


def _stub_pipeline(monkeypatch):
    """Everything except the insiders path, which stays real down to the stub."""
    monkeypatch.setattr(cli, "open_cache", lambda: MemoryCache())
    monkeypatch.setattr(cli, "load_config", lambda: dict(_CFG))
    monkeypatch.setattr(cli.engine, "fetch_all", lambda config, **kw: [])
    empty = {"records": [], "status": "empty", "detail": None}
    for adapter in (cli.rssnews, cli.anfpapers, cli.hfmodels, cli.hfpapers):
        monkeypatch.setattr(adapter, "fetch", lambda **kw: dict(empty))
    monkeypatch.setattr(cli.os, "_exit", lambda code: None)
    for mod, fn in ((cli.hfpapers, "backfill_summaries"), (cli.hfmodels, "backfill_descriptions"),
                    (cli.insiders, "backfill_created_at"), (cli.rssnews, "backfill_hn_points"),
                    (cli.rssnews, "recheck_hn_points")):
        monkeypatch.setattr(mod, fn, lambda cache, *a, **kw: 0)
    monkeypatch.setattr(cli, "_rising_ranked", lambda *a, **kw: [])
    monkeypatch.setattr(cli._readme_desc, "fill_missing_descriptions", lambda *a, **kw: None)


def test_export_reuses_the_poll_refresh_persisted(polls, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    _stub_pipeline(monkeypatch)
    main(["refresh", "--quiet"])
    assert len(polls) == 1
    _second_process()
    assert main(["export"]) == 0
    assert len(polls) == 1, "export must not poll the roster again"
    assert "insiders: reused poll from 0 min ago" in capsys.readouterr().err
    _second_process()
    assert main(["export", "--no-insiders-cache"]) == 0
    assert len(polls) == 2
