"""Two-layer cache: in-memory with TTL and optional disk backing."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import diskcache  # type: ignore[import-untyped]


class InMemoryCache:
    """Asyncio-safe in-memory cache with TTL.

    Keys are (tool_name, args_hash) tuples.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: dict[tuple[str, str], tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: tuple[str, str]) -> Any | None:
        """Return cached value or None if missing/expired."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    async def set(self, key: tuple[str, str], value: Any) -> None:
        """Store a value with TTL."""
        async with self._lock:
            self._store[key] = (value, time.monotonic() + self._ttl)


class DiskCache:
    """Disk-backed cache using diskcache, intended for eval runs.

    Keys are (tool_name, args_hash) tuples.
    """

    def __init__(self, directory: str, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._cache: diskcache.Cache = diskcache.Cache(directory)

    async def get(self, key: tuple[str, str]) -> Any | None:
        """Return cached value or None if missing/expired."""
        str_key = f"{key[0]}:{key[1]}"
        value = self._cache.get(str_key, default=None)
        return value  # diskcache handles TTL via expire parameter

    async def set(self, key: tuple[str, str], value: Any) -> None:
        """Store a value with TTL."""
        str_key = f"{key[0]}:{key[1]}"
        self._cache.set(str_key, value, expire=self._ttl)

    def close(self) -> None:
        """Close the underlying diskcache."""
        self._cache.close()


class CacheLayer:
    """Combined cache: check memory first, fall back to disk.

    Args:
        memory: In-memory cache (always used).
        disk: Optional disk cache (used during eval runs).
    """

    def __init__(self, memory: InMemoryCache, disk: DiskCache | None = None) -> None:
        self._memory = memory
        self._disk = disk

    async def get(self, key: tuple[str, str]) -> Any | None:
        """Return cached value from memory or disk, or None on miss."""
        value = await self._memory.get(key)
        if value is not None:
            return value
        if self._disk is not None:
            value = await self._disk.get(key)
            if value is not None:
                # Backfill memory from disk
                await self._memory.set(key, value)
                return value
        return None

    async def set(self, key: tuple[str, str], value: Any) -> None:
        """Store a value in both memory and disk (if configured)."""
        await self._memory.set(key, value)
        if self._disk is not None:
            await self._disk.set(key, value)
