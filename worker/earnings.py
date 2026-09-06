"""Earnings dates: backfill and forward calendar.

Earnings never adds score. It widens the expected range, so its only job here is
to be present and correct: a missing earnings date makes a scheduled 4% move
look like news, and that is precisely the false positive the design set out to
remove.

Both endpoints are free on Finnhub, so the forward calendar is refreshed weekly
for the whole watched universe in one call rather than per ticker.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock
from providers import get_providers
from providers.base import ProviderError

log = logging.getLogger("smw.earnings")

FORWARD_DAYS = 45


async def refresh_calendar(session: AsyncSession) -> int:
    tickers = [
        r[0]
        for r in (
            await session.execute(
                text(
                    "SELECT DISTINCT w.ticker FROM watchlist_items w"
                    " JOIN tickers t ON t.ticker = w.ticker"
                    " WHERE t.instrument_class = 'stock'"
                )
            )
        ).all()
    ]
    if not tickers:
        return 0

    today = clock.today_et()
    try:
        found = await get_providers().quotes.earnings_calendar(
            today - dt.timedelta(days=7), today + dt.timedelta(days=FORWARD_DAYS), tickers
        )
    except ProviderError as e:
        log.warning("earnings calendar failed: %s", e)
        return 0

    rows = [
        {"t": t, "d": d, "s": "calendar"} for t, dates in found.items() for d in dates
    ]
    if not rows:
        return 0
    await session.execute(
        text(
            "INSERT INTO earnings_dates (ticker, event_date, source)"
            " VALUES (:t, :d, :s) ON CONFLICT DO NOTHING"
        ),
        rows,
    )
    log.info("earnings calendar: %d dates across %d tickers", len(rows), len(found))
    return len(rows)
