"""On-demand quotes: the cold tier.

Two paths, not three. Round-robin polling spends budget refreshing prices nobody
is looking at, so everything outside the top 50 is fetched only when someone
opens a list containing it, and then cached for 60 seconds.

Cost is O(distinct tickers being viewed), never O(users x tickers): a ticker on
400 watchlists costs one fetch per 60s. The single-flight lock is what makes
that true under load -- without it, 400 simultaneous requests on an expired
popular key each spend a provider call at precisely the moment that ticker is
moving and the budget matters most.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import cache, clock
from api.db import session_scope
from api.calendar_ny import get_calendar
from api.config import QUOTE_CACHE_TTL_S
from providers import get_providers
from providers.base import ProviderError, Quote
from worker.intraday.sanity import SanityState, check

log = logging.getLogger("smw.ondemand")


def _to_payload(q: Quote, status: str, extended: float | None) -> dict:
    return {
        "ticker": q.ticker,
        "price": q.price,
        "prev_close": q.prev_close,
        "day_volume": q.day_volume,
        "is_extended_hours": q.is_extended_hours,
        "extended_price": extended,
        "source": q.source,
        "fetched_at": q.at.isoformat(),
        "status": status,
    }


async def _load_state(session: AsyncSession, ticker: str) -> SanityState:
    row = (
        await session.execute(
            text(
                "SELECT price, prev_close, pending_price, pending_since, pending_cycles"
                " FROM ticker_latest WHERE ticker = :t"
            ),
            {"t": ticker},
        )
    ).first()
    if row is None:
        return SanityState()
    return SanityState(row[0], row[1], row[2], row[3], int(row[4] or 0))


async def _persist(session: AsyncSession, payload: dict, sanity) -> None:
    await session.execute(
        text(
            """
        INSERT INTO ticker_latest (
            ticker, price, prev_close, day_volume, is_extended_hours, source,
            fetched_at, extended_price, status, pending_price, pending_since,
            pending_cycles)
        VALUES (:t, :px, :pc, :vol, :ext, :src, :at, :extpx, :status, :ppx,
                -- Casts are load-bearing: asyncpg infers a single type per
                -- placeholder, and :at appears as both a column value and a
                -- CASE branch, which it reports as an ambiguous parameter.
                CASE WHEN CAST(:ppx AS double precision) IS NULL
                     THEN NULL ELSE CAST(:at AS timestamptz) END, :pcyc)
        ON CONFLICT (ticker) DO UPDATE SET
            price = COALESCE(EXCLUDED.price, ticker_latest.price),
            prev_close = COALESCE(EXCLUDED.prev_close, ticker_latest.prev_close),
            day_volume = COALESCE(EXCLUDED.day_volume, ticker_latest.day_volume),
            is_extended_hours = EXCLUDED.is_extended_hours,
            source = EXCLUDED.source,
            fetched_at = EXCLUDED.fetched_at,
            extended_price = EXCLUDED.extended_price,
            status = EXCLUDED.status,
            pending_price = EXCLUDED.pending_price,
            pending_since = COALESCE(ticker_latest.pending_since, EXCLUDED.pending_since),
            pending_cycles = EXCLUDED.pending_cycles
        """
        ),
        {
            "t": payload["ticker"],
            "px": payload["price"],
            "pc": payload["prev_close"],
            "vol": payload["day_volume"],
            "ext": payload["is_extended_hours"],
            "src": payload["source"],
            "at": dt.datetime.fromisoformat(payload["fetched_at"]),
            "extpx": payload["extended_price"],
            "status": payload["status"],
            "ppx": sanity.pending_price,
            "pcyc": sanity.pending_cycles,
        },
    )


async def fetch_one(ticker: str, ensure_db: bool = False) -> dict | None:
    """Cache -> single-flight -> provider. Never raises upward.

    Opens its own session: `refresh` runs these concurrently, and an
    `AsyncSession` is not safe to share across tasks.

    `ensure_db` writes a cache hit through to `ticker_latest` instead of
    returning it straight away. The digest reads prices from the table, not from
    Redis, so a row that goes missing while the cache is still warm would show
    `no_data` for a full TTL and never self-heal -- the refresh would find the
    value in Redis, return happily, and write nothing. It costs one upsert, and
    only in the recovery case.
    """
    t = ticker.upper()
    hit = await cache.get_quote(t)
    if hit is not None:
        if ensure_db:
            async with session_scope() as session:
                await _persist(session, hit, SanityState())
        return hit

    async with cache.SingleFlight(f"q:{t}") as sf:
        if not sf.acquired:
            waited = await cache.wait_for(t)
            if waited is not None:
                return waited
            return None

        again = await cache.get_quote(t)
        if again is not None:
            return again

        try:
            q = await get_providers().quotes.quote(t)
        except (ProviderError, KeyError) as e:
            log.info("quote %s failed: %s", t, e)
            return None

        async with session_scope(direct=False) as session:
            return await _apply(session, q, t)


async def _apply(session: AsyncSession, q, t: str) -> dict:
    st = await _load_state(session, t)
    res = check(q.price, st, clock.now())

    # Extended-hours prices are DISPLAYED, never scored. After-hours
    # volatility needs its own calibration, and a thin 4am print would
    # score 3 sigma on no volume. But suppressing it entirely means the
    # system looks quietest at the most information-dense moment there is.
    extended = q.price if q.is_extended_hours else None
    scoreable = None if q.is_extended_hours else res.price

    payload = _to_payload(q, res.status, extended)
    if scoreable is not None:
        payload["price"] = scoreable
    elif q.is_extended_hours:
        cal = get_calendar()
        last = cal.current_or_last_session(q.at)
        row = (
            await session.execute(
                text("SELECT close FROM ticker_daily_bar WHERE ticker=:t AND bar_date=:d"),
                {"t": t, "d": last},
            )
        ).scalar()
        payload["price"] = float(row) if row is not None else q.price
        payload["source"] = "eod"
    else:
        payload["price"] = st.last_good

    await _persist(session, payload, res)
    await cache.set_quote(t, payload, QUOTE_CACHE_TTL_S)
    return payload


async def refresh(
    tickers: Sequence[str],
    budget_s: float = 2.0,
    ensure_db: Sequence[str] | None = None,
) -> dict[str, dict]:
    """Refresh what is stale, bounded by a wall-clock budget.

    A digest that blocks on a provider is worse than a digest that shows a price
    with an honest age on it, so this returns whatever finished in time.

    `ensure_db` names the tickers with no stored row at all, which must be
    written through even on a cache hit.
    """
    todo = [t.upper() for t in dict.fromkeys(tickers)]
    if not todo:
        return {}
    missing = {t.upper() for t in (ensure_db or ())}
    out: dict[str, dict] = {}

    async def one(t: str) -> None:
        got = await fetch_one(t, ensure_db=t in missing)
        if got:
            out[t] = got

    try:
        await asyncio.wait_for(
            asyncio.gather(*(one(t) for t in todo), return_exceptions=True),
            timeout=budget_s,
        )
    except (TimeoutError, asyncio.TimeoutError):
        log.info("on-demand refresh hit its %.1fs budget (%d symbols)", budget_s, len(todo))
    return out
