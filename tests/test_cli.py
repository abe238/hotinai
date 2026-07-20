import json
import time

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


def _source_record(name, signal, *, source="github", meta=None):
    return {
        "url": "https://github.com/acme/{}".format(name.replace(" ", "-").lower()),
        "canonical_repo": "acme/{}".format(name.replace(" ", "-").lower()),
        "name": name,
        "source": source,
        "signal": signal,
        "meta": meta or {},
    }


@pytest.mark.parametrize(
    ("command", "adapter_name", "records", "first_name"),
    [
        ("hn", "hn", [_source_record("low", {"hn_points": 2}), _source_record("high", {"hn_points": 9})], "high"),
        ("npm", "npm", [_source_record("low", {"npm_growth": 0.1}), _source_record("high", {"npm_growth": 0.5})], "high"),
        ("stars", "github", [_source_record("low", {"stars": 2}), _source_record("high", {"stars": 9})], "high"),
        ("trending", "trends", [_source_record("low", {"trend_total_score": 2}), _source_record("high", {"trend_total_score": 9})], "high"),
        ("reddit", "reddit", [_source_record("low", {"reddit_score": 2}), _source_record("high", {"reddit_score": 9})], "high"),
        ("youtube", "youtube", [_source_record("low", {"youtube_views": 2}), _source_record("high", {"youtube_views": 9})], "high"),
    ],
)
def test_single_source_commands_sort_live_adapter_records(monkeypatch, capsys, command, adapter_name, records, first_name):
    adapter = getattr(cli, adapter_name)
    monkeypatch.setattr(adapter, "fetch", lambda **kwargs: {"records": records, "status": "ok", "detail": None})

    assert main([command, "--limit", "2"]) == 0
    assert capsys.readouterr().out.splitlines()[0].endswith(first_name)


@pytest.mark.parametrize("command,adapter_name", [("hn", "hn"), ("npm", "npm"), ("stars", "github"), ("trending", "trends"), ("reddit", "reddit"), ("youtube", "youtube")])
def test_single_source_errors_and_empty_results(monkeypatch, capsys, command, adapter_name):
    adapter = getattr(cli, adapter_name)
    monkeypatch.setattr(adapter, "fetch", lambda **kwargs: {"records": [], "status": "error", "detail": "network unavailable"})
    assert main([command]) == 1
    assert "network unavailable" in capsys.readouterr().err

    monkeypatch.setattr(adapter, "fetch", lambda **kwargs: {"records": [], "status": "empty", "detail": "nothing found"})
    assert main([command]) == 0
    assert "No {} results".format(command) in capsys.readouterr().out


def test_single_source_ok_without_usable_records_is_friendly(monkeypatch, capsys):
    monkeypatch.setattr(cli.hn, "fetch", lambda **kwargs: {"records": [], "status": "ok", "detail": None})
    assert main(["hn"]) == 0
    assert "No hn results right now." in capsys.readouterr().out


def _cache_record(name, source, signal, *, canonical="acme/agent", meta=None):
    return {
        "url": "https://github.com/{}".format(canonical),
        "canonical_repo": canonical,
        "name": name,
        "source": source,
        "signal_json": {"__hotin_signal": signal, "__hotin_meta": meta or {}},
        "fetched_at": time.time(),
    }


def test_search_merges_source_observations_before_rendering(monkeypatch, capsys):
    cache = MemoryCache()
    cache.upsert(_cache_record("Agent Tool", "github", {"stars": 20}))
    cache.upsert(_cache_record("Agent Tool", "hn", {"hn_points": 40}))
    monkeypatch.setattr(cli, "open_cache", lambda: cache)

    assert main(["search", "agent", "--json"]) == 0
    tools = json.loads(capsys.readouterr().out)["tools"]
    assert len(tools) == 1
    assert tools[0]["sources"] == ["github", "hn"]


def test_search_requires_query(capsys):
    with pytest.raises(SystemExit) as exited:
        main(["search"])
    assert exited.value.code == 2
    assert "search requires a query" in capsys.readouterr().err


def test_search_empty_result_is_friendly(monkeypatch, capsys):
    monkeypatch.setattr(cli, "open_cache", MemoryCache)
    assert main(["search", "missing"]) == 0
    assert "No cached tools match missing." in capsys.readouterr().out


def test_show_prints_provenance_and_missing_repo_is_normal(monkeypatch, capsys):
    cache = MemoryCache()
    cache.upsert(_cache_record("Agent Tool", "github", {"stars": 20}))
    cache.upsert(_cache_record("Agent Tool", "hn", {"hn_points": 40}))
    monkeypatch.setattr(cli, "open_cache", lambda: cache)

    assert main(["show", "ACME/AGENT"]) == 0
    output = capsys.readouterr().out
    assert "signals:" in output
    assert "github:" in output and "stars: 20" in output
    assert "hn:" in output and "hn_points: 40" in output
    assert "momentum:" in output and "freshness_factor:" in output

    assert main(["show", "acme/missing"]) == 0
    assert "is not in the local cache yet" in capsys.readouterr().out


def test_update_sets_zero_ttl_even_when_cache_is_fresh(monkeypatch, capsys):
    cache = MemoryCache()
    cache.upsert(_cache_record("Fresh", "github", {"stars": 1}))
    seen = {}

    def fetch_all(config, **kwargs):
        seen.update(kwargs)
        return [SourceStatus("github", "ok", "refreshed")]

    monkeypatch.setattr(cli, "open_cache", lambda: cache)
    monkeypatch.setattr(cli.engine, "fetch_all", fetch_all)

    assert main(["update"]) == 0
    assert seen["ttl"] == 0
    assert "github  ok — refreshed" in capsys.readouterr().out


def test_about_always_shows_version_and_attribution(capsys):
    assert main(["about", "--quiet"]) == 0
    output = capsys.readouterr().out
    assert cli.__version__ in output
    assert "github.com/abe238/hotinai" in output


def test_attribution_only_once_and_only_for_interactive_human_output(monkeypatch, tmp_path, capsys):
    cache = MemoryCache()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "open_cache", lambda: cache)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)

    assert main(["search", "agent"]) == 0
    assert "github.com/abe238/hotinai" in capsys.readouterr().out
    assert (tmp_path / "hotin" / ".attribution-shown").exists()
    assert main(["search", "agent"]) == 0
    assert "github.com/abe238/hotinai" not in capsys.readouterr().out

    (tmp_path / "hotin" / ".attribution-shown").unlink()
    assert main(["search", "agent", "--quiet"]) == 0
    assert "github.com/abe238/hotinai" not in capsys.readouterr().out
    assert not (tmp_path / "hotin" / ".attribution-shown").exists()
    assert main(["search", "agent", "--json"]) == 0
    assert "github.com/abe238/hotinai" not in capsys.readouterr().out

    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: False)
    assert main(["search", "agent"]) == 0
    assert "github.com/abe238/hotinai" not in capsys.readouterr().out


def test_hostile_adapter_text_is_never_rendered_as_terminal_control(monkeypatch, capsys):
    hostile = "Agent \x1b[31mred\x1b[0m\u202e"
    cache = MemoryCache()
    cache.upsert(_cache_record(hostile, "hn", {"hn_points": 10}))
    monkeypatch.setattr(cli, "open_cache", lambda: cache)
    monkeypatch.setattr(cli.engine, "fetch_all", lambda *args, **kwargs: [SourceStatus("hn", "ok")])
    monkeypatch.setattr(cli.hn, "fetch", lambda **kwargs: {"records": [_source_record(hostile, {"hn_points": 10}, source="hn")], "status": "ok", "detail": None})

    for argv in (["hot"], ["search", "agent"], ["show", "acme/agent"], ["hn"]):
        assert main(argv) == 0
        output = capsys.readouterr().out
        assert "\x1b[31m" not in output
        assert "\u202e" not in output


def test_badge_colors_respect_no_color_and_non_tty(monkeypatch, tmp_path, capsys):
    cache = MemoryCache()
    cache.upsert(_cache_record("Fresh Agent", "github", {"stars": 5}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "open_cache", lambda: cache)
    monkeypatch.setattr(cli.engine, "fetch_all", lambda *args, **kwargs: [SourceStatus("github", "ok")])
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)

    assert main(["hot", "--quiet"]) == 0
    assert "\x1b[" in capsys.readouterr().out
    assert main(["hot", "--quiet", "--no-color"]) == 0
    assert "\x1b[" not in capsys.readouterr().out
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: False)
    assert main(["hot", "--quiet"]) == 0
    assert "\x1b[" not in capsys.readouterr().out
