"""Tests for InMemoryCache."""

from __future__ import annotations

import pytest

from companylens.clients.cache import InMemoryCache


@pytest.mark.asyncio
async def test_set_and_get_hit() -> None:
    """Value stored with set() is returned by get()."""
    cache = InMemoryCache(ttl_seconds=60)
    key = ("get_company_profile", "abc123")
    value = {"status": "active"}

    await cache.set(key, value)
    result = await cache.get(key)

    assert result == value


@pytest.mark.asyncio
async def test_get_miss_unknown_key() -> None:
    """get() returns None for a key that was never set."""
    cache = InMemoryCache(ttl_seconds=60)
    result = await cache.get(("search_companies", "neversetkey"))
    assert result is None


@pytest.mark.asyncio
async def test_ttl_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entries expire after TTL and get() returns None."""
    import time

    cache = InMemoryCache(ttl_seconds=1)
    key = ("get_psc", "ttlkey")
    await cache.set(key, {"total_count": 1})

    # Advance time past TTL by patching monotonic
    original = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: original() + 2.0)

    result = await cache.get(key)
    assert result is None


@pytest.mark.asyncio
async def test_overwrite_refreshes_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-setting a key resets its TTL."""
    import time

    cache = InMemoryCache(ttl_seconds=5)
    key = ("get_charges", "chargekey")

    await cache.set(key, {"total": 2})

    # Advance time by 3s — still within first TTL
    original = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: original() + 3.0)

    # Overwrite with a new TTL from "now" (3s ahead)
    await cache.set(key, {"total": 3})

    # Advance another 4s = 7s total. Original would have expired; new shouldn't.
    monkeypatch.setattr(time, "monotonic", lambda: original() + 7.0)

    result = await cache.get(key)
    assert result == {"total": 3}


@pytest.mark.asyncio
async def test_independent_keys() -> None:
    """Different keys don't interfere with each other."""
    cache = InMemoryCache(ttl_seconds=60)
    key_a = ("tool_a", "hash1")
    key_b = ("tool_b", "hash2")

    await cache.set(key_a, "value_a")
    await cache.set(key_b, "value_b")

    assert await cache.get(key_a) == "value_a"
    assert await cache.get(key_b) == "value_b"
