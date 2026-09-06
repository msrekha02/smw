"""Redis: quote cache and the single-flight lock.

Locks live in their own logical DB. Under `allkeys-lru` the lock keys are
evictable and stampede protection silently stops working under memory pressure
-- which is exactly when it is needed. The lock DB should be configured
`noeviction`; `docker-compose.yml` sets that.

Every call degrades to a no-op if Redis is unreachable. Redis being down must
make the system slower, not wrong: reads fall through to Postgres and acks are
untouched.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import redis.asyncio as aioredis

from api.config import (
    QUOTE_CACHE_TTL_S,
    SINGLE_FLIGHT_LOCK_S,
    SINGLE_FLIGHT_WAIT_S,
    settings,
)

_data: aioredis.Redis | None = None
_locks: aioredis.Redis | None = None
_down_until: float = 0.0


def _client(url: str) -> aioredis.Redis:
    return aioredis.from_url(url, decode_responses=True, socket_timeout=1.5)


def data() -> aioredis.Redis:
    global _data
    if _data is None:
        _data = _client(settings.redis_url)
    return _data


def locks() -> aioredis.Redis:
    global _locks
    if _locks is None:
        _locks = _client(settings.redis_lock_url)
    return _locks


async def close() -> None:
    """Drop the clients and clear the circuit breaker.

    Clearing `_down_until` matters: a client closed underneath an in-flight
    call trips the breaker, and a stale trip would silently disable stampede
    protection for the next five seconds of a fresh connection's life.
    """
    global _data, _locks, _down_until
    for c in (_data, _locks):
        if c is not None:
            try:
                await c.aclose()
            except Exception:
                pass
    _data = _locks = None
    _down_until = 0.0


def _mark_down() -> None:
    global _down_until
    _down_until = time.monotonic() + 5.0


def _is_down() -> bool:
    return time.monotonic() < _down_until


async def ping() -> bool:
    try:
        return bool(await data().ping())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Quote cache
# ---------------------------------------------------------------------------


def quote_key(ticker: str) -> str:
    return f"q:{ticker.upper()}"


async def get_quote(ticker: str) -> dict[str, Any] | None:
    if _is_down():
        return None
    try:
        raw = await data().get(quote_key(ticker))
    except Exception:
        _mark_down()
        return None
    return json.loads(raw) if raw else None


async def set_quote(ticker: str, payload: dict[str, Any], ttl: int = QUOTE_CACHE_TTL_S) -> None:
    if _is_down():
        return
    try:
        await data().set(quote_key(ticker), json.dumps(payload), ex=ttl)
    except Exception:
        _mark_down()


# ---------------------------------------------------------------------------
# Single flight
# ---------------------------------------------------------------------------


class SingleFlight:
    """`SET NX` around a fetch, so 400 simultaneous requests on one expired
    popular key produce exactly one provider call.

    Losers wait on the holder rather than queueing their own call; if the holder
    has not published within `wait_s` they return None and the caller serves
    whatever it already has. Blocking a user's digest on a provider is worse
    than showing them a price with an honest age on it.
    """

    def __init__(self, key: str, ttl_s: int = SINGLE_FLIGHT_LOCK_S):
        self.key = f"lock:{key}"
        self.ttl_s = ttl_s
        self.token = uuid.uuid4().hex
        self.acquired = False

    async def __aenter__(self) -> "SingleFlight":
        if _is_down():
            self.acquired = True  # no Redis: everyone fetches, correctness intact
            return self
        try:
            self.acquired = bool(
                await locks().set(self.key, self.token, nx=True, ex=self.ttl_s)
            )
        except Exception:
            _mark_down()
            self.acquired = True
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if not self.acquired or _is_down():
            return
        try:
            # Only release a lock we still hold: a slow fetch whose lock expired
            # must not delete the next holder's.
            script = (
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end"
            )
            await locks().eval(script, 1, self.key, self.token)
        except Exception:
            _mark_down()


async def wait_for(ticker: str, wait_s: float = SINGLE_FLIGHT_WAIT_S) -> dict[str, Any] | None:
    """Poll the cache while another caller holds the lock."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        got = await get_quote(ticker)
        if got is not None:
            return got
    return None


# ---------------------------------------------------------------------------
# Digest ETag
# ---------------------------------------------------------------------------


async def get_etag(user_id: uuid.UUID) -> str | None:
    if _is_down():
        return None
    try:
        return await data().get(f"etag:{user_id}")
    except Exception:
        _mark_down()
        return None


async def set_etag(user_id: uuid.UUID, etag: str, body: str, ttl: int = 120) -> None:
    if _is_down():
        return
    try:
        pipe = data().pipeline()
        pipe.set(f"etag:{user_id}", etag, ex=ttl)
        pipe.set(f"body:{user_id}:{etag}", body, ex=ttl)
        await pipe.execute()
    except Exception:
        _mark_down()


async def get_body(user_id: uuid.UUID, etag: str) -> str | None:
    if _is_down():
        return None
    try:
        return await data().get(f"body:{user_id}:{etag}")
    except Exception:
        _mark_down()
        return None
