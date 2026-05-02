"""Caching utilities for BRIDGE performance optimization."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, Optional

try:
    from redis.asyncio import Redis
except Exception:  # pragma: no cover - optional import
    Redis = Any


class TTLCache:
    """Simple in-memory TTL cache."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._store: Dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl_seconds
        self._store[key] = (time.time() + ttl, value)


class RequestCoalescer:
    """Coalesce concurrent requests for the same key."""

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}

    def lock_for(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]


class RedisCache:
    """Redis-backed cache with JSON serialization."""

    def __init__(self, client: Optional[Redis]) -> None:
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def get_json(self, key: str) -> Optional[Any]:
        if not self._client:
            return None
        raw = await self._client.get(key)
        if not raw:
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        if not self._client:
            return
        await self._client.set(key, json.dumps(value), ex=ttl_seconds)


async def create_redis_client() -> Optional[Redis]:
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(url, decode_responses=True)
        await client.ping()
        return client
    except Exception:
        return None
