"""In-memory sliding-window rate limiting for failed login attempts.

In-process on purpose: the API runs as a single uvicorn worker with no
shared store. Only failures are counted, so a shared NAT never locks out
unrelated successful logins.
"""

import time
from collections import deque


class LoginRateLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: float = 900.0, max_keys: int = 10_000):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._max_keys = max_keys
        self._failures: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        events = self._failures.get(key)
        if events is None:
            return deque()
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def _sweep(self, now: float) -> None:
        cutoff = now - self.window_seconds
        stale = [k for k, ev in self._failures.items() if not ev or ev[-1] <= cutoff]
        for k in stale:
            del self._failures[k]

    def retry_after(self, key: str) -> float:
        """Seconds until key may attempt again; 0.0 when not blocked."""
        now = time.monotonic()
        events = self._prune(key, now)
        if len(events) < self.max_failures or not events:
            return 0.0
        return max(0.0, self.window_seconds - (now - events[0]))

    def record_failure(self, key: str) -> float:
        """Record one failed attempt; returns retry_after (0 while under the limit)."""
        now = time.monotonic()
        if len(self._failures) >= self._max_keys:
            self._sweep(now)
            if len(self._failures) >= self._max_keys and key not in self._failures:
                # Distinct keys arriving faster than they expire (e.g. an
                # attacker rotating usernames): evict the oldest entry so
                # memory stays bounded.
                oldest = min(self._failures, key=lambda k: self._failures[k][-1])
                del self._failures[oldest]
        events = self._prune(key, now)
        events.append(now)
        self._failures[key] = events
        return self.retry_after(key)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
