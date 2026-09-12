"""Complete UTC days keep partial GitHub counts from distorting momentum."""

import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from hotin.throttle import Throttle
from .github import _retry_after

API_VERSION = "2026-03-10"
_API = "https://api.github.com"
_THROTTLE = Throttle(min_interval=0.25, jitter=0.1)
_USER_AGENT = "hotin (+https://hotin.ai)"
_REPO = re.compile(r"^[^/\s]+/[^/\s]+$")
_MEMO = {}
_STATUSES = {}
_LOCK = threading.Lock()
_DAY = 86400


def _reset_memo() -> None:
    with _LOCK:
        _MEMO.clear()
        _STATUSES.clear()


def parse_history(payload, *, now=None) -> Optional[dict]:
    """Anchor windows to UTC midnight, counting absent days as zero."""
    if not isinstance(payload, list):
        return None
    today = int((time.time() if now is None else now) // _DAY) * _DAY
    days = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        week, gains = entry.get("week"), entry.get("days")
        if (type(week) is not int or week < 0 or not isinstance(gains, list)
                or len(gains) != 7 or any(type(v) is not int or v < 0 for v in gains)):
            continue
        for i, value in enumerate(gains):
            day = week + i * _DAY
            if day + _DAY <= today:
                days[day] = value
    if not days:
        return None
    daily = [(day, days.get(day, 0)) for day in range(min(days), today, _DAY)]
    return {"daily": daily,
            "stars_7d": sum(days.get(today - i * _DAY, 0) for i in range(1, 8)),
            "stars_prev_7d": sum(days.get(today - i * _DAY, 0) for i in range(8, 15)),
            "stars_1d": days.get(today - _DAY, 0)}


def fetch_history(repo, token=None, *, now=None) -> Optional[dict]:
    """Memoize misses too, so overlapping board tabs never repeat a request."""
    with _LOCK:
        if repo in _MEMO:
            return _MEMO[repo]
        result, status = None, "error"
        try:
            headers = {"Accept": "application/vnd.github+json",
                       "X-GitHub-Api-Version": API_VERSION, "User-Agent": _USER_AGENT}
            if token:
                headers["Authorization"] = "Bearer {}".format(token)
            request = urllib.request.Request(
                "{}/repos/{}/stargazers/history?per_page=6".format(_API, repo), headers=headers)
            _THROTTLE.wait()
            with urllib.request.urlopen(request, timeout=20) as response:
                status = str(response.status)
                if response.status == 200:
                    result = parse_history(json.loads(response.read()), now=now)
                elif response.status in (403, 429):
                    delay = _retry_after(response.headers)
                    if delay is not None:
                        _THROTTLE.wait_for_retry_after(delay)
        except urllib.error.HTTPError as exc:
            status = str(exc.code)
            if exc.code in (403, 429):
                delay = _retry_after(exc.headers)
                if delay is not None:
                    try:
                        _THROTTLE.wait_for_retry_after(delay)
                    except Exception:
                        pass
        except Exception:
            pass
        _MEMO[repo] = result
        _STATUSES[repo] = status
        return result


def annotate(records, token=None, *, now=None, max_records=None) -> int:
    """Enrich valid repo records serially without making history a source."""
    started = time.monotonic()
    ok, tried, statuses = 0, 0, {}
    for record in records:
        if max_records is not None and tried >= max_records:
            break
        if not isinstance(record, dict):
            continue
        repo = record.get("canonical_repo") or record.get("name")
        if not isinstance(repo, str) or not _REPO.fullmatch(repo):
            continue
        tried += 1
        history = fetch_history(repo, token, now=now)
        with _LOCK:
            status = _STATUSES.get(repo, "ok" if history else "miss")
        statuses[status] = statuses.get(status, 0) + 1
        if history is None:
            continue
        for key in ("signal", "meta"):
            if not isinstance(record.get(key), dict):
                record[key] = {}
        for key in ("stars_7d", "stars_prev_7d", "stars_1d"):
            record["signal"][key] = history[key]
        gains = [value for _, value in history["daily"][-30:]]
        record["meta"]["star_days"] = [0] * (30 - len(gains)) + gains
        ok += 1
    if tried:
        print("star_history: {}/{} repos, {:.0f}s, statuses={}".format(
            ok, tried, time.monotonic() - started, statuses), file=sys.stderr)
    return ok


def seed_observations(cache, records, *, now=None) -> int:
    """One run key per historical day: the observation key has no timestamp."""
    today = int((time.time() if now is None else now) // _DAY) * _DAY
    rows = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        repo = record.get("canonical_repo") or record.get("name")
        signal = record.get("signal") or {}
        meta = record.get("meta") or {}
        if not isinstance(signal, dict) or not isinstance(meta, dict):
            continue
        stars, gains = signal.get("stars"), meta.get("star_days")
        if (not isinstance(repo, str) or not _REPO.fullmatch(repo)
                or type(stars) is not int or type(signal.get("stars_7d")) is not int
                or not isinstance(gains, list) or not gains
                or any(type(v) is not int or v < 0 for v in gains)):
            continue
        cumulative = stars
        for i, gain in enumerate(reversed(gains[-14:]), 1):
            day = today - i * _DAY
            key = "star_history:" + time.strftime("%Y-%m-%d", time.gmtime(day))
            rows[(repo, key)] = {"run_id": key, "entity_type": "repo", "entity_id": repo,
                                 "source": "star_history", "metric": "stars",
                                 "value": float(cumulative), "observed_at": float(day + _DAY)}
            cumulative -= gain
    observations = sorted(rows.values(), key=lambda row: row["observed_at"])
    existing = {(r["entity_id"], r["observed_at"]) for r in cache.recent_observations(today - 14 * _DAY)
                if r["source"] == "star_history" and r["metric"] == "stars"}
    observations = [r for r in observations if (r["entity_id"], r["observed_at"]) not in existing]
    cache.record_observations(observations)
    return len(observations)
