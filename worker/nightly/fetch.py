"""The nightly fetch phase.

Fetch is quota-bound and non-idempotent; compute is a pure function of stored
bars. Splitting them means only this half needs recovery machinery, and it
shrinks to "fetch bars, insert bars".

The order of operations inside one ticker is what makes a crash safe at every
point:

    a. response cache hit?            -> skip the HTTP call entirely
    b. mark in_flight, attempts += 1  [own transaction]
    c. spend one credit, GET /time_series
    d. write the raw response         [own transaction]
    e. restatement? freeze, skip compute, done
    f. upsert bars, recompute, done   [one transaction]

A crash between (c) and (d) is the only window that loses a credit, and it is
one credit for one ticker on one night.
"""
from __future__ import annotations

import datetime as dt
import logging

from api import clock
from api.config import BENCHMARK_UNIVERSE, DEFAULT_BENCHMARK, SPY_MIN_BARS
from api.db import session_scope
from api.quota import Budget, Exhausted, nightly_budget, worker_token
from providers import get_providers
from providers.base import ProviderError
from sqlalchemy import text
from worker.baseline.persist import recompute, seed_benchmarks, upsert_bars
from worker.nightly import corporate_actions, ledger

log = logging.getLogger("smw.nightly")

REFRESH_BARS = 25  # enough to close any weekend or holiday gap
MAX_ATTEMPTS = 3


async def spy_ready() -> bool:
    async with session_scope() as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM ticker_daily_bar WHERE ticker = :t"),
                {"t": DEFAULT_BENCHMARK},
            )
        ).scalar_one()
    return int(n) >= SPY_MIN_BARS


async def run_nightly(run_date: dt.date | None = None) -> dict:
    """One nightly pass. Safe to re-run; safe to interrupt."""
    run_date = run_date or clock.today_et()
    budget: Budget = nightly_budget(worker_token())
    stats = {"fetched": 0, "cached": 0, "computed": 0, "frozen": 0, "failed": 0}

    async with session_scope() as s:
        status = await ledger.start_run(s, run_date)
    if status == "done":
        log.info("nightly %s already complete", run_date)
        return stats | {"skipped": True}

    # 1-2. catalog, then the 12 benchmarks BEFORE anything else.
    from worker.catalog import sync_catalog

    try:
        async with session_scope() as s:
            await sync_catalog(s)
    except Exception:
        log.exception("catalog sync failed; continuing")

    async with session_scope() as s:
        await seed_benchmarks(s, budget)

    # 3. The SPY gate. Without it every window silently measures as a single
    #    session and the whole product reports confident nonsense.
    if not await spy_ready():
        log.error("SPY has fewer than %d bars; aborting run", SPY_MIN_BARS)
        async with session_scope() as s:
            await ledger.finish_run(s, run_date, "aborted_no_benchmark")
        return stats | {"aborted": "spy_not_ready"}

    # 4. enqueue in refcount order
    async with session_scope() as s:
        await ledger.enqueue(s, run_date)

    prov = get_providers().history

    while True:
        async with session_scope() as s:
            batch = await ledger.pending(s, run_date, limit=25)
        if not batch:
            break

        for ticker, _refcount in batch:
            if ticker in BENCHMARK_UNIVERSE:
                # Already refreshed above; mark done without spending again.
                async with session_scope() as s:
                    await ledger.mark(s, run_date, ticker, "done")
                continue
            try:
                outcome = await _one(prov, budget, run_date, ticker)
            except Exhausted:
                log.warning("nightly reserve exhausted at %s", ticker)
                async with session_scope() as s:
                    await ledger.finish_run(s, run_date, "quota_exhausted")
                return stats | {"stopped": "quota"}
            except Exception as e:
                log.exception("ticker %s failed", ticker)
                async with session_scope() as s:
                    attempts = await ledger.mark_in_flight(s, run_date, ticker)
                    await ledger.mark(
                        s, run_date, ticker,
                        "failed" if attempts >= MAX_ATTEMPTS else "pending",
                        str(e)[:400],
                    )
                stats["failed"] += 1
                continue
            for k in outcome:
                stats[k] = stats.get(k, 0) + outcome[k]

    async with session_scope() as s:
        await ledger.purge_cache(s)
        await ledger.finish_run(s, run_date, "done")
    log.info("nightly %s complete: %s", run_date, stats)
    return stats


async def _one(prov, budget: Budget, run_date: dt.date, ticker: str) -> dict:
    """One ticker, following the crash-safe order exactly."""
    # (a) A cached response means the credit was already spent tonight.
    async with session_scope() as s:
        payload = await ledger.cached_response(s, ticker, run_date)
    from_cache = payload is not None

    if not from_cache:
        # (b) own transaction, so the attempt survives a crash in (c).
        async with session_scope() as s:
            attempts = await ledger.mark_in_flight(s, run_date, ticker)
        if attempts > MAX_ATTEMPTS:
            async with session_scope() as s:
                await ledger.mark(s, run_date, ticker, "failed", "max attempts")
            return {"failed": 1}

        # (c) the credit is spent here, outside any transaction that could
        #     roll it back into existence.
        async with session_scope() as s:
            await budget.spend(s, 1)
        try:
            payload = await prov.fetch_time_series_raw(ticker, REFRESH_BARS)
        except ProviderError as e:
            async with session_scope() as s:
                await ledger.mark(
                    s, run_date, ticker,
                    "failed" if not e.retryable or attempts >= MAX_ATTEMPTS else "pending",
                    str(e)[:400],
                )
            return {"failed": 1}

        # (d) raw response written BEFORE parsing.
        async with session_scope() as s:
            await ledger.cache_response(s, ticker, run_date, payload)

    bars = prov.parse_time_series(payload)

    # (e) restatement: freeze, surface, stop. No compute, no snapshot touched.
    async with session_scope() as s:
        rest = await corporate_actions.detect(s, ticker, bars)
        if rest is not None:
            await corporate_actions.freeze(s, rest)
            await ledger.mark(s, run_date, ticker, "done", "restated")
            return {"frozen": 1, "cached" if from_cache else "fetched": 1}

    # (f) bars and baseline together: compute is pure, so re-running is free.
    async with session_scope() as s:
        await upsert_bars(s, ticker, bars)
        res = await recompute(s, ticker)
        if res is not None:
            await s.execute(
                text("UPDATE tickers SET status='active' WHERE ticker=:t"),
                {"t": ticker},
            )
        await ledger.mark(s, run_date, ticker, "done")

    out = {"computed": 1 if res is not None else 0}
    out["cached" if from_cache else "fetched"] = 1
    return out
