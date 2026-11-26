"""Async token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Token-bucket rate limiter.

    Args:
        rate: Tokens added per second.
        capacity: Maximum token capacity (burst size).
    """

    def __init__(self, rate: float, capacity: float) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens: float = capacity
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    async def acquire(self) -> None:
        """Block until one token is available, then consume it."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Calculate how long to wait for the next token
                wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)
