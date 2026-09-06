"""One line saying why.

The reason string is the product. A number without a sentence is a number the
user has to interpret; the whole promise is that they do not have to. Every
clause here is derived from a quantity that was actually used in the score, so
the sentence cannot drift away from the ranking.

Earnings appears as an unscored context tag: it widens the denominator, so
saying "on earnings" explains why the bar was higher, not why the score was.
"""
from __future__ import annotations

import datetime as dt

from api.calendar_ny import ET
from api.scoring.score import ScoreResult

SECTOR_WORD = {
    "XLK": "tech", "XLF": "financials", "XLE": "energy", "XLV": "healthcare",
    "XLI": "industrials", "XLY": "consumer discretionary",
    "XLP": "consumer staples", "XLU": "utilities", "XLRE": "real estate",
    "XLB": "materials", "XLC": "communications", "SPY": "the market",
}


def _pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:+.{digits}f}%"


def _abs_pct(x: float, digits: int = 1) -> str:
    return f"{abs(x) * 100:.{digits}f}%"


def _sector(t: str | None) -> str:
    return SECTOR_WORD.get((t or "").upper(), (t or "its sector").upper())


def _bench_clause(r: ScoreResult) -> str:
    b = r.bench_return
    if r.beta_used == 0.0:
        return ""
    name = _sector(r.window.bench_ticker)
    if abs(b) < 0.002:
        return f" while {name} was flat"
    return f" while {name} moved {_pct(b)}"


def _when(r: ScoreResult) -> str:
    w = r.window
    if w.capped:
        return "over the last 30 trading days"
    if w.anchor == "close" and w.ref_date:
        return f"since {w.ref_date.strftime('%A')}'s close"
    if w.same_day:
        return "since you last looked"
    # Naming the day beats "since yesterday", which is simply false when a
    # holiday sits in the gap: Tuesday's previous session is Friday.
    local = w.ref_at.astimezone(ET)
    return f"since {local:%A}" + ("'s close" if local.hour >= 16 else "")


def build(r: ScoreResult, *, is_initial: bool = False) -> str:
    if is_initial:
        return "Added to your watchlist. The next visit is measured from here."
    if r.window.ref_price is None:
        return "No reference price yet for this window."

    # A round trip is the case z_move cannot see, so it gets its own sentence.
    round_trip = abs(r.z_move) < 1.0 and r.z_path >= 2.0
    if round_trip:
        day = _friendly_day(r.z_path_on)
        # The round trip is a claim about the IDIOSYNCRATIC path, so the "net"
        # figure has to be the excess. Quoting the raw price change here reads
        # as a contradiction whenever the sector moved underneath it.
        s = (
            f"Moved {r.z_path:.1f} sigma on {day} and gave it back, "
            f"ending {_pct(r.excess)} against its sector {_when(r)}"
        )
        return _tail(r, s)

    # The headline is the price the user sees; the sigma clause is the part
    # that is net of the sector. Leading with one and sizing it by the other
    # produces sentences like "Up 4.7%" on a stock that fell 4.7%.
    verb = "Down" if r.cum_return < 0 else "Up"
    s = f"{verb} {_abs_pct(r.cum_return)} {_when(r)}{_bench_clause(r)}"

    if r.gated:
        return s + f", too small to call ({_abs_pct(r.excess, 2)} net of its sector)."
    if r.tier == "quiet":
        return s + ", inside its normal range."

    side = "weaker" if r.excess < 0 else "stronger"
    if r.beta_used == 0.0:
        s += f" -- {abs(r.z_move):.1f} sigma for itself"
    else:
        s += f" -- {abs(r.z_move):.1f} sigma {side} than its sector explains"
    return _tail(r, s)


def _tail(r: ScoreResult, s: str) -> str:
    bits: list[str] = []
    if r.vol_ratio >= 1.8:
        bits.append(f"{r.vol_ratio:.1f}x normal volume")
    if r.breach.direction == "high":
        bits.append("a new 52-week high")
    elif r.breach.direction == "low":
        bits.append("a new 52-week low")
    if r.earnings_days:
        # Unscored context: it widened the expected range, it did not add score.
        bits.append("earnings in the window")
    if bits:
        s += ", on " + _join(bits)
    return s + "."


def _join(bits: list[str]) -> str:
    if len(bits) == 1:
        return bits[0]
    return ", ".join(bits[:-1]) + " and " + bits[-1]


def _friendly_day(iso: str | None) -> str:
    if not iso:
        return "one day"
    try:
        return dt.date.fromisoformat(iso).strftime("%A")
    except ValueError:
        return iso


def quiet_summary(top: list[ScoreResult]) -> str:
    """Absence of signal is reported as a finding, not a blank screen."""
    if not top:
        return "Nothing unusual, and nothing to compare against yet."
    r = top[0]
    return (
        f"Nothing unusual. The biggest mover was {r.ticker}, "
        f"{_pct(r.cum_return)}, within its normal range."
    )


def market_banner(z: float, ret: float) -> str:
    d = "down" if ret < 0 else "up"
    return (
        f"The whole market is {d} {_abs_pct(ret)} today ({abs(z):.1f} sigma). "
        "Moves below are measured net of that."
    )
