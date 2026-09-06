"""Corporate actions: detect and freeze. Never auto-rebase.

Bars are fetched with `adjust=splits`, so the provider restates history when a
split occurs and the divergence from stored bars is detectable exactly: the
close we already have for a date no longer matches the close the provider
returns for that same date.

An earlier design classified the split from the restatement signature and
rebased user reference prices automatically. It was rejected on scope and on
safety. Any automated rebase built on a heuristic can, in its failure mode,
silently suppress the most important alert the product will ever generate.
Detect-and-freeze is roughly a tenth of the code and strictly safer; the cost --
the user must remove and re-add -- is stated in the UI rather than hidden.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock
from providers.base import Bar

log = logging.getLogger("smw.corpactions")

RESTATEMENT_TOLERANCE = 0.005  # 0.5%: wider than rounding, narrower than any split


@dataclass
class Restatement:
    ticker: str
    effective_date: dt.date
    stored_close: float
    returned_close: float

    @property
    def ratio(self) -> float:
        return self.returned_close / self.stored_close

    def describe(self) -> str:
        r = self.ratio
        # A guess, offered as a guess. Nothing downstream depends on it being
        # right; it exists so the card can say something more useful than
        # "the numbers changed".
        for num, den, label in (
            (1, 2, "2:1 split"), (1, 3, "3:1 split"), (1, 4, "4:1 split"),
            (1, 5, "5:1 split"), (1, 10, "10:1 split"),
            (2, 1, "1:2 reverse split"), (10, 1, "1:10 reverse split"),
        ):
            if abs(r - num / den) < 0.02 * (num / den):
                return label
        return f"a {r:.3f}x restatement"


async def detect(
    session: AsyncSession, ticker: str, returned: list[Bar]
) -> Restatement | None:
    """Compare the returned close for the last date we already store."""
    if not returned:
        return None
    row = (
        await session.execute(
            text(
                "SELECT bar_date, close FROM ticker_daily_bar"
                " WHERE ticker = :t ORDER BY bar_date DESC LIMIT 1"
            ),
            {"t": ticker.upper()},
        )
    ).first()
    if row is None:
        return None
    last_date, stored = row[0], float(row[1])
    match = next((b for b in returned if b.bar_date == last_date), None)
    if match is None or stored <= 0:
        return None
    if abs(match.close / stored - 1.0) <= RESTATEMENT_TOLERANCE:
        return None
    return Restatement(ticker.upper(), last_date, stored, match.close)


async def freeze(session: AsyncSession, r: Restatement) -> None:
    """Write the action, freeze the baseline, touch NO snapshot.

    Not touching snapshots is the point: the user's reference price is theirs,
    and the only safe way to reset it is for them to do it.
    """
    await session.execute(
        text(
            """
        INSERT INTO corporate_actions
            (ticker, detected_at, effective_date, observed_ratio, acknowledged)
        VALUES (:t, :now, :d, :ratio, false)
        """
        ),
        {"t": r.ticker, "now": clock.now(), "d": r.effective_date, "ratio": r.ratio},
    )
    reason = (
        f"Provider restated {r.ticker}'s history -- likely {r.describe()}. "
        "Scores paused; remove and re-add to reset your reference price."
    )
    await session.execute(
        text(
            "UPDATE ticker_baseline SET frozen_reason = :why, updated_at = :now"
            " WHERE ticker = :t"
        ),
        {"why": reason, "now": clock.now(), "t": r.ticker},
    )
    log.warning("froze %s: %s", r.ticker, reason)


async def clear(session: AsyncSession, ticker: str) -> None:
    """Called when a user removes and re-adds: the freeze is theirs to clear."""
    t = ticker.upper()
    await session.execute(
        text("UPDATE ticker_baseline SET frozen_reason = NULL WHERE ticker = :t"),
        {"t": t},
    )
    await session.execute(
        text("UPDATE corporate_actions SET acknowledged = true WHERE ticker = :t"),
        {"t": t},
    )
