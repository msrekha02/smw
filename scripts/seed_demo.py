"""Seed a working demo: benchmarks, a watchlist, and a checkpoint to diff from.

`docker compose up` runs this after the worker's bootstrap so the app has
something to show on first load. It uses the same seeding path a real add uses,
so nothing here is a special case that only exists for the demo.

Run: python -m scripts.seed_demo [--email you@example.com] [--scenario baseline]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import os

from sqlalchemy import text

from api import auth, clock, db
from api.config import settings
from api.quota import Budget, nightly_budget, worker_token
from worker.baseline.persist import seed_benchmarks, seed_ticker, set_initial_snapshot
from worker.catalog import refresh_refcounts, sync_catalog
from worker.intraday.ondemand import fetch_one

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s %(message)s")
log = logging.getLogger("smw.seed_demo")

DEMO_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "AMD", "AVGO", "META", "GOOGL", "NFLX",
    "JPM", "XOM", "LLY", "CAT", "BA", "PG", "KO", "WMT", "DUK", "TSLA",
    "AMZN", "SPY",
]


def scenario_window_sessions(default: int = 1) -> int:
    """How far back the demo checkpoint should sit.

    Each scenario fixture declares the window it was built to demonstrate --
    the spike-and-revert one only makes sense over five sessions -- so the
    seeder reads it rather than making the operator remember a flag.
    """
    import json
    import pathlib

    root = pathlib.Path(settings.fixtures_dir)
    if not root.is_absolute():
        root = pathlib.Path(__file__).resolve().parent.parent / root
    f = root / "scenarios" / f"{settings.replay_scenario}.json"
    if not f.exists():
        return default
    try:
        return int(json.loads(f.read_text(encoding="utf-8")).get("window_sessions", default))
    except (ValueError, TypeError):
        return default


async def run(
    email: str, tickers: list[str], back_sessions: int | None = None,
    dispose: bool = True,
) -> dict:
    if back_sessions is None:
        back_sessions = scenario_window_sessions()
    db.use_direct()
    await db.run_migrations(direct=True)

    # The same derivation the sign-in endpoint uses, so seeding this email
    # and signing in as it are the same user.
    email = auth.normalize_email(email)
    uid = auth.dev_user_id(email)
    async with db.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_users (id, email, seed_credits_reset_on, created_at)"
                " VALUES (:id,:e,:d,:now) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": uid, "e": email, "d": clock.today_et(), "now": clock.now()},
        )
        await sync_catalog(s)

    budget: Budget = nightly_budget(worker_token())
    async with db.session_scope() as s:
        await seed_benchmarks(s, budget)

    seeded = []
    for t in tickers:
        async with db.session_scope() as s:
            status = await seed_ticker(s, t, budget)
        seeded.append((t, status))
        log.info("seeded %s -> %s", t, status)

    # Live prices, so the first digest has something current to diff against.
    await fetch_quotes(tickers)

    # The checkpoint. Anchoring it a few sessions back is what makes the demo
    # show a real diff instead of a screen of zeroes on first load.
    from api.calendar_ny import get_calendar

    cal = get_calendar()
    ref_day = cal.session_n_ago(back_sessions, clock.today_et())
    bounds = cal.bounds(ref_day)
    seen_at = bounds.close_utc if bounds else clock.now() - dt.timedelta(days=1)

    async with db.session_scope() as s:
        for t in tickers:
            await s.execute(
                text(
                    "INSERT INTO watchlist_items (user_id, ticker, added_at)"
                    " VALUES (:u,:t,:now) ON CONFLICT DO NOTHING"
                ),
                {"u": uid, "t": t, "now": clock.now()},
            )
            await set_initial_snapshot(s, uid, t)
        await refresh_refcounts(s)

        await s.execute(
            text(
                """
            UPDATE watchlist_snapshots ws
               SET last_seen_at = :at,
                   is_initial = false,
                   last_seen_price = COALESCE(
                       (SELECT close FROM ticker_daily_bar b
                         WHERE b.ticker = ws.ticker AND b.bar_date = :d),
                       ws.last_seen_price),
                   last_seen_bench = COALESCE(
                       (SELECT close FROM ticker_daily_bar b
                         JOIN tickers t ON t.ticker = ws.ticker
                        WHERE b.ticker = t.benchmark_ticker AND b.bar_date = :d),
                       ws.last_seen_bench)
             WHERE ws.user_id = :u
            """
            ),
            {"at": seen_at, "d": ref_day, "u": uid},
        )

    async with db.session_scope() as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM watchlist_items WHERE user_id=:u"), {"u": uid}
            )
        ).scalar_one()
    if dispose:
        await db.dispose()
    return {
        "user_id": str(uid),
        "email": email,
        "watchlist": int(n),
        "reference_session": ref_day.isoformat(),
        "scenario": settings.replay_scenario,
        "seeded": seeded,
    }


async def fetch_quotes(tickers: list[str]) -> None:
    from api.config import BENCHMARK_UNIVERSE

    for t in list(dict.fromkeys(list(tickers) + list(BENCHMARK_UNIVERSE))):
        try:
            await fetch_one(t)
        except Exception:
            log.debug("quote %s unavailable", t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default=os.environ.get("DEMO_EMAIL", "you@example.com"))
    ap.add_argument("--tickers", default=",".join(DEMO_WATCHLIST))
    ap.add_argument(
        "--back-sessions",
        type=int,
        default=(
            int(os.environ["DEMO_BACK_SESSIONS"])
            if os.environ.get("DEMO_BACK_SESSIONS")
            else None
        ),
        help="how many sessions ago the demo user last looked "
             "(default: whatever the active scenario declares)",
    )
    args = ap.parse_args()
    out = asyncio.run(
        run(args.email, [t.strip().upper() for t in args.tickers.split(",") if t.strip()],
            args.back_sessions)
    )
    print(f"user_id  {out['user_id']}")
    print(f"email    {out['email']}")
    print(f"watching {out['watchlist']} tickers, last seen at {out['reference_session']}'s close")
    print(f"scenario {out['scenario']}")


if __name__ == "__main__":
    main()
