"""Per-IP sliding-window rate limiter (client IP read behind a proxy)."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.requests import Request


def client_ip(request: Request) -> str:
    """Return the client IP, preferring the first X-Forwarded-For entry."""
    xff = request.headers.get("x-forwarded-for", "")
    first = xff.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


class SlidingWindowLimiter:
    """Allow at most ``limit`` hits per ``window`` seconds per key."""

    def __init__(self, limit: int = 10, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record a hit for key and return False if it exceeds the window limit."""
        t = time.monotonic() if now is None else now
        if len(self._hits) > 10_000:
            self._hits = defaultdict(
                deque, {k: v for k, v in self._hits.items() if v and t - v[-1] < self.window}
            )
        q = self._hits[key]
        while q and t - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(t)
        return True
