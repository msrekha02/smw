"""Watchlist CRUD and symbol search."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock
from api.auth import Principal, get_current_user
from api.config import MAX_TICKERS_PER_USER
from api.db import get_session, session_scope
from api.quota import (
    take_user_seed_credit,
    user_budget,
    user_seed_credits_left,
)
from api.schemas import AddResult, SymbolOut, WatchlistAdd, WatchlistItemOut
from worker import catalog
from worker.baseline.persist import seed_ticker, set_initial_snapshot
from worker.nightly import corporate_actions

log = logging.getLogger("smw.watchlist")
router = APIRouter(tags=["watchlist"])


@router.get("/search", response_model=list[SymbolOut])
async def search_symbols(
    q: str = Query(min_length=1, max_length=40),
    limit: int = Query(12, ge=1, le=50),
    user: Principal = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SymbolOut]:
    rows = await catalog.search(session, q, user.id, limit)
    return [
        SymbolOut(
            ticker=r["ticker"], name=r["name"], exchange=r["exchange"], type=r["type"],
            already_watched=bool(r["watched"]), seeded=bool(r["seeded"]),
        )
        for r in rows
    ]


@router.get("/watchlist", response_model=list[WatchlistItemOut])
async def list_items(
    user: Principal = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[WatchlistItemOut]:
    rows = (
        await session.execute(
            text(
                """
        SELECT w.ticker, t.name, t.sector, t.benchmark_ticker, t.instrument_class,
               t.status, w.added_at, w.pinned_unread
          FROM watchlist_items w JOIN tickers t ON t.ticker = w.ticker
         WHERE w.user_id = :uid
         ORDER BY w.added_at DESC
        """
            ),
            {"uid": user.id},
        )
    ).mappings().all()
    return [WatchlistItemOut(**dict(r)) for r in rows]


async def _seed_in_background(ticker: str, user_id) -> None:
    """Seeding is network-bound, not compute-bound: 1259 EWMA iterations run in
    under 10ms, but the 8 credits/min ceiling means 7.5s per novel ticker. That
    is why adds are async."""
    try:
        async with session_scope() as s:
            await seed_ticker(s, ticker, user_budget())
            await set_initial_snapshot(s, user_id, ticker)
    except Exception:
        log.exception("background seed of %s failed", ticker)


@router.post("/watchlist", response_model=AddResult, status_code=status.HTTP_201_CREATED)
async def add_item(
    body: WatchlistAdd,
    background: BackgroundTasks,
    user: Principal = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AddResult:
    t = body.ticker

    n = (
        await session.execute(
            text("SELECT count(*) FROM watchlist_items WHERE user_id = :uid"),
            {"uid": user.id},
        )
    ).scalar_one()
    if int(n) >= MAX_TICKERS_PER_USER:
        raise HTTPException(400, f"watchlist is capped at {MAX_TICKERS_PER_USER} tickers")

    if not await catalog.is_listed(session, t):
        raise HTTPException(
            404,
            f"{t} is not in the US equity/ETF catalog. Both free data tiers are "
            "US-only, so the scope is enforced here rather than failing later.",
        )

    known = (
        await session.execute(
            text("SELECT status FROM tickers WHERE ticker = :t"), {"t": t}
        )
    ).scalar()

    await session.execute(
        text(
            """
        INSERT INTO tickers (ticker, name, status)
        SELECT :t, c.name, 'seeding' FROM symbol_catalog c WHERE c.ticker = :t
        ON CONFLICT (ticker) DO NOTHING
        """
        ),
        {"t": t},
    )
    await session.execute(
        text(
            """
        INSERT INTO watchlist_items (user_id, ticker, added_at)
        VALUES (:uid, :t, :now)
        ON CONFLICT (user_id, ticker) DO NOTHING
        """
        ),
        {"uid": user.id, "t": t, "now": clock.now()},
    )
    await session.execute(
        text("UPDATE tickers SET last_watched_at = :now WHERE ticker = :t"),
        {"now": clock.now(), "t": t},
    )
    # A re-add is the documented way to clear a corporate-action freeze.
    await corporate_actions.clear(session, t)
    await catalog.refresh_refcounts(session)

    # Adding an already-seeded ticker costs ZERO credits, and watchlists
    # concentrate heavily in mega-caps, so most adds are free.
    charged = False
    if known != "active":
        charged = await take_user_seed_credit(session, user.id, 1)

    await set_initial_snapshot(session, user.id, t)
    await session.commit()

    left = await user_seed_credits_left(session, user.id)
    item = WatchlistItemOut(
        **dict(
            (
                await session.execute(
                    text(
                        "SELECT w.ticker, t.name, t.sector, t.benchmark_ticker,"
                        " t.instrument_class, t.status, w.added_at, w.pinned_unread"
                        " FROM watchlist_items w JOIN tickers t ON t.ticker = w.ticker"
                        " WHERE w.user_id = :uid AND w.ticker = :t"
                    ),
                    {"uid": user.id, "t": t},
                )
            ).mappings().one()
        )
    )

    if known == "active":
        return AddResult(
            ticker=t, status="active", message="Added and scoreable now.",
            seed_credits_left=left, item=item,
        )
    if not charged:
        # Degradation, not rejection.
        return AddResult(
            ticker=t, status="seeding",
            message="Added. You are out of seeding credits today, so this one is "
                    "scoreable tomorrow.",
            seed_credits_left=left, item=item,
        )

    background.add_task(_seed_in_background, t, user.id)
    return AddResult(
        ticker=t, status="seeding",
        message="Added. Building its baseline now, usually a few seconds.",
        seed_credits_left=left, item=item,
    )


@router.delete(
    "/watchlist/{ticker}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def remove_item(
    ticker: str,
    user: Principal = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    t = ticker.upper()
    res = await session.execute(
        text("DELETE FROM watchlist_items WHERE user_id = :uid AND ticker = :t"),
        {"uid": user.id, "t": t},
    )
    if not res.rowcount:
        raise HTTPException(404, f"{t} is not on your watchlist")
    await catalog.refresh_refcounts(session)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/quota")
async def quota_status(
    user: Principal = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The partition view, minus the reserve's internals.

    The reserve is reported as a number so the ops surface is honest, but no
    request handler can spend from it: `user_budget()` cannot construct it.
    """
    from api import quota

    snap = await quota.snapshot(session)
    return {
        "partitions": snap,
        "your_seed_credits_left": await user_seed_credits_left(session, user.id),
        "note": "The reserved partition is not addressable from any request path.",
    }
