"""Integrity: quota partitions, the ack contract, the ledger, and freezing.

These need a real Postgres because they are claims about concurrency and
transaction boundaries, and an in-memory stand-in would prove nothing about
either.
"""
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from api import clock, digest_token, quota
from api.calendar_ny import UTC
from api.digest_token import Observed

pytestmark = pytest.mark.asyncio(loop_scope="function")


async def _fresh(dbmod):
    """A clean slate for one test."""
    await dbmod.run_migrations(direct=True)
    async with dbmod.session_scope() as s:
        await s.execute(text("DELETE FROM quota_ledger"))
        await s.execute(text("DELETE FROM job_item"))
        await s.execute(text("DELETE FROM job_run"))
        await s.execute(text("DELETE FROM provider_response_cache"))
        await s.execute(text("DELETE FROM watchlist_snapshots"))
        await s.execute(text("DELETE FROM watchlist_items"))
        await s.execute(text("DELETE FROM corporate_actions"))
        await s.execute(text("DELETE FROM ticker_baseline"))
        await s.execute(text("DELETE FROM ticker_daily_bar"))
        await s.execute(text("DELETE FROM ticker_latest"))
        await s.execute(text("DELETE FROM tickers"))
        await s.execute(text("DELETE FROM app_users"))


async def _user(dbmod, uid: uuid.UUID) -> None:
    async with dbmod.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO app_users (id, seed_credits_reset_on, created_at)"
                " VALUES (:id, :d, :now) ON CONFLICT DO NOTHING"
            ),
            {"id": uid, "d": clock.today_et(), "now": clock.now()},
        )


async def _ticker(dbmod, t: str, bench: str | None = "XLK") -> None:
    async with dbmod.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO tickers (ticker, instrument_class, benchmark_ticker, status)"
                " VALUES (:t, 'stock', :b, 'active') ON CONFLICT DO NOTHING"
            ),
            {"t": t, "b": bench},
        )


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------


async def test_the_etf_name_backfill_matches_the_static_map():
    """The migration and `api/config.py` name the same instruments.

    Two hand-maintained lists of the same facts drift, and the failure is
    silent: an instrument added to one and not the other shows a blank name or
    a raw enum in the watchlist. This turns that into a failing test instead.
    """
    import pathlib
    import re

    from api.config import BROAD_ETFS, ETF_NAMES, ETF_SECTORS, SECTOR_ETFS

    sql = (
        pathlib.Path(__file__).resolve().parent.parent / "db" / "002_etf_names.sql"
    ).read_text(encoding="utf-8")

    # Two VALUES blocks: names first, then sectors.
    name_block, sector_block = sql.split("UPDATE tickers AS t")[1:3]
    pairs = lambda block: {
        m.group(1): m.group(2).replace("''", "'")
        for m in re.finditer(r"\('([A-Z]+)',\s*'((?:[^']|'')*)'\)", block)
    }

    assert pairs(name_block) == ETF_NAMES, "migration names drifted from ETF_NAMES"
    assert pairs(sector_block) == ETF_SECTORS, "migration sectors drifted from ETF_SECTORS"

    # And the map covers every instrument this system picks for itself.
    assert set(ETF_NAMES) == SECTOR_ETFS | BROAD_ETFS
    assert set(ETF_SECTORS) == SECTOR_ETFS


async def test_a_user_path_cannot_construct_a_reserve_budget(db):
    """The reserve is not merely accounted separately, it is unreachable."""
    with pytest.raises(quota.ReserveViolation):
        quota.Budget(quota.Partition.RESERVED)
    with pytest.raises(quota.ReserveViolation):
        quota.Budget(quota.Partition.RESERVED, _token=object())

    assert quota.user_budget().partition is quota.Partition.SEEDING
    assert quota.catalog_budget().partition is quota.Partition.CATALOG
    assert (
        quota.nightly_budget(quota.worker_token()).partition is quota.Partition.RESERVED
    )


async def test_user_seeding_cannot_drain_the_nightly_reserve(db):
    await _fresh(db)
    ub = quota.user_budget()
    async with db.session_scope() as s:
        # Exhaust the entire seeding partition.
        g = await ub.try_spend(s, quota.TD_SEEDING + 50)
        assert g.granted == quota.TD_SEEDING

        with pytest.raises(quota.Exhausted):
            await ub.spend(s, 1)

        # The reserve is untouched and still fully available to the worker.
        nb = quota.nightly_budget(quota.worker_token())
        st = await nb.status(s)
        assert st.spent_today == 0
        assert st.remaining == quota.TD_RESERVED


async def test_partial_grants_let_a_run_do_what_it_can(db):
    await _fresh(db)
    nb = quota.nightly_budget(quota.worker_token())
    async with db.session_scope() as s:
        await nb.try_spend(s, quota.TD_RESERVED - 5)
        g = await nb.try_spend(s, 20)
    assert g.granted == 5, "a run that can refresh 5 more tickers should refresh 5"


async def test_per_user_daily_seed_allowance(db):
    await _fresh(db)
    uid = uuid.uuid4()
    await _user(db, uid)
    async with db.session_scope() as s:
        for _ in range(quota.SEED_CREDITS_PER_USER_PER_DAY):
            assert await quota.take_user_seed_credit(s, uid, 1) is True
        assert await quota.take_user_seed_credit(s, uid, 1) is False
        assert await quota.user_seed_credits_left(s, uid) == 0


# ---------------------------------------------------------------------------
# Ack
# ---------------------------------------------------------------------------


async def _snapshot(dbmod, uid, ticker, at, price=100.0):
    async with dbmod.session_scope() as s:
        await s.execute(
            text(
                """
            INSERT INTO watchlist_items (user_id, ticker, added_at)
            VALUES (:u, :t, :now) ON CONFLICT DO NOTHING
            """
            ),
            {"u": uid, "t": ticker, "now": clock.now()},
        )
        await s.execute(
            text(
                """
            INSERT INTO watchlist_snapshots (user_id, ticker, last_seen_price,
                last_seen_bench, last_seen_bench_ticker, last_seen_at, is_initial)
            VALUES (:u, :t, :px, 100.0, 'XLK', :at, true)
            ON CONFLICT (user_id, ticker) DO UPDATE
                SET last_seen_at = EXCLUDED.last_seen_at,
                    last_seen_price = EXCLUDED.last_seen_price
            """
            ),
            {"u": uid, "t": ticker, "px": price, "at": at},
        )


async def _apply_ack(dbmod, uid, ticker, o: Observed) -> str:
    async with dbmod.session_scope() as s:
        row = (
            await s.execute(
                text(
                    """
            UPDATE watchlist_snapshots
               SET last_seen_price=:px, last_seen_bench=:b,
                   last_seen_bench_ticker=:bt, last_seen_at=:at, is_initial=false
             WHERE user_id=:u AND ticker=:t AND last_seen_at < :at
            RETURNING ticker
            """
                ),
                {"px": o.px, "b": o.bench, "bt": o.bt, "at": o.at, "u": uid, "t": ticker},
            )
        ).first()
    return "applied" if row else "superseded"


async def test_acks_are_monotonic_and_order_independent(db):
    """Two devices can ack in any order, the later observation wins, and an old
    tab cannot rewind the checkpoint."""
    await _fresh(db)
    uid = uuid.uuid4()
    await _user(db, uid)
    await _ticker(db, "NVDA")
    t0 = dt.datetime(2025, 9, 2, 14, 0, tzinfo=UTC)
    await _snapshot(db, uid, "NVDA", t0, price=100.0)

    early = Observed(101.0, 100.0, "XLK", t0 + dt.timedelta(minutes=10))
    late = Observed(105.0, 100.0, "XLK", t0 + dt.timedelta(minutes=30))

    assert await _apply_ack(db, uid, "NVDA", late) == "applied"
    assert await _apply_ack(db, uid, "NVDA", early) == "superseded"

    async with db.session_scope() as s:
        px, at, initial = (
            await s.execute(
                text(
                    "SELECT last_seen_price, last_seen_at, is_initial"
                    " FROM watchlist_snapshots WHERE user_id=:u AND ticker=:t"
                ),
                {"u": uid, "t": "NVDA"},
            )
        ).one()
    assert px == 105.0, "the later observation wins regardless of arrival order"
    assert at == late.at
    assert initial is False


async def test_re_acking_the_same_token_is_idempotent(db):
    await _fresh(db)
    uid = uuid.uuid4()
    await _user(db, uid)
    await _ticker(db, "AMD")
    t0 = dt.datetime(2025, 9, 2, 14, 0, tzinfo=UTC)
    await _snapshot(db, uid, "AMD", t0)

    o = Observed(150.0, 100.0, "XLK", t0 + dt.timedelta(minutes=5))
    assert await _apply_ack(db, uid, "AMD", o) == "applied"
    assert await _apply_ack(db, uid, "AMD", o) == "superseded", (
        "a zero-row update returning a bare 200 causes a silent re-ack loop"
    )


async def test_each_ticker_checkpoints_at_its_own_timestamp(db):
    """A digest mixes a WebSocket price from two seconds ago with a cold-tier
    close from yesterday."""
    await _fresh(db)
    uid = uuid.uuid4()
    await _user(db, uid)
    for t in ("NVDA", "DUK"):
        await _ticker(db, t)
    base = dt.datetime(2025, 9, 2, 14, 0, tzinfo=UTC)
    await _snapshot(db, uid, "NVDA", base)
    await _snapshot(db, uid, "DUK", base)

    hot = Observed(176.0, 268.0, "XLK", base + dt.timedelta(seconds=2))
    cold = Observed(122.0, 85.0, "XLU", base + dt.timedelta(hours=18))
    tok = digest_token.issue(uid, {"NVDA": hot, "DUK": cold}, clock.now())
    back = digest_token.verify(tok, uid)

    for t, o in back.items():
        await _apply_ack(db, uid, t, o)

    async with db.session_scope() as s:
        rows = dict(
            (r[0], r[1])
            for r in (
                await s.execute(
                    text(
                        "SELECT ticker, last_seen_at FROM watchlist_snapshots"
                        " WHERE user_id=:u"
                    ),
                    {"u": uid},
                )
            ).all()
        )
    assert rows["NVDA"] != rows["DUK"]
    assert rows["DUK"] == cold.at


# ---------------------------------------------------------------------------
# Corporate actions
# ---------------------------------------------------------------------------


async def test_restatement_freezes_and_mutates_no_snapshot(db):
    """Any automated rebase built on a heuristic can, in its failure mode,
    silently suppress the most important alert the product will ever generate."""
    from providers.base import Bar
    from worker.nightly import corporate_actions

    await _fresh(db)
    uid = uuid.uuid4()
    await _user(db, uid)
    await _ticker(db, "NVDA")

    day = dt.date(2025, 8, 29)
    async with db.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO ticker_daily_bar (ticker,bar_date,open,high,low,close,volume)"
                " VALUES ('NVDA',:d,700,710,690,704,1000)"
            ),
            {"d": day},
        )
        await s.execute(
            text(
                "INSERT INTO ticker_baseline (ticker, updated_at) VALUES ('NVDA', :now)"
            ),
            {"now": clock.now()},
        )
    await _snapshot(db, uid, "NVDA", dt.datetime(2025, 8, 29, 20, 0, tzinfo=UTC), price=704.0)

    # A 4:1 split: the provider restates the same date at a quarter of the price.
    returned = [Bar(day, 175.0, 177.5, 172.5, 176.0, 4000)]
    async with db.session_scope() as s:
        rest = await corporate_actions.detect(s, "NVDA", returned)
        assert rest is not None
        assert rest.ratio == pytest.approx(0.25, rel=0.01)
        assert "4:1 split" in rest.describe()
        await corporate_actions.freeze(s, rest)

    async with db.session_scope() as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM corporate_actions WHERE ticker='NVDA'")
            )
        ).scalar_one()
        frozen = (
            await s.execute(
                text("SELECT frozen_reason FROM ticker_baseline WHERE ticker='NVDA'")
            )
        ).scalar_one()
        px = (
            await s.execute(
                text(
                    "SELECT last_seen_price FROM watchlist_snapshots"
                    " WHERE user_id=:u AND ticker='NVDA'"
                ),
                {"u": uid},
            )
        ).scalar_one()

    assert n == 1
    assert "remove and re-add" in frozen.lower()
    assert px == 704.0, "the user's reference price is theirs; freezing must not touch it"


async def test_a_normal_days_bars_are_not_mistaken_for_a_restatement(db):
    from providers.base import Bar
    from worker.nightly import corporate_actions

    await _fresh(db)
    await _ticker(db, "AAPL")
    day = dt.date(2025, 8, 29)
    async with db.session_scope() as s:
        await s.execute(
            text(
                "INSERT INTO ticker_daily_bar (ticker,bar_date,open,high,low,close,volume)"
                " VALUES ('AAPL',:d,231,233,230,232.00,1000)"
            ),
            {"d": day},
        )
        # A 0.1% difference is rounding, not a corporate action.
        assert await corporate_actions.detect(s, "AAPL", [Bar(day, 231, 233, 230, 232.2, 1000)]) is None
