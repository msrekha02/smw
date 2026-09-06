"""Ticker detail: the page that shows its work."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import Principal, get_current_user
from api.db import get_session
from api.schemas import ResidualHistogram, TickerDetail

router = APIRouter(tags=["tickers"])


@router.get("/tickers/{ticker}", response_model=TickerDetail)
async def detail(
    ticker: str,
    user: Principal = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TickerDetail:
    t = ticker.upper()
    row = (
        await session.execute(
            text(
                """
        SELECT t.ticker, t.name, t.sector, t.instrument_class, t.benchmark_ticker,
               t.status, b.beta_raw, b.beta_used, b.r2, b.sigma_idio, b.sample_days,
               b.adv20, b.wk52_high, b.wk52_low, b.last_bar_date, b.frozen_reason,
               b.residual_hist, b.recent_daily
          FROM tickers t LEFT JOIN ticker_baseline b ON b.ticker = t.ticker
         WHERE t.ticker = :t
        """
            ),
            {"t": t},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(404, f"{t} is not known to this system")

    earn = [
        r[0]
        for r in (
            await session.execute(
                text(
                    "SELECT event_date FROM earnings_dates WHERE ticker = :t"
                    " ORDER BY event_date DESC LIMIT 24"
                ),
                {"t": t},
            )
        ).all()
    ]

    hist = row["residual_hist"]
    return TickerDetail(
        ticker=row["ticker"], name=row["name"], sector=row["sector"],
        instrument_class=row["instrument_class"],
        benchmark_ticker=row["benchmark_ticker"], status=row["status"],
        beta_raw=row["beta_raw"], beta_used=row["beta_used"], r2=row["r2"],
        sigma_idio=row["sigma_idio"], sample_days=int(row["sample_days"] or 0),
        adv20=row["adv20"], wk52_high=row["wk52_high"], wk52_low=row["wk52_low"],
        last_bar_date=row["last_bar_date"], frozen_reason=row["frozen_reason"],
        residual_hist=ResidualHistogram(**hist) if hist else None,
        recent_daily=list(row["recent_daily"] or []),
        earnings=earn,
    )
