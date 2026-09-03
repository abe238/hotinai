import io
import json
import urllib.error
import urllib.request

import pytest

from hotin import __version__, cli, subscribe
from hotin.cache import MemoryCache
from hotin.cli import main
from hotin.health import SourceStatus
from hotin.throttle import Throttle


class _Response(io.BytesIO):
    def __init__(self, status: int) -> None:
        super().__init__(b'{"ok":true}')
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _fake_opener(status: int, seen: list):
    def opener(request, timeout=None):
        seen.append((request, timeout))
        return _Response(status)
    return opener


def test_subscribe_posts_json_with_headers(capsys):
    seen = []
    assert subscribe.run("you@example.com", opener=_fake_opener(202, seen)) == 0
    request, timeout = seen[0]
    assert request.full_url == "https://hotin.ai/api/subscribe"
    assert request.get_method() == "POST"
    assert timeout == 10
    assert json.loads(request.data.decode("utf-8")) == {"email": "you@example.com", "source": "cli"}
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("X-hotin-client") == "cli"
    assert request.get_header("User-agent") == "hotin-cli/{}".format(__version__)
    assert capsys.readouterr().out.strip() == "Check your inbox to confirm."


def test_subscribe_accepts_200(capsys):
    assert subscribe.run("you@example.com", opener=_fake_opener(200, [])) == 0
    assert "Check your inbox" in capsys.readouterr().out


def test_subscribe_http_error_is_one_plain_line(capsys):
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, io.BytesIO(b"<b>slow</b>"))
    assert subscribe.run("you@example.com", opener=opener) == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert len(out.err.strip().splitlines()) == 1
    assert "429" in out.err
    assert "<" not in out.err


@pytest.mark.parametrize("reason", ["<script>nope</script>", "/Users/abe/.certs/proxy.pem", "proxy 10.0.0.7:3128 refused"])
def test_subscribe_network_error_is_constant(capsys, reason):
    def opener(request, timeout=None):
        raise urllib.error.URLError(reason)
    assert subscribe.run("you@example.com", opener=opener) == 1
    err = capsys.readouterr().err
    assert err.strip() == subscribe._NETWORK_ERROR
    assert reason not in err


@pytest.mark.parametrize("good", ["you@example.com", "first.last+tag@sub.example.co", "a_b%c@x-y.example.org"])
def test_subscribe_accepts_reasonable_addresses(good):
    calls = []
    assert subscribe.run(good, opener=_fake_opener(202, calls)) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("bad", [
    "not-an-email", "a@b", "@example.com", "a b@example.com", "", "<b>x</b>@example.com",
    "a..b@example.com", ".a@example.com", "a.@example.com",
    "a@.example.com", "a@example..com", "a@example-.com", "a@-example.com", "a@example.c0m", "a@example.com.",
])
def test_subscribe_rejects_garbage_locally(capsys, bad):
    calls = []
    assert subscribe.run(bad, opener=_fake_opener(202, calls)) == 2
    assert calls == []
    assert "<" not in capsys.readouterr().err


def test_cli_subscribe_wires_through_and_help_lists_it(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(subscribe, "urlopen", _fake_opener(202, seen))
    assert main(["subscribe", "you@example.com"]) == 0
    assert len(seen) == 1
    assert "Check your inbox to confirm." in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "subscribe" in capsys.readouterr().out


def test_cli_subscribe_bad_address_exits_2(capsys):
    assert main(["subscribe", "not-an-email"]) == 2


# --- footer -----------------------------------------------------------------

FOOTER = "Daily email at 8:08am PT: hotin subscribe you@example.com"


def _seed(monkeypatch):
    cache = MemoryCache()

    def fetch_all(config, **kwargs):
        kwargs["cache"].upsert({
            "url": "https://github.com/acme/tool", "canonical_repo": "acme/tool",
            "name": "Acme Agent", "source": "github",
            "signal_json": {"signal": {"stars": 20}, "meta": {"topics": ["agent"]}},
        })
        return [SourceStatus("github", "ok")]

    def offline(*args, **kwargs):
        raise urllib.error.URLError("offline in tests")

    def empty(**kwargs):
        return {"records": [], "status": "empty", "detail": None}

    insider = {"entity_type": "repo", "entity_id": "acme/tool", "canonical_repo": "acme/tool",
               "url": "https://github.com/acme/tool", "name": "Acme Agent", "source": "insiders",
               "signal": {"insider_stars": 3, "stars": 20}, "meta": {"insiders": ["simonw"]}}
    monkeypatch.setattr(cli, "open_cache", lambda: cache)
    monkeypatch.setattr(cli.engine, "fetch_all", fetch_all)
    monkeypatch.setattr(cli.hfmodels, "fetch", empty)
    monkeypatch.setattr(cli.hfpapers, "fetch", empty)
    news = {"name": "Acme ships a thing", "url": "https://acme.example/blog", "source": "rssnews",
            "signal": {}, "meta": {"date": "2026-09-01", "publisher": "Acme", "kind": "primary"}}
    rising = {"canonical_repo": "acme/rocket", "name": "acme/rocket", "url": "https://github.com/acme/rocket",
              "signal": {"stars": 500, "created_at": "2026-08-30T00:00:00Z"}, "meta": {}}
    monkeypatch.setattr(cli.rssnews, "fetch", lambda **kwargs: {"records": [news], "status": "ok", "detail": None})
    monkeypatch.setattr(cli.github, "fetch", lambda *a, **kw: {"records": [rising], "status": "ok", "detail": None})
    monkeypatch.setattr(cli.insiders, "fetch", lambda **kwargs: {"records": [insider], "status": "ok", "detail": None})
    monkeypatch.setattr(urllib.request, "urlopen", offline)  # every other adapter degrades to empty
    monkeypatch.setattr(Throttle, "_sleep_and_record", lambda self, delay: None)  # no pacing sleeps
    monkeypatch.setattr(cli.os, "_exit", lambda code: None)
    monkeypatch.delenv("HOTIN_NO_FOOTER", raising=False)


BOARD_COMMANDS = ["repos", "rising", "insiders", "models", "papers", "news", "brief"]


@pytest.mark.parametrize("command", BOARD_COMMANDS)
def test_footer_prints_once_after_text_board(monkeypatch, capsys, command):
    _seed(monkeypatch)
    assert main([command]) == 0
    out = capsys.readouterr().out
    assert out.count(FOOTER) == 1
    assert out.rstrip().endswith(FOOTER)


@pytest.mark.parametrize("command", BOARD_COMMANDS)
def test_footer_is_dim_when_color_enabled(monkeypatch, capsys, command):
    _seed(monkeypatch)
    monkeypatch.setattr(cli, "_color_enabled", lambda arguments: True)
    assert main([command]) == 0
    out = capsys.readouterr().out
    assert out.count(FOOTER) == 1
    assert "\x1b[2m" + FOOTER + "\x1b[0m" in out


@pytest.mark.parametrize("command", BOARD_COMMANDS)
@pytest.mark.parametrize("flags", [["--format", "json"], ["--json"], ["--format", "md"], ["--format", "html"]])
def test_footer_absent_for_non_text_formats(monkeypatch, capsys, command, flags):
    _seed(monkeypatch)
    assert main([command] + flags) == 0
    assert FOOTER not in capsys.readouterr().out


def test_footer_respects_env_opt_out(monkeypatch, capsys):
    _seed(monkeypatch)
    monkeypatch.setenv("HOTIN_NO_FOOTER", "1")
    assert main(["repos", "--limit", "5"]) == 0
    assert FOOTER not in capsys.readouterr().out


def test_footer_not_on_non_board_commands(capsys):
    assert main(["about"]) == 0
    assert FOOTER not in capsys.readouterr().out
