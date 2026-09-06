"""The live sanity filter.

This filter is allowed to be crude, and that is a consequence of the two-clock
split rather than an oversight. Nothing intraday ever writes to a statistic, so
the worst a bad tick can do is produce one wrong card for one poll cycle,
self-healing on the next. A filter that also had to protect a shared estimator
would need a threshold tight enough to catch corruption and loose enough not to
quarantine real news, and no single value does both.

A suspicious print is HELD, not dropped: held prices are surfaced as
`verifying`, and the hold times out after three intervals so a real gap
eventually gets through.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from api.config import SANITY_HOLD_CYCLES, SANITY_JUMP

Verdict = Literal["accept", "hold", "no_data"]


@dataclass
class SanityState:
    last_good: float | None = None
    prev_close: float | None = None
    pending_price: float | None = None
    pending_since: dt.datetime | None = None
    pending_cycles: int = 0


@dataclass
class SanityResult:
    verdict: Verdict
    price: float | None
    status: str                 # ok | verifying | no_data
    pending_price: float | None = None
    pending_cycles: int = 0
    note: str | None = None


def check(price: float | None, st: SanityState, now: dt.datetime) -> SanityResult:
    if price is None or price <= 0:
        return SanityResult("no_data", None, "no_data", note="non-positive price")

    refs = [r for r in (st.last_good, st.prev_close) if r and r > 0]
    if not refs:
        return SanityResult("accept", price, "ok")

    # Implausible only if it disagrees with BOTH references. A stock that gapped
    # overnight disagrees with prev_close but not with the last good print, and
    # a genuine intraday halt-and-reopen is the other way round.
    jumps = [abs(price / r - 1.0) for r in refs]
    if min(jumps) <= SANITY_JUMP:
        return SanityResult("accept", price, "ok")

    # The same suspicious level twice running is news, not corruption.
    if st.pending_price and abs(price / st.pending_price - 1.0) < 0.01:
        cycles = st.pending_cycles + 1
        if cycles >= SANITY_HOLD_CYCLES:
            return SanityResult(
                "accept", price, "ok", note="released after repeated confirmation"
            )
        return SanityResult(
            "hold", None, "verifying", pending_price=price, pending_cycles=cycles
        )

    if st.pending_since and (now - st.pending_since).total_seconds() > 180:
        return SanityResult("accept", price, "ok", note="hold timed out")

    return SanityResult(
        "hold",
        None,
        "verifying",
        pending_price=price,
        pending_cycles=1,
        note=f"{min(jumps) * 100:.1f}% from both references",
    )
