"""The live layer: stampede protection, the sanity filter, extended hours."""
from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from sqlalchemy import text

from api import cache, clock
from api.calendar_ny import ET, UTC, get_calendar
from api.config import SANITY_HOLD_CYCLES, SANITY_JUMP
from worker.intraday.sanity import SanityState, check

# No module-level asyncio mark: this file mixes async integration tests with
# synchronous ones for the sanity filter, and `asyncio_mode = auto` already
# picks up the coroutines.


# ---------------------------------------------------------------------------
# Single flight
# ---------------------------------------------------------------------------


async def test_concurrent_requests_on_one_expired_key_make_one_provider_call(db):
    """Without this, 400 simultaneous requests on an expired popular key each
    spend a provider call at precisely the moment that ticker is moving."""
    from providers import get_providers, reset_providers
    from worker.intraday import ondemand

    await db.run_migrations(direct=True)
    async with db.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO tickers (ticker, instrument_class, benchmark_ticker,"
                " status) VALUES ('AAPL','stock','XLK','active')"
                " ON CONFLICT DO NOTHING"
            )
        )

    if not await cache.ping():
        pytest.skip("no Redis; the lock degrades to per-caller fetch by design")

    await cache.data().delete(cache.quote_key("AAPL"))
    await cache.locks().delete("lock:q:AAPL")

    reset_providers()
    prov = get_providers().quotes
    calls = {"n": 0}
    original = prov.quote

    async def counting(ticker: str):
        calls["n"] += 1
        # Long enough that every loser really does contend for the lock, short
        # enough to stay well inside SINGLE_FLIGHT_LOCK_S: if the holder
        # outlived its own lock, a second caller could legitimately acquire it.
        await asyncio.sleep(0.05)
        return await original(ticker)

    prov.quote = counting  # type: ignore[method-assign]
    try:
        results = await asyncio.gather(
            *(ondemand.fetch_one("AAPL") for _ in range(200))
        )
    finally:
        prov.quote = original  # type: ignore[method-assign]

    assert calls["n"] == 1, f"{calls['n']} provider calls for 200 requests"
    served = [r for r in results if r is not None]
    assert served, "the losers must be served, not dropped"
    prices = {r["price"] for r in served}
    assert len(prices) == 1, "everyone sees the same price"


async def test_a_cache_hit_makes_no_provider_call_at_all(db):
    from providers import get_providers, reset_providers
    from worker.intraday import ondemand

    if not await cache.ping():
        pytest.skip("no Redis")
    await db.run_migrations(direct=True)
    async with db.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO tickers (ticker, instrument_class, benchmark_ticker,"
                " status) VALUES ('MSFT','stock','XLK','active')"
                " ON CONFLICT DO NOTHING"
            )
        )

    await cache.data().delete(cache.quote_key("MSFT"))
    reset_providers()
    await ondemand.fetch_one("MSFT")

    prov = get_providers().quotes
    calls = {"n": 0}
    original = prov.quote

    async def counting(ticker: str):
        calls["n"] += 1
        return await original(ticker)

    prov.quote = counting  # type: ignore[method-assign]
    try:
        for _ in range(20):
            assert await ondemand.fetch_one("MSFT") is not None
    finally:
        prov.quote = original  # type: ignore[method-assign]

    assert calls["n"] == 0, "a ticker on 400 watchlists costs one fetch per TTL"


# ---------------------------------------------------------------------------
# Sanity filter
# ---------------------------------------------------------------------------


def test_a_normal_tick_is_accepted():
    st = SanityState(last_good=100.0, prev_close=99.0)
    r = check(101.0, st, clock.now())
    assert r.verdict == "accept"
    assert r.status == "ok"


def test_a_non_positive_price_is_no_data():
    st = SanityState(last_good=100.0, prev_close=99.0)
    assert check(0.0, st, clock.now()).status == "no_data"
    assert check(None, st, clock.now()).status == "no_data"


def test_an_overnight_gap_is_not_corruption():
    """A stock that gapped disagrees with prev_close but not with the last good
    print, so it must not be quarantined."""
    st = SanityState(last_good=100.0, prev_close=70.0)
    assert check(101.0, st, clock.now()).verdict == "accept"


def test_an_implausible_tick_is_held_for_one_cycle_then_released():
    """Held, not dropped: the hold times out so a real gap eventually gets
    through, and the worst case is one wrong card for one poll cycle."""
    now = clock.now()
    st = SanityState(last_good=100.0, prev_close=100.0)
    bad = 100.0 * (1 + SANITY_JUMP * 3)

    first = check(bad, st, now)
    assert first.verdict == "hold"
    assert first.status == "verifying"
    assert first.price is None

    st.pending_price = first.pending_price
    st.pending_cycles = first.pending_cycles
    st.pending_since = now

    # The same suspicious level repeatedly is news, not corruption.
    for _ in range(SANITY_HOLD_CYCLES):
        res = check(bad, st, now)
        st.pending_cycles = res.pending_cycles or st.pending_cycles
        if res.verdict == "accept":
            break
    assert res.verdict == "accept"
    assert res.price == bad


def test_a_stale_hold_times_out():
    now = clock.now()
    st = SanityState(
        last_good=100.0,
        prev_close=100.0,
        pending_price=999.0,
        pending_since=now - dt.timedelta(minutes=10),
    )
    res = check(180.0, st, now)
    assert res.verdict == "accept"
    assert res.note == "hold timed out"


# ---------------------------------------------------------------------------
# Extended hours
# ---------------------------------------------------------------------------


async def test_extended_hours_is_displayed_but_never_scored(db):
    """After-hours volatility needs its own calibration and a thin 4am print
    would score 3 sigma on no volume. But suppressing it entirely means the
    system looks quietest at the most information-dense moment there is."""
    import os

    from providers import reset_providers
    from providers.replay import clear_caches
    from worker.intraday import ondemand

    await db.run_migrations(direct=True)
    cal = get_calendar()
    session = dt.date(2025, 9, 2)
    async with db.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO tickers (ticker, instrument_class, benchmark_ticker,"
                " status) VALUES ('NVDA','stock','XLK','active')"
                " ON CONFLICT DO NOTHING"
            )
        )
        await s.execute(
            text(
                "INSERT INTO ticker_daily_bar (ticker,bar_date,open,high,low,close,volume)"
                " VALUES ('NVDA',:d,170,178,169,176,1000)"
                " ON CONFLICT (ticker,bar_date) DO UPDATE SET close = EXCLUDED.close"
            ),
            {"d": session},
        )

    after_close = dt.datetime(2025, 9, 2, 18, 30, tzinfo=ET)   # 18:30 ET
    assert not cal.is_open(after_close)

    prev = os.environ.get("REPLAY_NOW")
    os.environ["REPLAY_NOW"] = after_close.astimezone(UTC).isoformat()
    clock.reset_cache()
    clear_caches()
    reset_providers()
    if await cache.ping():
        await cache.data().delete(cache.quote_key("NVDA"))
    try:
        payload = await ondemand.fetch_one("NVDA")
    finally:
        if prev is None:
            os.environ.pop("REPLAY_NOW", None)
        else:
            os.environ["REPLAY_NOW"] = prev
        clock.reset_cache()
        clear_caches()
        reset_providers()

    assert payload is not None
    assert payload["is_extended_hours"] is True
    # The scoreable price is the regular close, not the after-hours print.
    assert payload["source"] == "eod"
    assert payload["price"] == pytest.approx(176.0)
    assert payload["extended_price"] is not None


async def test_a_cache_hit_still_repairs_a_missing_row(db):
    """The digest reads prices from `ticker_latest`, not from Redis.

    A row that goes missing while the cache is still warm would otherwise show
    `no_data` for a full TTL and never self-heal: the refresh would find the
    value in Redis, return happily, and write nothing.
    """
    from providers import reset_providers
    from worker.intraday import ondemand

    if not await cache.ping():
        pytest.skip("no Redis")
    await db.run_migrations(direct=True)
    async with db.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO tickers (ticker, instrument_class, benchmark_ticker,"
                " status) VALUES ('GOOGL','stock','XLC','active')"
                " ON CONFLICT DO NOTHING"
            )
        )
    reset_providers()
    await cache.data().delete(cache.quote_key("GOOGL"))
    assert await ondemand.fetch_one("GOOGL") is not None

    # The row disappears; Redis still holds the price.
    async with db.session_scope() as s:
        await s.execute(text("DELETE FROM ticker_latest WHERE ticker='GOOGL'"))
    assert await cache.get_quote("GOOGL") is not None

    await ondemand.refresh(["GOOGL"], budget_s=5.0, ensure_db=["GOOGL"])

    async with db.session_scope() as s:
        px = (
            await s.execute(
                text("SELECT price FROM ticker_latest WHERE ticker='GOOGL'")
            )
        ).scalar()
    assert px is not None, "a warm cache must not block recovery of a lost row"
