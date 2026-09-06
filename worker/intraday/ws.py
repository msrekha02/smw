"""The hot tier: a WebSocket over the top 50 tickers by watcher count.

Finnhub's free WebSocket caps at 50 symbols, which is the reason membership is
by refcount rather than round-robin. Watchlists concentrate heavily in
mega-caps, so 50 symbols covers a large share of what anyone is actually
looking at, and everything else falls to the on-demand tier at 60s.

Ticks are buffered and flushed to `ticker_latest` in one batched upsert every
five seconds. A per-tick write would turn a busy open into a write storm for
data that is overwritten seconds later.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy import text

from api import cache, clock
from api.config import QUOTE_CACHE_TTL_S, WS_FLUSH_S, WS_SYMBOL_CAP
from api.db import session_scope
from providers import get_providers
from worker.intraday.sanity import SanityState, check

log = logging.getLogger("smw.ws")


async def hot_symbols(limit: int = WS_SYMBOL_CAP) -> list[str]:
    """Top N by watcher count. Ties broken by ticker so membership is stable
    and does not churn subscriptions every refresh."""
    async with session_scope() as session:
        rows = (
            await session.execute(
                text(
                    """
            SELECT w.ticker, count(*) AS refcount
              FROM watchlist_items w
              JOIN tickers t ON t.ticker = w.ticker
             WHERE t.status = 'active'
             GROUP BY w.ticker
             ORDER BY refcount DESC, w.ticker ASC
             LIMIT :n
            """
                ),
                {"n": limit},
            )
        ).all()
    return [r[0] for r in rows]


class TickBuffer:
    """Last tick wins, per symbol, inside one flush interval."""

    def __init__(self) -> None:
        self._buf: dict[str, tuple[float, dt.datetime, int | None]] = {}

    def add(self, ticker: str, price: float, at: dt.datetime, volume: int | None) -> None:
        self._buf[ticker.upper()] = (price, at, volume)

    def drain(self) -> dict[str, tuple[float, dt.datetime, int | None]]:
        out, self._buf = self._buf, {}
        return out


async def flush(buf: TickBuffer) -> int:
    batch = buf.drain()
    if not batch:
        return 0

    async with session_scope() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT ticker, price, prev_close, pending_price, pending_since,"
                    " pending_cycles FROM ticker_latest WHERE ticker = ANY(:ts)"
                ),
                {"ts": list(batch)},
            )
        ).all()
        state = {
            r[0]: SanityState(r[1], r[2], r[3], r[4], int(r[5] or 0)) for r in rows
        }

        params = []
        for t, (px, at, vol) in batch.items():
            st = state.get(t, SanityState())
            res = check(px, st, clock.now())
            if res.verdict == "hold":
                params.append(
                    {
                        "t": t, "px": None, "vol": vol, "at": at,
                        "status": "verifying", "ppx": res.pending_price,
                        "pcyc": res.pending_cycles,
                    }
                )
                continue
            params.append(
                {
                    "t": t, "px": res.price, "vol": vol, "at": at,
                    "status": res.status, "ppx": None, "pcyc": 0,
                }
            )
            await cache.set_quote(
                t,
                {
                    "ticker": t, "price": res.price, "prev_close": st.prev_close,
                    "day_volume": vol, "is_extended_hours": False,
                    "extended_price": None, "source": "ws",
                    "fetched_at": at.isoformat(), "status": res.status,
                },
                QUOTE_CACHE_TTL_S,
            )

        await session.execute(
            text(
                """
            INSERT INTO ticker_latest (ticker, price, day_volume, source,
                                       fetched_at, status, pending_price,
                                       pending_since, pending_cycles)
            VALUES (:t, :px, :vol, 'ws', :at, :status, :ppx,
                    CASE WHEN CAST(:ppx AS double precision) IS NULL
                         THEN NULL ELSE CAST(:at AS timestamptz) END, :pcyc)
            ON CONFLICT (ticker) DO UPDATE SET
                price = COALESCE(EXCLUDED.price, ticker_latest.price),
                day_volume = COALESCE(EXCLUDED.day_volume, ticker_latest.day_volume),
                source = 'ws',
                fetched_at = EXCLUDED.fetched_at,
                status = EXCLUDED.status,
                pending_price = EXCLUDED.pending_price,
                pending_since = COALESCE(ticker_latest.pending_since,
                                         EXCLUDED.pending_since),
                pending_cycles = EXCLUDED.pending_cycles
            """
            ),
            params,
        )
    return len(params)


async def run(refresh_membership_s: int = 300) -> None:
    """Subscribe, buffer, flush. Falls back to on-demand simply by stopping:
    a symbol with no fresh WS write ages past its freshness threshold and the
    digest path refreshes it through the cold tier on the next view.
    """
    quotes = get_providers().quotes
    if not getattr(quotes, "supports_stream", False):
        log.warning("quote provider has no stream; hot tier disabled")
        return

    while True:
        symbols = await hot_symbols()
        if not symbols:
            await asyncio.sleep(30)
            continue

        buf = TickBuffer()
        stop = asyncio.Event()

        async def pump() -> None:
            try:
                async for tick in quotes.stream(symbols):
                    buf.add(tick.ticker, tick.price, tick.at, tick.volume)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ws stream ended")
            finally:
                stop.set()

        async def flusher() -> None:
            while not stop.is_set():
                await asyncio.sleep(WS_FLUSH_S)
                try:
                    await flush(buf)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("tick flush failed")

        task_pump = asyncio.create_task(pump())
        task_flush = asyncio.create_task(flusher())
        try:
            await asyncio.wait(
                [task_pump, task_flush],
                timeout=refresh_membership_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in (task_pump, task_flush):
                t.cancel()
            await asyncio.gather(task_pump, task_flush, return_exceptions=True)
            await flush(buf)
