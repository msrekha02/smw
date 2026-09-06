"""The four signals.

All are computed over the user's window and all are built from ABSOLUTE
magnitudes, with direction carried separately. Ranking a signed composite means
a -5 sigma crash sorts below a +0.5 sigma drift and never reaches the digest.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Sequence

from api.config import EARNINGS_VOL_MULT, MIN_N_EFF, SIGMA_FLOOR


def clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def window_days(
    recent_daily: Sequence[dict[str, Any]],
    ref_at: dt.datetime,
    now: dt.datetime,
    cal,
) -> list[dict[str, Any]]:
    """The stored daily rows whose session actually falls inside the window.

    Membership is decided by the session's CLOSE, not by its date: a row belongs
    if its close happened after the user's checkpoint and at or before now. That
    single rule is correct for a close-anchored window, a same-session recheck
    and an overnight gap alike.

    Getting this wrong is expensive and quiet. Passing the whole 30-row history
    through unfiltered makes `z_path` report the largest move of the last six
    weeks as if it happened while the user was away, and every ticker becomes
    critical on the strength of an event they already saw.
    """
    out: list[dict[str, Any]] = []
    for d in recent_daily:
        try:
            day = dt.date.fromisoformat(str(d.get("d", "")))
        except ValueError:
            continue
        b = cal.bounds(day)
        if b is None:
            continue
        if ref_at < b.close_utc <= now:
            out.append(d)
    return out


def window_path(
    wd: Sequence[dict[str, Any]], excess: float, n_eff: float
) -> list[dict[str, Any]]:
    """The cumulative excess-return path across the window, for plotting.

    Takes the rows `window_days` already selected rather than re-deciding
    membership, so the line on screen is drawn over exactly the sessions that
    were scored. `t` is elapsed sessions, which is what the expected-range cone
    is a function of: the band at `t` is sigma_idio * sqrt(t).

    The final point is the window's `excess`, measured endpoint-to-endpoint off
    the live price, not the running sum of close-to-close rows. Those two differ
    intraday, and the line has to end on the number the card reports.
    """
    out: list[dict[str, Any]] = []
    cum = 0.0
    for k, d in enumerate(wd, start=1):
        cum += float(d.get("exc", 0.0))
        out.append({"t": float(k), "cum": round(cum, 6), "d": str(d.get("d", ""))})

    t_now = max(round(float(n_eff), 4), out[-1]["t"] if out else 0.0)
    if out and abs(out[-1]["t"] - t_now) < 1e-6:
        out[-1] = {**out[-1], "cum": round(excess, 6)}
    else:
        out.append({"t": t_now, "cum": round(excess, 6), "d": ""})
    return out


# ---------------------------------------------------------------------------
# S1: idiosyncratic displacement
# ---------------------------------------------------------------------------


def expected_sigma(sigma_idio: float, n_eff: float, n_earnings: float) -> float:
    """Dispersion over a window of `n_eff` sessions, `n_earnings` of them
    scheduled earnings days.

    Earnings widens the denominator; it does not add score. An earlier version
    added a flat bonus when earnings fell in the window, which is wrong twice.
    It double-counts -- the price reaction IS the surprise, and z_move already
    contains it. And it has the wrong sign: a 3 sigma move on a scheduled
    earnings day is LESS surprising than one on a random Tuesday, because
    everyone knew a catalyst was landing.

    Variance is additive across days, so the correct treatment is here.
    """
    s = max(sigma_idio, SIGMA_FLOOR)
    n_earn = clip(n_earnings, 0.0, max(n_eff, 0.0))
    n_ord = max(n_eff - n_earn, 0.0)
    var = s * s * n_ord + (s * EARNINGS_VOL_MULT) ** 2 * n_earn
    return math.sqrt(max(var, s * s * MIN_N_EFF))


def z_move(excess: float, sigma_exp: float) -> float:
    return excess / max(sigma_exp, 1e-12)


# ---------------------------------------------------------------------------
# S2: path
# ---------------------------------------------------------------------------


def z_path(win: Sequence[dict[str, Any]], sigma_idio: float) -> tuple[float, str | None]:
    """The largest single-day idiosyncratic move inside the window.

    z_move compares two endpoints, so a stock that spiked 12% and round-tripped
    to flat scores zero. For someone away a week that is a total miss of a real
    event. No consumer watchlist does this.
    """
    best, on = 0.0, None
    s = max(sigma_idio, SIGMA_FLOOR)
    for d in win:
        v = abs(float(d.get("exc", 0.0))) / s
        if v > best:
            best, on = v, str(d.get("d"))
    return best, on


# ---------------------------------------------------------------------------
# S3: volume
# ---------------------------------------------------------------------------


def vol_score(win: Sequence[dict[str, Any]]) -> tuple[float, float]:
    """log2 of the peak volume ratio, clamped to [0, 3].

    Doubling normal volume scores 1, eight times scores 3. Returns the score and
    the raw ratio, because the ratio is what the reason string says out loud.
    """
    peak = 1.0
    for d in win:
        r = float(d.get("volr", 1.0) or 1.0)
        if r > peak:
            peak = r
    return clip(math.log2(max(peak, 1e-9)), 0.0, 3.0), peak


# ---------------------------------------------------------------------------
# S4: 52-week breach
# ---------------------------------------------------------------------------


@dataclass
class Breach:
    score: float
    direction: str | None  # "high" | "low"
    level: float | None
    distance: float  # fractional distance beyond the prior extreme


def breach_score(
    win: Sequence[dict[str, Any]],
    fallback_high: float | None,
    fallback_low: float | None,
    sigma_idio: float,
) -> Breach:
    """Continuous rather than binary.

    Touching the record the window INHERITED scores 1.0; every further sigma
    beyond it adds another point, capped at 3. A stock that pokes one cent above
    its old high and one that gaps 8% through it are not the same event.

    The reference is the extreme carried on the window's first row (`hh`/`ll`),
    which is the record as of the session before the window opened.
    """
    if not win:
        return Breach(0.0, None, None, 0.0)
    s = max(sigma_idio, SIGMA_FLOOR)
    prior_high = win[0].get("hh") or fallback_high
    prior_low = win[0].get("ll") or fallback_low

    hi = max((float(d.get("high", d.get("close", 0.0)) or 0.0) for d in win), default=0.0)
    lows = [
        float(d.get("low") or d.get("close") or 0.0)
        for d in win
        if (d.get("low") or d.get("close"))
    ]
    lo = min(lows) if lows else 0.0

    up = (hi / prior_high - 1.0) if prior_high else -1.0
    dn = (prior_low / lo - 1.0) if (prior_low and lo > 0) else -1.0

    if up < 0 and dn < 0:
        return Breach(0.0, None, None, 0.0)
    if up >= dn:
        return Breach(clip(1.0 + up / s, 0.0, 3.0), "high", prior_high, up)
    return Breach(clip(1.0 + dn / s, 0.0, 3.0), "low", prior_low, dn)


# ---------------------------------------------------------------------------
# Earnings inside the window
# ---------------------------------------------------------------------------


def earnings_in_window(
    dates: Sequence[dt.date], ref_date_exclusive: dt.date | None, now_date: dt.date
) -> list[dt.date]:
    """Earnings sessions strictly after the anchor date, through today.

    For a close-anchored window the anchor date itself is excluded: its close is
    the reference, so whatever happened that day is already in the price the
    user checkpointed. For an intraday anchor the caller passes the day before,
    because the rest of that session IS inside the window.
    """
    if ref_date_exclusive is None:
        return [d for d in dates if d == now_date]
    return sorted(d for d in dates if ref_date_exclusive < d <= now_date)
