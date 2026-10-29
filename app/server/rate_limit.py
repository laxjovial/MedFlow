"""Small process-local sliding-window limiter for sensitive API routes.

This is suitable as a first layer for a single MedFlow server process. It is not
shared between multiple worker processes or replicas; those deployments need
a shared gateway/store-backed limiter.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowRateLimiter:
    """Thread-safe fixed-key sliding window with bounded stale-key cleanup."""

    def __init__(self, *, max_keys: int = 10_000) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys
        self._operations = 0

    def consume(
        self, key: str, *, limit: int, window_seconds: int,
        now: float | None = None,
    ) -> int | None:
        """Record one attempt; return retry-after seconds when over limit."""
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be positive")
        moment = time.monotonic() if now is None else now
        cutoff = moment - window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(1, int(events[0] + window_seconds - moment + 0.999))
            events.append(moment)
            self._operations += 1
            # Amortized cleanup keeps old client keys from growing forever.
            if self._operations % 128 == 0:
                for stale_key in list(self._events):
                    queue = self._events[stale_key]
                    while queue and queue[0] <= cutoff:
                        queue.popleft()
                    if not queue:
                        self._events.pop(stale_key, None)
                if len(self._events) > self._max_keys:
                    # Drop oldest insertion-ordered keys as a bounded-memory fallback.
                    for stale_key in list(self._events)[:len(self._events) - self._max_keys]:
                        self._events.pop(stale_key, None)
            return None
