"""OPT-1: the per-account REST poll runs on a small worker pool.

Same requests, same results, same pacing; only the wall clock changes.
"""

import io
import json
import threading
import time
import urllib.error

from hotin.sources import _insider_roster as core
from hotin.throttle import Throttle


def _fake_urlopen(counter, threads):
    """Deterministic stars per login; one request per (login, page)."""
    def urlopen(request, timeout=0):
        with counter["lock"]:
            counter["n"] += 1
        threads.add(threading.current_thread().name)
        time.sleep(0.005)  # a little latency so workers actually overlap
        login = request.full_url.split("/users/")[1].split("/")[0]
        if login.endswith("7"):
            raise urllib.error.HTTPError(request.full_url, 404, "gone", {}, io.BytesIO(b""))
        if login.endswith("3"):
            raise urllib.error.HTTPError(request.full_url, 403, "limited", {}, io.BytesIO(b""))
        body = json.dumps([{
            "starred_at": "2099-01-01T00:00:00Z",
            "repo": {"full_name": "org/repo-{}".format(int(login[1:]) % 5),
                     "created_at": "2098-12-01T00:00:00Z",
                     "stargazers_count": 10, "description": "d"},
        }]).encode()

        class Resp:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return body
        return Resp()
    return urlopen


def _run(monkeypatch, workers):
    counter = {"n": 0, "lock": threading.Lock()}
    threads = set()
    monkeypatch.setenv(core._WORKERS_ENV, str(workers))
    monkeypatch.setattr(core.urllib.request, "urlopen", _fake_urlopen(counter, threads))
    monkeypatch.setattr(core._THROTTLE, "wait", lambda: None)
    monkeypatch.setattr(core._THROTTLE, "wait_for_retry_after", lambda *a, **k: None)
    logins = ["u{}".format(i) for i in range(40)]
    results = core._rest_floor(logins, "tok", window_days=45, now=None)
    return results, counter["n"], threads


def test_four_workers_match_serial_exactly_with_the_same_request_count(monkeypatch):
    serial, n_serial, t_serial = _run(monkeypatch, 1)
    pooled, n_pooled, t_pooled = _run(monkeypatch, 4)
    assert pooled == serial
    assert list(pooled) == list(serial)          # roster order, not completion order
    assert n_pooled == n_serial == 40            # budget unchanged
    assert len(t_serial) == 1 and len(t_pooled) > 1
    aggs = core.aggregate_by_repo(
        [e for r in pooled.values() for e in r["events"]])
    assert aggs == core.aggregate_by_repo(
        [e for r in serial.values() for e in r["events"]])
    outcomes = {r["outcome"] for r in pooled.values()}
    assert outcomes == {core._gql.OK, core._gql.RATE_LIMITED}


def test_garbage_worker_env_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(core._WORKERS_ENV, "lots")
    assert core._workers() == core._DEFAULT_WORKERS
    monkeypatch.setenv(core._WORKERS_ENV, "0")
    assert core._workers() == 1


def test_throttle_pacing_holds_across_threads():
    """Without the lock, 4 threads overlap their sleeps and finish ~4x early."""
    throttle = Throttle(min_interval=0.01)
    def worker():
        for _ in range(10):
            throttle.wait()
    threads = [threading.Thread(target=worker) for _ in range(4)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.monotonic() - t0 >= 39 * 0.01
