import json

import pytest

from hotin import cli
from hotin.cache import MemoryCache
from hotin.health import SourceStatus
from hotin.cli import COMMANDS, main


@pytest.fixture(autouse=True)
def prevent_hot_process_exit(monkeypatch):
    """Keep main() testable while production hot commands exit immediately."""
    monkeypatch.setattr(cli.os, "_exit", lambda exit_code: None)


def test_help_lists_every_subcommand(capsys):
    with pytest.raises(SystemExit) as exited:
        main(["--help"])

    output = capsys.readouterr().out
    assert exited.value.code == 0
    for command in COMMANDS:
        assert command in output


def test_setup_check_succeeds_without_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert main(["setup", "--check"]) == 0
    output = capsys.readouterr().out
    assert "configured entries: 0" in output
    assert "setup check passed" in output


def test_setup_check_sanitizes_config_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "\x1b[31mHACKED\x1b[0m" / "xdgconfig"))

    assert main(["setup", "--check"]) == 0
    assert "\x1b" not in capsys.readouterr().out


def test_hot_prints_ranked_json_from_seeded_cache(monkeypatch, capsys):
    cache = MemoryCache()

    def fetch_all(config, **kwargs):
        kwargs["cache"].upsert({
            "url": "https://github.com/acme/tool", "canonical_repo": "acme/tool",
            "name": "Acme Agent", "source": "github",
            "signal_json": {"__hotin_signal": {"stars": 20}, "__hotin_meta": {"topics": ["agent"]}},
        })
        return [SourceStatus("github", "ok")]

    monkeypatch.setattr(cli, "open_cache", lambda: cache)
    monkeypatch.setattr(cli.engine, "fetch_all", fetch_all)

    assert main(["hot", "--json", "--limit", "5"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["tools"][0]["name"] == "Acme Agent"
    assert output["tools"][0]["category"] == "agents"
    assert output["tools"][0]["score"] > 0
    assert output["sources"] == [{"source": "github", "status": "ok", "detail": None}]


def test_hot_limit_zero_returns_zero_tools(monkeypatch, capsys):
    cache = MemoryCache()
    monkeypatch.setattr(cli, "open_cache", lambda: cache)
    monkeypatch.setattr(cli.engine, "fetch_all", lambda *args, **kwargs: [SourceStatus("github", "empty")])

    assert main(["hot", "--json", "--limit", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["tools"] == []


def test_hot_rejects_negative_limit(capsys):
    assert main(["hot", "--limit", "-1"]) == 2
    assert "limit must be zero or greater" in capsys.readouterr().err


def test_hot_json_sanitizes_nonfinite_raw_signal(monkeypatch, capsys):
    cache = MemoryCache()

    def fetch_all(config, **kwargs):
        kwargs["cache"].upsert({
            "url": "https://github.com/acme/tool", "canonical_repo": "acme/tool",
            "name": "Acme Agent", "source": "github",
            "signal_json": {"__hotin_signal": {"stars": float("inf")}, "__hotin_meta": {}},
        })
        return [SourceStatus("github", "ok")]

    monkeypatch.setattr(cli, "open_cache", lambda: cache)
    monkeypatch.setattr(cli.engine, "fetch_all", fetch_all)

    assert main(["hot", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["tools"][0]["signal"]["stars"] is None


@pytest.mark.parametrize(
    ("statuses", "expected_exit_code"),
    [
        ([SourceStatus("github", "ok")], 0),
        ([SourceStatus("npm", "error", "timed out")], 1),
    ],
    ids=["success", "all-sources-failed"],
)
def test_hot_exits_immediately_after_output(monkeypatch, statuses, expected_exit_code):
    exit_codes = []
    monkeypatch.setattr(cli, "open_cache", MemoryCache)
    monkeypatch.setattr(cli.engine, "fetch_all", lambda *args, **kwargs: statuses)
    monkeypatch.setattr(cli.os, "_exit", exit_codes.append)

    assert main(["hot", "--json"]) == expected_exit_code
    assert exit_codes == [expected_exit_code]
