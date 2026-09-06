"""The worker: two schedulers, one process.

Nightly and intraday have different tick rates, different data sources and
different failure modes, but they are one deployable because a second one would
buy nothing here. A single worker instance also sidesteps leader election
entirely: `pg_advisory_lock` is unsafe through pgbouncer's transaction mode, and
a pooler-safe lease is designed and deliberately not built.

The worker uses `DATABASE_URL_DIRECT`. Session-scoped behaviour is unreliable
through Supabase's transaction-mode pooler.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import os

from api import clock, db
from api.calendar_ny import ET, get_calendar
from api.config import settings
from api.db import session_scope
from providers import get_providers
from worker.earnings import refresh_calendar
from worker.intraday import benchmarks, ws
from worker.nightly.fetch import run_nightly

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
log = logging.getLogger("smw.worker")

# 20 minutes after the regular close, so late prints have settled.
NIGHTLY_AFTER_CLOSE_MIN = 20


async def nightly_scheduler() -> None:
    """Run once per trading day, after the US close. Idempotent by run_date, so
    a restart mid-evening resumes rather than re-spends."""
    last_run: dt.date | None = None
    while True:
        try:
            now = clock.now()
            cal = get_calendar()
            today = now.astimezone(ET).date()
            bounds = cal.bounds(today)
            due = (
                bounds is not None
                and now >= bounds.close_utc + dt.timedelta(minutes=NIGHTLY_AFTER_CLOSE_MIN)
                and last_run != today
            )
            if os.environ.get("RUN_NIGHTLY_ON_BOOT") == "1" and last_run is None:
                due = True
            if due:
                log.info("nightly run starting for %s", today)
                stats = await run_nightly(today)
                log.info("nightly finished: %s", stats)
                last_run = today
                if today.weekday() == 5 or os.environ.get("RUN_NIGHTLY_ON_BOOT") == "1":
                    async with session_scope() as s:
                        await refresh_calendar(s)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("nightly scheduler iteration failed")
        await asyncio.sleep(120)


async def intraday_scheduler() -> None:
    tasks = [
        asyncio.create_task(benchmarks.run(), name="benchmarks"),
        asyncio.create_task(ws.run(), name="ws"),
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def bootstrap() -> None:
    """Benchmarks seed FIRST. A fresh deploy with no SPY bars would otherwise
    report same-session scoring on every multi-day window, silently."""
    from api.quota import nightly_budget, worker_token
    from worker.baseline.persist import seed_benchmarks
    from worker.catalog import sync_catalog

    async with session_scope() as s:
        n = await sync_catalog(s)
        log.info("catalog: %d symbols", n)
    async with session_scope() as s:
        res = await seed_benchmarks(s, nightly_budget(worker_token()))
    log.info("benchmarks: %s", res)


async def main() -> None:
    db.use_direct()
    await db.run_migrations(direct=True)
    log.info(
        "worker up: providers=%s clock=%s market_open=%s",
        get_providers().mode,
        clock.now().isoformat(),
        get_calendar().is_open(clock.now()),
    )
    if os.environ.get("SKIP_BOOTSTRAP") != "1":
        await bootstrap()

    tasks = [
        asyncio.create_task(nightly_scheduler(), name="nightly"),
        asyncio.create_task(intraday_scheduler(), name="intraday"),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await db.dispose()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
