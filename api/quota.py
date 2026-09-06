"""Partitioned provider budgets.

Twelve Data's free tier is 800 credits/day. Without partitioning, one user
adding 200 tickers starves baseline freshness for everyone -- so the nightly
reserve is not merely accounted separately, it is *unreachable* from any
user-triggered code path.

    640  RESERVED  nightly baselines
    120  SEEDING   new tickers, global queue, 20/user/day
     40  CATALOG   symbol sync, market state, slack

Enforcement is structural, not by convention: `user_budget()` cannot construct a
reserve budget, and `Budget` refuses to be built against RESERVED without an
explicit worker-only token. A user path that tries gets `ReserveViolation`,
which is a bug, not a rate limit.
"""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock
from api.config import (
    SEED_CREDITS_PER_USER_PER_DAY,
    TD_CATALOG,
    TD_RESERVED,
    TD_SEEDING,
)


class Partition(str, enum.Enum):
    RESERVED = "reserved"
    SEEDING = "seeding"
    CATALOG = "catalog"


LIMITS: dict[Partition, int] = {
    Partition.RESERVED: TD_RESERVED,
    Partition.SEEDING: TD_SEEDING,
    Partition.CATALOG: TD_CATALOG,
}

# Only worker-side callers hold this. It is deliberately not exported through
# `api.quota.__all__`-style convenience; user paths call `user_budget()`.
_WORKER_TOKEN = object()


class QuotaError(RuntimeError):
    pass


class ReserveViolation(QuotaError):
    """A user-triggered path tried to reach the nightly reserve."""


class Exhausted(QuotaError):
    """The partition is out of credits for today. Degrade, do not reject."""

    def __init__(self, partition: Partition, limit: int):
        super().__init__(f"{partition.value} partition exhausted ({limit}/day)")
        self.partition = partition
        self.limit = limit


@dataclass
class Grant:
    partition: Partition
    granted: int
    spent_today: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(self.limit - self.spent_today, 0)


class Budget:
    """A handle on exactly one partition. Spending goes through the DB ledger,
    so two API instances and the worker cannot each believe they have 640."""

    def __init__(self, partition: Partition, _token: object | None = None) -> None:
        if partition is Partition.RESERVED and _token is not _WORKER_TOKEN:
            raise ReserveViolation(
                "the nightly reserve is not addressable from this code path"
            )
        self.partition = partition
        self.limit = LIMITS[partition]

    def __repr__(self) -> str:  # pragma: no cover
        return f"Budget({self.partition.value}, limit={self.limit})"

    async def try_spend(self, session: AsyncSession, n: int = 1) -> Grant:
        """Atomically reserve up to `n` credits. Returns what was granted.

        Partial grants are deliberate: a nightly run that can only refresh 400
        of 600 tickers should refresh 400, in refcount order, not zero.
        """
        today = clock.today_et()
        row = (
            await session.execute(
                text(
                    """
                INSERT INTO quota_ledger (partition, usage_date, spent)
                VALUES (:p, :d, 0)
                ON CONFLICT (partition, usage_date) DO UPDATE
                   SET spent = quota_ledger.spent
                RETURNING spent
                """
                ),
                {"p": self.partition.value, "d": today},
            )
        ).scalar_one()
        granted = max(min(n, self.limit - int(row)), 0)
        if granted:
            await session.execute(
                text(
                    """
                UPDATE quota_ledger SET spent = spent + :n
                 WHERE partition = :p AND usage_date = :d
                """
                ),
                {"n": granted, "p": self.partition.value, "d": today},
            )
        return Grant(self.partition, granted, int(row) + granted, self.limit)

    async def spend(self, session: AsyncSession, n: int = 1) -> None:
        g = await self.try_spend(session, n)
        if g.granted < n:
            raise Exhausted(self.partition, self.limit)

    async def status(self, session: AsyncSession) -> Grant:
        today = clock.today_et()
        spent = (
            await session.execute(
                text(
                    "SELECT spent FROM quota_ledger WHERE partition=:p AND usage_date=:d"
                ),
                {"p": self.partition.value, "d": today},
            )
        ).scalar()
        return Grant(self.partition, 0, int(spent or 0), self.limit)


def user_budget() -> Budget:
    """The only budget a request handler may hold."""
    return Budget(Partition.SEEDING)


def catalog_budget() -> Budget:
    return Budget(Partition.CATALOG)


def nightly_budget(token: object) -> Budget:
    """Worker-only. `token` must be the module's worker token."""
    return Budget(Partition.RESERVED, token)


def worker_token() -> object:
    """Imported by `worker.*` only. Kept as a function so a user-path import of
    a bare constant does not accidentally grant access."""
    return _WORKER_TOKEN


# ---------------------------------------------------------------------------
# Per-user daily seeding allowance
# ---------------------------------------------------------------------------


async def take_user_seed_credit(
    session: AsyncSession, user_id: uuid.UUID, n: int = 1
) -> bool:
    """Charge the user's own daily seeding allowance. False if they are out.

    Separate from the global partition on purpose: the global partition protects
    the system, this protects other users from one enthusiastic one.
    """
    today = clock.today_et()
    res = await session.execute(
        text(
            """
        UPDATE app_users
           SET seed_credits_used_today =
                 CASE WHEN seed_credits_reset_on < :today THEN :n
                      ELSE seed_credits_used_today + :n END,
               seed_credits_reset_on = :today
         WHERE id = :uid
           AND (seed_credits_reset_on < :today
                OR seed_credits_used_today + :n <= :cap)
        RETURNING seed_credits_used_today
        """
        ),
        {"uid": user_id, "today": today, "n": n, "cap": SEED_CREDITS_PER_USER_PER_DAY},
    )
    return res.scalar() is not None


async def user_seed_credits_left(session: AsyncSession, user_id: uuid.UUID) -> int:
    today = clock.today_et()
    row = (
        await session.execute(
            text(
                "SELECT seed_credits_used_today, seed_credits_reset_on"
                " FROM app_users WHERE id = :uid"
            ),
            {"uid": user_id},
        )
    ).first()
    if row is None:
        return 0
    used, reset_on = row
    if reset_on < today:
        return SEED_CREDITS_PER_USER_PER_DAY
    return max(SEED_CREDITS_PER_USER_PER_DAY - int(used), 0)


async def snapshot(session: AsyncSession) -> dict[str, dict[str, int]]:
    """All three partitions, for the ops surface."""
    today: dt.date = clock.today_et()
    rows = (
        await session.execute(
            text("SELECT partition, spent FROM quota_ledger WHERE usage_date = :d"),
            {"d": today},
        )
    ).all()
    spent = {r[0]: int(r[1]) for r in rows}
    return {
        p.value: {
            "limit": LIMITS[p],
            "spent": spent.get(p.value, 0),
            "remaining": max(LIMITS[p] - spent.get(p.value, 0), 0),
        }
        for p in Partition
    }
