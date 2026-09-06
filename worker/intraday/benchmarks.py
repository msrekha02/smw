"""Benchmark poller.

The 11 sector ETFs plus SPY, every 60 seconds, unconditionally. They must be
fresher than the stocks they anchor: a stale benchmark mis-attributes a sector
move to the stock, which is the one error this whole system exists to avoid.

Twelve symbols a minute against a 45/min budget is affordable precisely because
it is a fixed cost that does not grow with users.
"""
from __future__ import annotations

import asyncio
import logging

from api import cache, clock
from api.calendar_ny import get_calendar
from api.config import BENCHMARK_POLL_S, BENCHMARK_UNIVERSE, QUOTE_CACHE_TTL_S
from api.db import session_scope
from providers import get_providers
from providers.base import ProviderError
from worker.intraday.ondemand import _apply

log = logging.getLogger("smw.benchmarks")


async def poll_once() -> int:
    prov = get_providers().quotes
    done = 0
    for t in BENCHMARK_UNIVERSE:
        try:
            q = await prov.quote(t)
        except (ProviderError, KeyError) as e:
            log.info("benchmark %s: %s", t, e)
            continue
        async with session_scope() as session:
            payload = await _apply(session, q, t)
        await cache.set_quote(t, payload, QUOTE_CACHE_TTL_S)
        done += 1
    return done


async def run() -> None:
    cal = get_calendar()
    settled = False
    while True:
        try:
            if cal.is_open(clock.now()):
                n = await poll_once()
                settled = False
                log.debug("refreshed %d benchmarks", n)
            elif not settled:
                # One pass after the close pins the settled price. After that,
                # polling a closed market spends budget to learn nothing.
                await poll_once()
                settled = True
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("benchmark poll failed")
        await asyncio.sleep(BENCHMARK_POLL_S)
