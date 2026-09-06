"""The digest endpoint.

ETag/304 because the client polls every 20 seconds while the market is open and
most of those polls have nothing to say. `next_poll_after_ms` lets the server
set the cadence rather than the client guessing: 20s open, 15 minutes closed.
"""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import cache, clock, digest_service
from api.auth import Principal, get_current_user
from api.calendar_ny import UTC, get_calendar
from api.config import POLL_MS_CLOSED, POLL_MS_OPEN, STALE_AFTER_S
from api.db import get_session
from api.schemas import DigestOut

log = logging.getLogger("smw.digest")
router = APIRouter(tags=["digest"])


async def _stale_tickers(
    session: AsyncSession, user_id
) -> tuple[list[str], list[str]]:
    """Watched tickers whose quote is older than its source allows, plus the
    benchmarks they anchor to.

    This is the cold tier's trigger: everything outside the WebSocket's top 50
    is fetched only when somebody opens a list containing it.

    Returns (stale, missing): the second list names tickers with no stored row
    at all, which must be written through even when Redis still has the price.

    Benchmarks are included even though they are not on anyone's watchlist. A
    stale benchmark mis-attributes a sector move to the stock, which is the one
    error this system exists to avoid, and a stock refreshed against a missing
    benchmark falls back to beta 0 and reports reduced confidence for the whole
    list. Age is measured against the system clock, because the replay clock
    does not move SQL `now()`.
    """
    rows = (
        await session.execute(
            text(
                """
        SELECT w.ticker, t.benchmark_ticker, l.source, l.fetched_at,
               lb.source AS b_source, lb.fetched_at AS b_fetched_at
          FROM watchlist_items w
          JOIN tickers t ON t.ticker = w.ticker
          LEFT JOIN ticker_latest l  ON l.ticker = w.ticker
          LEFT JOIN ticker_latest lb ON lb.ticker = t.benchmark_ticker
         WHERE w.user_id = :uid AND t.status = 'active'
        """
            ),
            {"uid": user_id},
        )
    ).all()

    now = clock.now()

    def stale(source: str | None, fetched_at) -> bool:
        if source is None or fetched_at is None:
            return True
        return (now - fetched_at).total_seconds() > STALE_AFTER_S.get(source, 86400)

    out: list[str] = []
    missing: list[str] = []
    for ticker, bench, source, fetched_at, b_source, b_fetched in rows:
        if stale(source, fetched_at):
            out.append(ticker)
            if source is None:
                missing.append(ticker)
        if bench and stale(b_source, b_fetched):
            out.append(bench)
            if b_source is None:
                missing.append(bench)
    return list(dict.fromkeys(out)), list(dict.fromkeys(missing))


@router.get("/digest", response_model=DigestOut)
async def get_digest(
    request: Request,
    response: Response,
    as_if_last_seen: str | None = Query(
        default=None,
        description=(
            "ISO-8601 override for the diff anchor. Lets you view any historical "
            "window on demand instead of waiting a week to accumulate one."
        ),
    ),
    refresh: bool = Query(default=True),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    user: Principal = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    anchor: dt.datetime | None = None
    if as_if_last_seen:
        try:
            anchor = dt.datetime.fromisoformat(as_if_last_seen)
        except ValueError:
            anchor = None
        if anchor is not None and anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)

    if refresh:
        stale, missing = await _stale_tickers(session, user.id)
        if stale:
            from worker.intraday.ondemand import refresh as refresh_quotes

            await refresh_quotes(stale, budget_s=2.0, ensure_db=missing)

    digest = await digest_service.build_digest(session, user.id, anchor)
    body = digest_service.stable_body(digest)
    etag = digest_service.etag_for(body)

    cal = get_calendar()
    poll = POLL_MS_OPEN if cal.is_open(clock.now()) else POLL_MS_CLOSED

    if if_none_match and if_none_match.strip() == etag:
        # Nothing changed. The client keeps the digest it has, including the
        # token it already holds, so its pending acks stay valid.
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": "private, no-cache",
                "X-Next-Poll-After-Ms": str(poll),
            },
        )

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["X-Next-Poll-After-Ms"] = str(poll)
    await cache.set_etag(user.id, etag, body)
    return digest
