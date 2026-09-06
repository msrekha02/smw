"""The run ledger and the provider response cache.

The credit is spent at the HTTP call, OUTSIDE any transaction, so a ledger alone
prevents reprocessing but not double-spending: a crash between the call and the
commit loses the work but not the credit. The raw response is therefore written
to a cache table BEFORE parsing, and a retry checks the cache and skips the call
entirely. That is what makes the nightly job exactly-once on quota rather than
merely at-least-once on work.

Each step owns its own transaction, because a single long transaction would roll
back the very bookkeeping that recovery depends on.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock
from api.config import RESPONSE_CACHE_TTL_H

log = logging.getLogger("smw.ledger")


async def start_run(session: AsyncSession, run_date: dt.date) -> str:
    row = (
        await session.execute(
            text(
                """
        INSERT INTO job_run (run_date, started_at, status)
        VALUES (:d, :now, 'running')
        ON CONFLICT (run_date) DO UPDATE
            SET status = CASE WHEN job_run.status = 'done' THEN 'done'
                              ELSE 'running' END
        RETURNING status
        """
            ),
            {"d": run_date, "now": clock.now()},
        )
    ).scalar_one()
    return row


async def finish_run(session: AsyncSession, run_date: dt.date, status: str) -> None:
    await session.execute(
        text(
            "UPDATE job_run SET finished_at = :now, status = :s,"
            " credits_spent = (SELECT coalesce(sum(attempts),0) FROM job_item"
            "                   WHERE run_date = :d AND status = 'done')"
            " WHERE run_date = :d"
        ),
        {"now": clock.now(), "s": status, "d": run_date},
    )


async def enqueue(session: AsyncSession, run_date: dt.date) -> int:
    """Active tickers, ordered by watcher count.

    Descending refcount matters for the failure mode, not for throughput: a run
    that dies at 60% should leave the LEAST-watched tickers unrefreshed.
    """
    n = (
        await session.execute(
            text(
                """
        INSERT INTO job_item (run_date, ticker, refcount, status)
        SELECT :d, t.ticker,
               (SELECT count(*) FROM watchlist_items w WHERE w.ticker = t.ticker),
               'pending'
          FROM tickers t
         WHERE t.status IN ('active', 'seeding')
        ON CONFLICT (run_date, ticker) DO NOTHING
        """
            ),
            {"d": run_date},
        )
    ).rowcount
    return int(n or 0)


async def pending(session: AsyncSession, run_date: dt.date, limit: int) -> list[tuple[str, int]]:
    rows = (
        await session.execute(
            text(
                """
        SELECT ticker, refcount FROM job_item
         WHERE run_date = :d AND status IN ('pending', 'in_flight') AND attempts < 3
         ORDER BY refcount DESC, ticker ASC
         LIMIT :n
        """
            ),
            {"d": run_date, "n": limit},
        )
    ).all()
    return [(r[0], int(r[1])) for r in rows]


async def mark_in_flight(session: AsyncSession, run_date: dt.date, ticker: str) -> int:
    return int(
        (
            await session.execute(
                text(
                    "UPDATE job_item SET status='in_flight', attempts = attempts + 1"
                    " WHERE run_date=:d AND ticker=:t RETURNING attempts"
                ),
                {"d": run_date, "t": ticker},
            )
        ).scalar_one()
    )


async def mark(
    session: AsyncSession, run_date: dt.date, ticker: str, status: str, error: str | None = None
) -> None:
    await session.execute(
        text(
            "UPDATE job_item SET status=:s, error=:e WHERE run_date=:d AND ticker=:t"
        ),
        {"s": status, "e": error, "d": run_date, "t": ticker},
    )


async def cached_response(
    session: AsyncSession, ticker: str, run_date: dt.date
) -> dict[str, Any] | None:
    """Step (a). This is what makes the job exactly-once on quota."""
    row = (
        await session.execute(
            text(
                "SELECT payload FROM provider_response_cache"
                " WHERE ticker = :t AND run_date = :d"
            ),
            {"t": ticker, "d": run_date},
        )
    ).scalar()
    return row if row is None or isinstance(row, dict) else json.loads(row)


async def cache_response(
    session: AsyncSession, ticker: str, run_date: dt.date, payload: dict
) -> None:
    await session.execute(
        text(
            """
        INSERT INTO provider_response_cache (ticker, run_date, payload, fetched_at)
        VALUES (:t, :d, CAST(:p AS jsonb), :now)
        ON CONFLICT (ticker, run_date) DO UPDATE
            SET payload = EXCLUDED.payload, fetched_at = EXCLUDED.fetched_at
        """
        ),
        {"t": ticker, "d": run_date, "p": json.dumps(payload), "now": clock.now()},
    )


async def purge_cache(session: AsyncSession) -> int:
    n = (
        await session.execute(
            text(
                "DELETE FROM provider_response_cache"
                " WHERE fetched_at < :cutoff"
            ),
            {"cutoff": clock.now() - dt.timedelta(hours=RESPONSE_CACHE_TTL_H)},
        )
    ).rowcount
    return int(n or 0)
