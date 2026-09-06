"""The nightly job's recovery contract.

The credit is spent at the HTTP call, outside any transaction, so a ledger alone
prevents reprocessing but not double-spending. The raw response is written to a
cache table before parsing, and a retry checks the cache and skips the call.

This file kills the job at every step and counts the provider calls that result.
"""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from api import clock
from api.quota import nightly_budget, worker_token
from providers.replay import ReplayHistory
from worker.nightly import fetch as fetch_mod
from worker.nightly import ledger

pytestmark = pytest.mark.asyncio(loop_scope="function")

TICKERS = ["AAPL", "MSFT", "NVDA"]


class Boom(RuntimeError):
    pass


class CountingHistory(ReplayHistory):
    """Counts real provider calls and can fail on demand."""

    def __init__(self, fail_on_call: bool = False):
        super().__init__()
        # Deliberately NOT `calls`: ReplayHistory keeps its own counter under
        # that name and the override would double-count every request.
        self.n_calls = 0
        self.fail_on_call = fail_on_call

    async def fetch_time_series_raw(self, ticker: str, outputsize: int) -> dict:
        self.n_calls += 1
        if self.fail_on_call:
            # A crash after the request left the building but before the
            # response was written down.
            raise Boom("network died mid-response")
        return await super().fetch_time_series_raw(ticker, outputsize)


async def _reset(dbmod):
    await dbmod.run_migrations(direct=True)
    async with dbmod.session_scope() as s:
        for t in (
            "job_item", "job_run", "provider_response_cache", "quota_ledger",
            "ticker_baseline", "ticker_daily_bar", "corporate_actions",
            "ticker_latest", "watchlist_snapshots", "watchlist_items", "tickers",
        ):
            await s.execute(text(f"DELETE FROM {t}"))
        for t in TICKERS:
            await s.execute(
                text(
                    "INSERT INTO tickers (ticker, instrument_class, benchmark_ticker,"
                    " status) VALUES (:t,'stock','XLK','active')"
                ),
                {"t": t},
            )
        await s.execute(
            text(
                "INSERT INTO tickers (ticker, instrument_class, benchmark_ticker,"
                " status) VALUES ('XLK','sector_etf','SPY','active')"
            )
        )
        await s.execute(
            text(
                "INSERT INTO tickers (ticker, instrument_class, benchmark_ticker,"
                " status) VALUES ('SPY','broad_etf',NULL,'active')"
            )
        )


async def _seed_prior_bars(dbmod, prov, run_date):
    """Give every ticker a history, so the run under test is a refresh."""
    from worker.baseline.persist import upsert_bars

    for t in TICKERS + ["XLK", "SPY"]:
        bars = await prov.daily_bars(t, 400)
        async with dbmod.session_scope() as s:
            await upsert_bars(s, t, bars[:-1])   # leave the last day to fetch
    async with dbmod.session_scope() as s:
        await ledger.start_run(s, run_date)
        await ledger.enqueue(s, run_date)


async def _drain(prov, run_date, budget, max_rounds: int = 6) -> dict:
    """Run every pending item to completion, the way a restart would."""
    stats: dict[str, int] = {}
    for _ in range(max_rounds):
        async with fetch_mod.session_scope() as s:
            batch = await ledger.pending(s, run_date, 50)
        if not batch:
            break
        for ticker, _rc in batch:
            if ticker in ("XLK", "SPY"):
                async with fetch_mod.session_scope() as s:
                    await ledger.mark(s, run_date, ticker, "done")
                continue
            try:
                out = await fetch_mod._one(prov, budget, run_date, ticker)
            except Boom:
                continue
            except Exception:
                continue
            for k, v in out.items():
                stats[k] = stats.get(k, 0) + v
    return stats


async def _done_count(dbmod, run_date) -> int:
    async with dbmod.session_scope() as s:
        return int(
            (
                await s.execute(
                    text(
                        "SELECT count(*) FROM job_item WHERE run_date=:d"
                        " AND status='done' AND ticker = ANY(:ts)"
                    ),
                    {"d": run_date, "ts": TICKERS},
                )
            ).scalar_one()
        )


async def test_clean_run_costs_exactly_one_call_per_ticker(db):
    run_date = clock.today_et()
    await _reset(db)
    prov = CountingHistory()
    await _seed_prior_bars(db, prov, run_date)
    prov.n_calls = 0

    await _drain(prov, run_date, nightly_budget(worker_token()))

    assert prov.n_calls == len(TICKERS)
    assert await _done_count(db, run_date) == len(TICKERS)


async def test_crash_after_marking_in_flight_costs_no_extra_call(db):
    """Step (b) owns its own transaction so the attempt survives, but no credit
    has been spent yet."""
    run_date = clock.today_et()
    await _reset(db)
    prov = CountingHistory()
    await _seed_prior_bars(db, prov, run_date)
    prov.n_calls = 0

    async with db.session_scope() as s:
        await ledger.mark_in_flight(s, run_date, "AAPL")   # then the process dies

    await _drain(prov, run_date, nightly_budget(worker_token()))
    assert prov.n_calls == len(TICKERS)
    assert await _done_count(db, run_date) == len(TICKERS)


async def test_crash_after_caching_the_response_skips_the_call_entirely(db):
    """Step (a) is what makes the job exactly-once on quota."""
    run_date = clock.today_et()
    await _reset(db)
    prov = CountingHistory()
    await _seed_prior_bars(db, prov, run_date)

    # Simulate a run that got as far as (d) for one ticker and then died.
    payload = await prov.fetch_time_series_raw("NVDA", fetch_mod.REFRESH_BARS)
    async with db.session_scope() as s:
        await ledger.mark_in_flight(s, run_date, "NVDA")
        await ledger.cache_response(s, run_date=run_date, ticker="NVDA", payload=payload)
    prov.n_calls = 0

    await _drain(prov, run_date, nightly_budget(worker_token()))

    assert prov.n_calls == len(TICKERS) - 1, "the cached ticker must not be refetched"
    assert await _done_count(db, run_date) == len(TICKERS)


async def test_crash_during_compute_does_not_respend(db):
    """Compute is a pure function of stored bars, so re-running it is free."""
    run_date = clock.today_et()
    await _reset(db)
    prov = CountingHistory()
    await _seed_prior_bars(db, prov, run_date)
    prov.n_calls = 0

    real = fetch_mod.recompute
    state = {"blown": False}

    async def flaky(session, ticker):
        if ticker == "MSFT" and not state["blown"]:
            state["blown"] = True
            raise Boom("died in compute")
        return await real(session, ticker)

    fetch_mod.recompute = flaky
    try:
        await _drain(prov, run_date, nightly_budget(worker_token()))
    finally:
        fetch_mod.recompute = real

    assert prov.n_calls == len(TICKERS), "the retry reads the response cache"
    assert await _done_count(db, run_date) == len(TICKERS)
    async with db.session_scope() as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM ticker_baseline WHERE ticker = ANY(:ts)"),
                {"ts": TICKERS},
            )
        ).scalar_one()
    assert int(n) == len(TICKERS)


async def test_a_crash_inside_the_http_call_overcounts_never_undercounts(db):
    """The single window the design does not close, asserted rather than hidden.

    A crash between spending the credit and writing the response costs one
    credit for one ticker on one night. The ledger over-counts, which is the
    safe direction against a hard external cap: under-counting would let the
    real provider quota run out while the system believed it had room.
    """
    run_date = clock.today_et()
    await _reset(db)
    good = CountingHistory()
    await _seed_prior_bars(db, good, run_date)

    budget = nightly_budget(worker_token())
    dying = CountingHistory(fail_on_call=True)
    await _drain(dying, run_date, budget, max_rounds=1)

    async with db.session_scope() as s:
        spent_after_crash = (await budget.status(s)).spent_today
    assert dying.n_calls == len(TICKERS)
    assert spent_after_crash == len(TICKERS)

    good.n_calls = 0
    await _drain(good, run_date, budget)
    async with db.session_scope() as s:
        spent_total = (await budget.status(s)).spent_today

    assert good.n_calls == len(TICKERS)
    assert spent_total == 2 * len(TICKERS)
    assert await _done_count(db, run_date) == len(TICKERS)


async def test_items_are_ordered_by_watcher_count(db):
    """A run that dies at 60% should leave the LEAST-watched tickers
    unrefreshed."""
    run_date = clock.today_et()
    await _reset(db)
    uid = uuid.uuid4()
    async with db.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_users (id, seed_credits_reset_on, created_at)"
                " VALUES (:id,:d,:now)"
            ),
            {"id": uid, "d": clock.today_et(), "now": clock.now()},
        )
        await s.execute(
            text(
                "INSERT INTO watchlist_items (user_id, ticker, added_at)"
                " VALUES (:u,'NVDA',:now)"
            ),
            {"u": uid, "now": clock.now()},
        )
        await s.execute(text("DELETE FROM job_item WHERE run_date = :d"), {"d": run_date})
        await ledger.enqueue(s, run_date)
        batch = await ledger.pending(s, run_date, 10)

    assert batch[0][0] == "NVDA"
    assert batch[0][1] == 1


async def test_response_cache_purges_after_its_ttl(db):
    run_date = clock.today_et()
    await _reset(db)
    async with db.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO provider_response_cache (ticker, run_date, payload,"
                " fetched_at) VALUES ('AAPL', :d, '{}'::jsonb, :old)"
            ),
            {"d": run_date, "old": clock.now() - dt.timedelta(hours=72)},
        )
        removed = await ledger.purge_cache(s)
    assert removed == 1
