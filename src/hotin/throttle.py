"""Shared request pacing for source adapters."""

import random
import time
from typing import Callable, Optional


class Throttle:
    """Ensure requests to a host are spaced by a polite minimum interval."""

    def __init__(
        self,
        min_interval: float,
        jitter: float = 0.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval = min_interval
        self.jitter = jitter
        self._sleep = sleep_fn
        self._clock = clock_fn
        self._last_call: Optional[float] = None

    def _regular_delay(self) -> float:
        if self._last_call is None:
            return 0.0
        elapsed = self._clock() - self._last_call
        interval = self.min_interval + random.uniform(0.0, self.jitter)
        return max(0.0, interval - elapsed)

    def _sleep_and_record(self, delay: float) -> None:
        if delay > 0:
            self._sleep(delay)
        self._last_call = self._clock()

    def wait(self) -> None:
        """Wait as needed before the next request."""
        self._sleep_and_record(self._regular_delay())

    def wait_for_retry_after(self, seconds: float) -> None:
        """Honor a server-requested retry delay without weakening normal pacing."""
        self._sleep_and_record(max(float(seconds), self._regular_delay()))
