"""Tests for the async token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from companylens.clients.ratelimit import RateLimiter


@pytest.mark.asyncio
async def test_consecutive_acquires_timing() -> None:
    """Consecutive acquires should not take longer than 1.5x the expected time."""
    # 2 tokens/sec, capacity=1 so burst of 1 token only
    limiter = RateLimiter(rate=2.0, capacity=1.0)

    # Drain the initial token
    await limiter.acquire()

    # Next 2 acquires require new tokens; each takes ~0.5s at rate=2
    expected_total = 2 * 0.5  # 1.0 s
    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.monotonic() - start

    assert elapsed <= expected_total * 1.5, (
        f"Took {elapsed:.2f}s, expected ≤ {expected_total * 1.5:.2f}s"
    )


@pytest.mark.asyncio
async def test_burst_limit_respected() -> None:
    """Burst should be limited to capacity; excess tokens must wait."""
    capacity = 3.0
    rate = 10.0  # fast refill so waits are short in CI
    limiter = RateLimiter(rate=rate, capacity=capacity)

    # First 'capacity' acquires should be near-instant (tokens already available)
    start = time.monotonic()
    for _ in range(int(capacity)):
        await limiter.acquire()
    burst_elapsed = time.monotonic() - start

    # Burst should finish well under 0.3s
    assert burst_elapsed < 0.3, f"Burst took {burst_elapsed:.2f}s, expected < 0.3s"

    # Next acquire must wait for a new token (~1/rate seconds)
    start = time.monotonic()
    await limiter.acquire()
    wait_elapsed = time.monotonic() - start

    min_wait = 1.0 / rate * 0.5  # allow 50% slack
    assert wait_elapsed >= min_wait, (
        f"Did not wait for token: {wait_elapsed:.3f}s, expected ≥ {min_wait:.3f}s"
    )


@pytest.mark.asyncio
async def test_concurrent_acquires_serialize() -> None:
    """Concurrent callers should not get tokens faster than the rate."""
    rate = 5.0
    capacity = 1.0
    limiter = RateLimiter(rate=rate, capacity=capacity)

    results: list[float] = []

    async def grab() -> None:
        await limiter.acquire()
        results.append(time.monotonic())

    start = time.monotonic()
    await asyncio.gather(*[grab() for _ in range(4)])
    total = time.monotonic() - start

    # 4 tokens at 5/sec = at least 0.6s (3 waits)
    assert total >= 0.6 * 0.7, f"Concurrent acquires finished too fast: {total:.2f}s"
