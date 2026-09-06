"""Writing a computed baseline down, and seeding a brand-new ticker.

`compute_baseline` is pure; everything that touches a provider, the quota ledger
or the database lives here. Keeping the split sharp is what lets the nightly job
re-run compute for free after a crash.
"""
from __future__ import annotations

import datetime as dt
import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock
from api.config import BENCHMARK_UNIVERSE, ETF_NAMES, ETF_SECTORS, SEED_BARS
from api.quota import Budget, Exhausted
from providers import get_providers
from providers.base import Bar, ProviderError
from worker.baseline.seed import (
    BaselineResult,
    NotEnoughBars,
    classify,
    compute_baseline,
    resolve_benchmark,
)

log = logging.getLogger("smw.seed")


async def upsert_bars(session: AsyncSession, ticker: str, bars: list[Bar]) -> int:
    if not bars:
        return 0
    await session.execute(
        text(
            """
        INSERT INTO ticker_daily_bar (ticker, bar_date, open, high, low, close, volume)
        VALUES (:t, :d, :o, :h, :l, :c, :v)
        ON CONFLICT (ticker, bar_date) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, volume = EXCLUDED.volume
        """
        ),
        [
            {
                "t": ticker.upper(), "d": b.bar_date, "o": b.open, "h": b.high,
                "l": b.low, "c": b.close, "v": b.volume,
            }
            for b in bars
        ],
    )
    return len(bars)


async def load_bars(session: AsyncSession, ticker: str, limit: int = SEED_BARS) -> list[Bar]:
    rows = (
        await session.execute(
            text(
                "SELECT bar_date, open, high, low, close, volume"
                " FROM ticker_daily_bar WHERE ticker = :t"
                " ORDER BY bar_date DESC LIMIT :n"
            ),
            {"t": ticker.upper(), "n": limit},
        )
    ).all()
    out = [Bar(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), r[5]) for r in rows]
    out.reverse()
    return out


async def write_baseline(session: AsyncSession, res: BaselineResult) -> None:
    row = res.as_row()
    row["recent_daily"] = json.dumps(row["recent_daily"])
    row["residual_hist"] = json.dumps(row["residual_hist"])
    row["updated_at"] = clock.now()
    cols = list(row)
    await session.execute(
        text(
            f"""
        INSERT INTO ticker_baseline ({', '.join(cols)})
        VALUES ({', '.join(':' + c for c in cols)})
        ON CONFLICT (ticker) DO UPDATE SET
            {', '.join(f'{c} = EXCLUDED.{c}' for c in cols if c != 'ticker')}
        """
        ),
        row,
    )


async def recompute(session: AsyncSession, ticker: str) -> BaselineResult | None:
    """Pure recompute from stored bars. Costs no quota and is idempotent."""
    t = ticker.upper()
    meta = (
        await session.execute(
            text("SELECT instrument_class, benchmark_ticker FROM tickers WHERE ticker=:t"),
            {"t": t},
        )
    ).first()
    if meta is None:
        return None
    ic, bm = meta[0], meta[1]
    stock = await load_bars(session, t)
    if len(stock) < 60:
        return None
    bench = await load_bars(session, bm) if bm else None
    try:
        res = compute_baseline(t, ic, bm, stock, bench)
    except NotEnoughBars as e:
        log.info("recompute %s: %s", t, e)
        return None
    await write_baseline(session, res)
    return res


async def backfill_earnings(session: AsyncSession, ticker: str) -> int:
    t = ticker.upper()
    try:
        dates = await get_providers().quotes.earnings_history(t)
    except (ProviderError, KeyError) as e:
        log.info("earnings backfill %s: %s", t, e)
        return 0
    if not dates:
        return 0
    await session.execute(
        text(
            "INSERT INTO earnings_dates (ticker, event_date, source)"
            " VALUES (:t, :d, 'provider') ON CONFLICT DO NOTHING"
        ),
        [{"t": t, "d": d} for d in dates],
    )
    return len(dates)


async def ensure_ticker_row(session: AsyncSession, ticker: str) -> tuple[str, str | None]:
    """Resolve instrument class, sector and benchmark. Free on replay, one
    Finnhub profile call on live -- and only for symbols we have never seen."""
    t = ticker.upper()
    row = (
        await session.execute(
            text(
                "SELECT instrument_class, benchmark_ticker, sector, status"
                " FROM tickers WHERE ticker = :t"
            ),
            {"t": t},
        )
    ).first()
    if row is not None and row[1] is not None:
        return row[0], row[1]

    ic = classify(t)
    sector = None
    name = None
    if ic == "stock":
        try:
            prof = await get_providers().quotes.profile(t)
            sector, name = prof.sector, prof.name
        except (ProviderError, KeyError) as e:
            log.info("profile %s: %s", t, e)

    # The provider names stocks and nothing else, so an ETF arrives here with a
    # null name and, if it is a sector ETF, no sector of its own. Both are
    # filled from the static universe rather than left for the UI to paper over
    # with a raw enum or an empty cell.
    if name is None:
        name = ETF_NAMES.get(t)
    if sector is None and ic == "sector_etf":
        sector = ETF_SECTORS.get(t)

    bm = resolve_benchmark(t, ic, sector)

    await session.execute(
        text(
            """
        INSERT INTO tickers (ticker, name, instrument_class, sector,
                             benchmark_ticker, status)
        VALUES (:t, :name, :ic, :sector, :bm, 'seeding')
        ON CONFLICT (ticker) DO UPDATE SET
            name = COALESCE(EXCLUDED.name, tickers.name),
            instrument_class = EXCLUDED.instrument_class,
            sector = COALESCE(EXCLUDED.sector, tickers.sector),
            benchmark_ticker = EXCLUDED.benchmark_ticker
        """
        ),
        {"t": t, "name": name, "ic": ic, "sector": sector, "bm": bm},
    )
    return ic, bm


async def seed_ticker(
    session: AsyncSession, ticker: str, budget: Budget, *, force: bool = False
) -> str:
    """Fetch history and build the baseline. Returns the resulting status.

    A ticker is scoreable IMMEDIATELY on add -- there is no warm-up period
    during which the product does not work -- as long as the seeding partition
    has a credit. If it does not, the add still succeeds and the item shows
    `seeding`: degradation, not rejection.
    """
    t = ticker.upper()
    ic, bm = await ensure_ticker_row(session, t)

    have = (
        await session.execute(
            text("SELECT count(*) FROM ticker_daily_bar WHERE ticker = :t"), {"t": t}
        )
    ).scalar_one()

    prov = get_providers().history
    if int(have) < 250 or force:
        try:
            await budget.spend(session, 1)
        except Exhausted:
            log.info("seeding partition exhausted; %s stays seeding", t)
            return "seeding"
        try:
            payload = await prov.fetch_time_series_raw(t, SEED_BARS)
            bars = prov.parse_time_series(payload)
        except (ProviderError, KeyError) as e:
            log.warning("seed fetch %s failed: %s", t, e)
            return "seeding"
        if len(bars) < 60:
            await session.execute(
                text("UPDATE tickers SET status='unknown' WHERE ticker=:t"), {"t": t}
            )
            return "unknown"
        await upsert_bars(session, t, bars)

    if bm:
        bhave = (
            await session.execute(
                text("SELECT count(*) FROM ticker_daily_bar WHERE ticker = :t"), {"t": bm}
            )
        ).scalar_one()
        if int(bhave) < 250:
            # Benchmarks are shared infrastructure; seeding one is charged to
            # whichever partition is already open, not to a second user credit.
            await ensure_ticker_row(session, bm)
            try:
                await budget.spend(session, 1)
                payload = await prov.fetch_time_series_raw(bm, SEED_BARS)
                await upsert_bars(session, bm, prov.parse_time_series(payload))
                await session.execute(
                    text("UPDATE tickers SET status='active' WHERE ticker=:t"), {"t": bm}
                )
            except (Exhausted, ProviderError, KeyError) as e:
                log.info("benchmark %s seed deferred: %s", bm, e)

    res = await recompute(session, t)
    if res is None:
        return "seeding"

    if ic == "stock":
        await backfill_earnings(session, t)

    await session.execute(
        text("UPDATE tickers SET status='active' WHERE ticker=:t"), {"t": t}
    )
    return "active"


async def seed_benchmarks(session: AsyncSession, budget: Budget) -> dict[str, str]:
    """Benchmarks seed FIRST, always. Everything else anchors to them."""
    out: dict[str, str] = {}
    for t in BENCHMARK_UNIVERSE:
        try:
            out[t] = await seed_ticker(session, t, budget)
        except Exception as e:  # one bad symbol never blocks the rest
            log.exception("benchmark seed %s failed", t)
            out[t] = f"error: {e}"
    return out


async def set_initial_snapshot(
    session: AsyncSession, user_id, ticker: str
) -> None:
    """The checkpoint a new watchlist item starts from.

    Written at add time so the first digest has something to diff against;
    marked `is_initial` so the card reads "measured from here" rather than
    reporting a zero move as if it were a finding.
    """
    t = ticker.upper()
    row = (
        await session.execute(
            text(
                """
        SELECT l.price, l.fetched_at, t.benchmark_ticker, lb.price
          FROM tickers t
          LEFT JOIN ticker_latest l  ON l.ticker = t.ticker
          LEFT JOIN ticker_latest lb ON lb.ticker = t.benchmark_ticker
         WHERE t.ticker = :t
        """
            ),
            {"t": t},
        )
    ).first()
    px = row[0] if row else None
    bench_px = row[3] if row else None
    bm = row[2] if row else None
    if px is None:
        px = (
            await session.execute(
                text(
                    "SELECT close FROM ticker_daily_bar WHERE ticker=:t"
                    " ORDER BY bar_date DESC LIMIT 1"
                ),
                {"t": t},
            )
        ).scalar()
    if bench_px is None and bm:
        bench_px = (
            await session.execute(
                text(
                    "SELECT close FROM ticker_daily_bar WHERE ticker=:t"
                    " ORDER BY bar_date DESC LIMIT 1"
                ),
                {"t": bm},
            )
        ).scalar()
    if px is None:
        return
    await session.execute(
        text(
            """
        INSERT INTO watchlist_snapshots (user_id, ticker, last_seen_price,
            last_seen_bench, last_seen_bench_ticker, last_seen_at, is_initial)
        VALUES (:uid, :t, :px, :bench, :bt, :at, true)
        ON CONFLICT (user_id, ticker) DO NOTHING
        """
        ),
        {
            "uid": user_id, "t": t, "px": float(px),
            "bench": float(bench_px or 0.0), "bt": bm or "SPY",
            "at": clock.now(),
        },
    )


def today() -> dt.date:
    return clock.today_et()
