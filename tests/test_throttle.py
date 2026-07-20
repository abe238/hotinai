from hotin.throttle import Throttle


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_wait_enforces_minimum_interval_when_clock_has_not_advanced():
    fake_time = FakeTime()
    throttle = Throttle(2.0, sleep_fn=fake_time.sleep, clock_fn=fake_time.clock)

    throttle.wait()
    throttle.wait()

    assert fake_time.sleeps[-1] >= 2.0


def test_wait_skips_sleep_when_clock_has_already_advanced():
    fake_time = FakeTime()
    throttle = Throttle(2.0, sleep_fn=fake_time.sleep, clock_fn=fake_time.clock)

    throttle.wait()
    fake_time.now += 3.0
    throttle.wait()

    assert fake_time.sleeps == []


def test_wait_adds_jitter_to_repeated_calls(monkeypatch):
    fake_time = FakeTime()
    delays = iter((0.1, 0.4, 0.2))
    monkeypatch.setattr("hotin.throttle.random.uniform", lambda start, end: next(delays))
    throttle = Throttle(2.0, jitter=0.5, sleep_fn=fake_time.sleep, clock_fn=fake_time.clock)

    throttle.wait()
    throttle.wait()
    throttle.wait()
    throttle.wait()

    assert len(set(fake_time.sleeps)) > 1
    assert all(2.0 <= seconds <= 2.5 for seconds in fake_time.sleeps)


def test_retry_after_never_sleeps_less_than_server_requested_delay():
    fake_time = FakeTime()
    throttle = Throttle(2.0, sleep_fn=fake_time.sleep, clock_fn=fake_time.clock)

    throttle.wait()
    throttle.wait_for_retry_after(30)

    assert fake_time.sleeps[-1] >= 30
