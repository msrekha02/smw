"""Acknowledgement and feedback.

Acks are monotonic per ticker: `WHERE last_seen_at < :at` makes them idempotent
and order-independent, so two devices can ack in any order, the later
observation wins, and an old tab cannot rewind the checkpoint.

The response reports per-ticker outcomes, because a silent zero-row update
returning a bare 200 produces a quiet re-ack loop that looks exactly like broken
receipts from the client's side.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock, digest_token
from api.auth import Principal, get_current_user
from api.db import get_session
from api.schemas import AckRequest, AckResponse, FeedbackBatch

log = logging.getLogger("smw.ack")
router = APIRouter(tags=["ack"])


@router.post("/ack", response_model=AckResponse)
async def ack(
    body: AckRequest,
    user: Principal = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AckResponse:
    try:
        observed = digest_token.verify(body.token, user.id)
    except digest_token.TokenError as e:
        raise HTTPException(400, f"digest token rejected: {e}") from e

    wanted = set(body.tickers) if body.tickers else set(observed)
    results: dict[str, str] = {}

    for ticker in sorted(wanted):
        o = observed.get(ticker)
        if o is None:
            results[ticker] = "not_found"
            continue
        row = (
            await session.execute(
                text(
                    """
            UPDATE watchlist_snapshots
               SET last_seen_price = :px, last_seen_bench = :bench,
                   last_seen_bench_ticker = :bt, last_seen_at = :at,
                   is_initial = false
             WHERE user_id = :uid AND ticker = :t AND last_seen_at < :at
            RETURNING ticker
            """
                ),
                {
                    "px": o.px, "bench": o.bench, "bt": o.bt, "at": o.at,
                    "uid": user.id, "t": ticker,
                },
            )
        ).first()
        if row is not None:
            results[ticker] = "applied"
            continue

        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM watchlist_snapshots WHERE user_id=:uid AND ticker=:t"
                ),
                {"uid": user.id, "t": ticker},
            )
        ).first()
        results[ticker] = "superseded" if exists else "not_found"

    await session.commit()
    return AckResponse(results=results)


@router.post("/feedback", status_code=202)
async def feedback(
    body: FeedbackBatch,
    user: Principal = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Impressions, click-throughs, dismissals and thumbs.

    This is the only part of the system that checks whether "meaningful" is
    meaningful to a person. Everything else validates the model against itself.
    """
    if not body.events:
        return {"recorded": 0}
    now = clock.now()
    await session.execute(
        text(
            """
        INSERT INTO digest_feedback
            (user_id, ticker, tier, attention, shown_at, clicked_through,
             dismissed_fast, thumb)
        VALUES (:uid, :t, :tier, :att, :shown, :click, :dismiss, :thumb)
        ON CONFLICT (user_id, ticker, shown_at) DO UPDATE SET
            clicked_through = digest_feedback.clicked_through OR EXCLUDED.clicked_through,
            dismissed_fast  = digest_feedback.dismissed_fast  OR EXCLUDED.dismissed_fast,
            thumb = COALESCE(EXCLUDED.thumb, digest_feedback.thumb)
        """
        ),
        [
            {
                "uid": user.id, "t": e.ticker.upper(), "tier": e.tier,
                "att": e.attention, "shown": e.shown_at or now,
                "click": e.clicked_through, "dismiss": e.dismissed_fast,
                "thumb": e.thumb,
            }
            for e in body.events
        ],
    )
    await session.commit()
    return {"recorded": len(body.events)}
