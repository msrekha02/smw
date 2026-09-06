"""Resolving "since you last looked" into a reference price and a dispersion.

Two rules do the work here.

**Windows of 2+ trading days anchor to a close.** Sigma is estimated from
close-to-close returns, but `last_seen_price` is whatever the price was at
10:03am on a Tuesday. Measuring an intraday-anchored return against
close-to-close-calibrated volatility carries extra noise the denominator does
not know about, biasing z upward -- more false positives, in the direction the
design least wants. "Since Friday's close, -6.2%" is both statistically
consistent and a better sentence.

**Dispersion never reaches zero.** A same-session recheck spans a fraction of a
day, and `sigma * sqrt(0)` would produce 0/0 on every row.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from api.calendar_ny import ET, TradingCalendar, et_date
from api.config import MAX_WINDOW_DAYS, MIN_N_EFF

CloseLookup = Callable[[str, dt.date], float | None]


@dataclass
class Snapshot:
    """The user's checkpoint for one ticker."""

    ticker: str
    last_seen_price: float
    last_seen_bench: float
    last_seen_bench_ticker: str
    last_seen_at: dt.datetime
    is_initial: bool = False


@dataclass
class Window:
    ref_price: float | None
    ref_bench: float | None
    ref_at: dt.datetime
    now: dt.datetime
    ref_date: dt.date | None       # None when anchored intraday
    n_days: int
    n_eff: float
    capped: bool
    anchor: str                    # "close" | "intraday"
    bench_ticker: str
    notes: list[str] = field(default_factory=list)
    ok: bool = True

    @property
    def same_day(self) -> bool:
        """Whether the anchor sits inside today's session.

        `n_days` counts session CLOSES crossed, which is zero both for a recheck
        an hour later and for a Friday-evening checkpoint viewed on Tuesday when
        Monday was a holiday. Only the calendar date separates those two, and
        calling the second one "today" is simply wrong.
        """
        return et_date(self.ref_at) == et_date(self.now)

    @property
    def since_label(self) -> str:
        if self.capped:
            return f"the last {MAX_WINDOW_DAYS} trading days"
        if self.anchor == "close" and self.ref_date:
            return f"{self.ref_date.strftime('%A')}'s close"
        if self.same_day:
            return "you last looked"
        return f"{self.ref_at.astimezone(ET).strftime('%A')}"


def resolve_window(
    snap: Snapshot,
    now: dt.datetime,
    cal: TradingCalendar,
    benchmark_ticker: str | None,
    close_on: CloseLookup,
) -> Window:
    """Pick the reference endpoint and the matching dispersion.

    `benchmark_ticker` is the ticker's CURRENT benchmark, which may differ from
    the one stored on the snapshot if a sector reclassification landed
    mid-window. Dividing two unrelated ETFs would fabricate an excess return, so
    that case is detected and reported rather than papered over.
    """
    notes: list[str] = []
    bench = benchmark_ticker or snap.last_seen_bench_ticker
    n_raw = cal.sessions_between(snap.last_seen_at, now)

    if n_raw > MAX_WINDOW_DAYS:
        # Capping n_days without moving the reference price inflates z by
        # sqrt(actual/30). Both must move together.
        ref_date = cal.session_n_ago(MAX_WINDOW_DAYS, et_date(now))
        ref_price = close_on(snap.ticker, ref_date)
        ref_bench = close_on(bench, ref_date) if bench else None
        anchor_at = _close_at(cal, ref_date) or snap.last_seen_at
        return _finish(
            snap, cal, now, ref_price, ref_bench, anchor_at, ref_date,
            capped=True, anchor="close", bench=bench, notes=notes,
        )

    if n_raw >= 2:
        ref_date = cal.session_on_or_before(et_date(snap.last_seen_at))
        ref_price = close_on(snap.ticker, ref_date)
        ref_bench = close_on(bench, ref_date) if bench else None
        anchor_at = _close_at(cal, ref_date) or snap.last_seen_at
        if ref_price is None:
            # No stored bar for that session: fall back to the checkpoint price
            # and say so, rather than silently scoring against nothing.
            notes.append("no stored close for the reference session")
            return _finish(
                snap, cal, now, snap.last_seen_price, snap.last_seen_bench,
                snap.last_seen_at, None, capped=False, anchor="intraday",
                bench=bench, notes=notes,
            )
        return _finish(
            snap, cal, now, ref_price, ref_bench, anchor_at, ref_date,
            capped=False, anchor="close", bench=bench, notes=notes,
        )

    # Same session, or one overnight gap: the user's own checkpoint price is
    # the honest reference, and the session-fraction scaling is already correct.
    ref_bench = snap.last_seen_bench
    if bench != snap.last_seen_bench_ticker:
        prev = close_on(snap.last_seen_bench_ticker, et_date(snap.last_seen_at))
        alt = close_on(bench, et_date(snap.last_seen_at))
        if alt is not None:
            ref_bench = alt
            notes.append(
                f"benchmark changed {snap.last_seen_bench_ticker} -> {bench} mid-window"
            )
        else:
            notes.append("benchmark_unavailable")
        del prev
    return _finish(
        snap, cal, now, snap.last_seen_price, ref_bench, snap.last_seen_at,
        None, capped=False, anchor="intraday", bench=bench, notes=notes,
    )


def _close_at(cal: TradingCalendar, d: dt.date) -> dt.datetime | None:
    b = cal.bounds(d)
    return b.close_utc if b else None


def _finish(
    snap: Snapshot,
    cal: TradingCalendar,
    now: dt.datetime,
    ref_price: float | None,
    ref_bench: float | None,
    anchor_at: dt.datetime,
    ref_date: dt.date | None,
    *,
    capped: bool,
    anchor: str,
    bench: str,
    notes: list[str],
) -> Window:
    span = cal.session_span(anchor_at, now)
    n_days = cal.sessions_between(anchor_at, now)
    if capped:
        span = min(span, float(MAX_WINDOW_DAYS) + 1.0)
        n_days = MAX_WINDOW_DAYS
    return Window(
        ref_price=ref_price,
        ref_bench=ref_bench,
        ref_at=anchor_at,
        now=now,
        ref_date=ref_date,
        n_days=n_days,
        n_eff=max(span, MIN_N_EFF),
        capped=capped,
        anchor=anchor,
        bench_ticker=bench,
        notes=notes,
        ok=ref_price is not None and ref_price > 0,
    )
