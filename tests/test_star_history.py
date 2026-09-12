import json
import sqlite3
import urllib.error
from unittest.mock import MagicMock

import pytest

from hotin.cache import MemoryCache, Cache
from hotin.sources import _star_history as history

NOW = 1789194135
TODAY = int(NOW // 86400) * 86400
PAYLOAD = [
    {"week": 1788652800, "days": [151, 167, 160, 137, 166, 136, 0]},
    {"week": 1788048000, "days": [160, 342, 237, 168, 183, 155, 139]},
]


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    history._reset_memo()
    monkeypatch.setattr(history, "_THROTTLE", MagicMock())
    yield
    history._reset_memo()


def test_parse_complete_days_and_missing_window():
    parsed = history.parse_history(PAYLOAD, now=NOW)
    assert parsed["stars_1d"] == 136
    assert parsed["stars_7d"] == 1056
    assert parsed["stars_prev_7d"] == 1245
    assert parsed["daily"][-1] == (TODAY - 86400, 136)
    assert all(day + 86400 <= TODAY for day, _ in parsed["daily"])
    junk = [None, {}, {"week": 0, "days": [1] * 6},
            {"week": 0, "days": [-1] * 7}, {"week": 0, "days": ["1"] * 7}]
    assert history.parse_history(junk + PAYLOAD, now=NOW) == parsed
    assert history.parse_history(junk, now=NOW) is None
    assert history.parse_history({}, now=NOW) is None


def test_fetch_headers_and_memo(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps(PAYLOAD).encode()
    request = MagicMock(return_value=response)
    monkeypatch.setattr(history.urllib.request, "urlopen", request)
    assert history.fetch_history("a/b", now=NOW)["stars_7d"] == 1056
    assert history.fetch_history("a/b", now=NOW)["stars_7d"] == 1056
    assert request.call_count == 1
    req = request.call_args.args[0]
    assert req.full_url.endswith("/repos/a/b/stargazers/history?per_page=6")
    assert req.get_header("X-github-api-version") == history.API_VERSION
    assert request.call_args.kwargs == {"timeout": 20}


@pytest.mark.parametrize("code", [404, 403, 429])
def test_fetch_errors_are_memoized(monkeypatch, code):
    request = MagicMock(side_effect=urllib.error.HTTPError(
        "url", code, "error", {"Retry-After": "2"}, None))
    monkeypatch.setattr(history.urllib.request, "urlopen", request)
    assert history.fetch_history("a/b", now=NOW) is None
    assert history.fetch_history("a/b", now=NOW) is None
    assert request.call_count == 1
    assert history._THROTTLE.wait_for_retry_after.call_count == (code in (403, 429))


@pytest.mark.parametrize("body,status", [(b"junk", 200), (b"{}", 200), (b"[]", 202)])
def test_fetch_invalid_response(monkeypatch, body, status):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = status
    response.read.return_value = body
    monkeypatch.setattr(history.urllib.request, "urlopen", MagicMock(return_value=response))
    assert history.fetch_history("a/b", now=NOW) is None


def test_annotate_padding_limit_and_trace(monkeypatch, capsys):
    fetch = MagicMock(return_value=history.parse_history(PAYLOAD, now=NOW))
    monkeypatch.setattr(history, "fetch_history", fetch)
    records = [None, {"name": "bad name"}, {"name": "a/b"}, {"name": "c/d"}]
    assert history.annotate(records, now=NOW, max_records=1) == 1
    assert len(records[2]["meta"]["star_days"]) == 30
    assert records[2]["meta"]["star_days"][-1] == 136
    assert records[2]["meta"]["star_days"][0] == 0
    assert fetch.call_count == 1
    assert "star_history: 1/1 repos" in capsys.readouterr().err


@pytest.mark.parametrize("persistent", [False, True])
def test_seed_exact_values_and_idempotency(tmp_path, persistent):
    if persistent:
        connection = sqlite3.connect(str(tmp_path / "history.db"))
        connection.row_factory = sqlite3.Row
        cache = Cache(connection)
    else:
        cache = MemoryCache()
    record = {"canonical_repo": "a/b", "signal": {"stars": 1000, "stars_7d": 60},
              "meta": {"star_days": [10, 20, 30]}}
    assert history.seed_observations(cache, [record], now=NOW) == 3
    assert cache.observations_for("repo", "a/b", "stars") == [
        (950.0, float(TODAY - 2 * 86400)),
        (970.0, float(TODAY - 86400)), (1000.0, float(TODAY))]
    assert history.seed_observations(cache, [record], now=NOW) == 0
    rows = cache.recent_observations(0)
    assert len(rows) == 3
    assert all(r["entity_type"] == "repo" and r["metric"] == "stars"
               and r["source"] == "star_history" for r in rows)
    cache.close()
