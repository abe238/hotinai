"""OPT-1: export and refresh print a per-phase timing table on stderr."""

import re

from hotin import cli
from hotin.cache import MemoryCache
from hotin.cli import main

_EMPTY = {"records": [], "status": "empty", "detail": None}


def _stub_sources(monkeypatch):
    monkeypatch.setattr(cli, "open_cache", lambda: MemoryCache())
    monkeypatch.setattr(cli.engine, "fetch_all", lambda config, **kw: [])
    for adapter in (cli.insiders, cli.smartmoney, cli.rssnews, cli.anfpapers,
                    cli.hfmodels, cli.hfpapers):
        monkeypatch.setattr(adapter, "fetch", lambda **kw: dict(_EMPTY))


def _phases(err):
    return re.findall(r"^phase (\S+): \d+\.\d+s$", err, flags=re.M)


def test_export_prints_every_phase(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    _stub_sources(monkeypatch)
    monkeypatch.setattr(cli, "_rising_ranked", lambda *a, **kw: [])
    monkeypatch.setattr(cli._readme_desc, "fill_missing_descriptions", lambda *a, **kw: None)
    assert main(["export"]) == 0
    assert _phases(capsys.readouterr().err) == [
        "fetch_sources", "rank_repos_models_papers", "insiders_poll",
        "insiders_cache_readback", "news", "rising", "windows",
        "readme_descriptions", "render_rows", "render_index_html",
        "write_latest_json", "tags_json", "total"]


def test_refresh_prints_every_phase(monkeypatch, capsys):
    _stub_sources(monkeypatch)
    monkeypatch.setattr(cli.os, "_exit", lambda code: None)
    for mod, fn in ((cli.hfpapers, "backfill_summaries"), (cli.hfmodels, "backfill_descriptions"),
                    (cli.insiders, "backfill_created_at"), (cli.rssnews, "backfill_hn_points"),
                    (cli.rssnews, "recheck_hn_points")):
        monkeypatch.setattr(mod, fn, lambda cache, *a, **kw: 0)
    main(["refresh", "--json"])
    out, err = capsys.readouterr()
    assert out.lstrip().startswith("{")            # stdout JSON untouched
    assert _phases(err) == [
        "preserve_healed_meta", "fetch_sources", "fetch_insiders_news_papers",
        "heal_paper_summaries", "heal_model_descriptions", "heal_insider_dates",
        "heal_hn_points", "record_observations", "total"]
