"""The composite score, the tiers, and the gates.

Pure: no database, no clock of its own. `scripts/calibrate.py` drives exactly
this code path over stored history, which is what makes the calibration page a
measurement of the production scorer rather than a model of it.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Sequence

from api.config import (
    MATERIAL_MOVE,
    SIGMA_FLOOR,
    TIER_CRITICAL,
    TIER_MINOR,
    TIER_NOTABLE,
    W_BREACH,
    W_MOVE,
    W_PATH,
    W_VOL,
    Z_CLAMP,
)
from api.scoring import signals
from api.scoring.window import Window

TIERS = ("critical", "notable", "minor", "quiet")


@dataclass
class Baseline:
    """The scorer's view of a baseline row. Deliberately not the ORM model."""

    ticker: str
    instrument_class: str = "stock"
    benchmark_ticker: str | None = None
    beta_used: float = 1.0
    beta_raw: float = 1.0
    r2: float = 0.0
    sigma_idio: float = 0.016
    adv20: float | None = None
    wk52_high: float | None = None
    wk52_low: float | None = None
    recent_daily: list[dict[str, Any]] = field(default_factory=list)
    sample_days: int = 0
    last_bar_date: dt.date | None = None
    frozen_reason: str | None = None


@dataclass
class PricePoint:
    price: float
    source: str = "ws"          # ws | rest | eod | mock
    bar_date: dt.date | None = None
    at: dt.datetime | None = None
    stale: bool = False


@dataclass
class ScoreResult:
    ticker: str
    attention: float
    tier: str
    direction: str
    z_move: float
    z_path: float
    z_path_on: str | None
    vol_score: float
    vol_ratio: float
    breach: signals.Breach
    excess: float
    cum_return: float
    bench_return: float
    sigma_expected: float
    n_days: int
    n_eff: float
    beta_used: float
    window_path: list[dict[str, Any]]
    earnings_days: list[dt.date]
    confidence: str
    confidence_reasons: list[str]
    gated: bool
    window: Window

    @property
    def contributions(self) -> dict[str, float]:
        """What the decomposition panel renders. Sums to `attention`."""
        return {
            "move": W_MOVE * min(abs(self.z_move), Z_CLAMP),
            "path": W_PATH * min(self.z_path, Z_CLAMP),
            "volume": W_VOL * self.vol_score,
            "breach": W_BREACH * self.breach.score,
        }


def tier_of(attention: float) -> str:
    if attention >= TIER_CRITICAL:
        return "critical"
    if attention >= TIER_NOTABLE:
        return "notable"
    if attention >= TIER_MINOR:
        return "minor"
    return "quiet"


def score(
    base: Baseline,
    latest: PricePoint,
    bench_latest: PricePoint | None,
    win: Window,
    earnings_days: Sequence[dt.date],
    now: dt.datetime,
    cal,
    bench_close_on=None,
) -> ScoreResult:
    """Score one ticker over one window.

    `bench_close_on(ticker, date) -> float | None` is required only when the
    stock's own price is an end-of-day close: the benchmark endpoint must match
    the stock endpoint. Otherwise you compute a stock return ending yesterday
    and subtract a benchmark return ending now, which attributes the entire
    current-day market move to the stock as idiosyncratic.
    """
    reasons: list[str] = []
    confidence = "ok"

    sigma = max(base.sigma_idio or SIGMA_FLOOR, SIGMA_FLOOR)
    beta = base.beta_used if base.beta_used is not None else 1.0

    ref = win.ref_price
    ref_bench = win.ref_bench
    cum = (latest.price / ref - 1.0) if ref else 0.0

    bench_px: float | None = None
    if base.instrument_class == "broad_etf":
        beta = 0.0
    elif latest.source == "eod" and latest.bar_date is not None and bench_close_on:
        bench_px = bench_close_on(win.bench_ticker, latest.bar_date)
    elif bench_latest is not None:
        bench_px = bench_latest.price

    if base.instrument_class == "broad_etf":
        bmove = 0.0
    elif bench_px and ref_bench:
        bmove = bench_px / ref_bench - 1.0
    else:
        # A silent beta substitution is the likeliest source of a confident
        # false critical: a beta 2.1 semiconductor name scored at 1.0 during a
        # -3% sector day shows a fabricated -3% of idiosyncratic weakness.
        bmove = 0.0
        beta = 0.0
        confidence = "reduced"
        reasons.append("benchmark price unavailable; sector move not removed")

    excess = cum - beta * bmove

    ref_day_exclusive = win.ref_date if win.anchor == "close" else (
        win.ref_at.date() - dt.timedelta(days=1)
    )
    earn = signals.earnings_in_window(list(earnings_days), ref_day_exclusive, now.date())
    sigma_exp = signals.expected_sigma(sigma, win.n_eff, float(len(earn)))
    zm = signals.z_move(excess, sigma_exp)

    wd = signals.window_days(base.recent_daily, win.ref_at, now, cal)
    zp, zp_on = signals.z_path(wd, sigma)
    vs, vratio = signals.vol_score(wd)
    br = signals.breach_score(
        wd,
        base.wk52_high,
        base.wk52_low,
        sigma,
    )

    attention = (
        W_MOVE * min(abs(zm), Z_CLAMP)
        + W_PATH * min(zp, Z_CLAMP)
        + W_VOL * vs
        + W_BREACH * br.score
    )
    tier = tier_of(attention)

    # A floor on economic significance beneath the floor on statistical
    # significance. Without it, a 0.4% move twelve minutes into a session
    # divides by a tiny sqrt(n_eff) and produces a spurious 4 sigma.
    #
    # The floor is applied to the largest move ANYWHERE in the window, not just
    # to the endpoint difference. Gating on the endpoint alone would silence the
    # exact case z_path exists to catch: a stock that spiked 12% and
    # round-tripped has |excess| of nearly zero, and demoting it would throw
    # away the most valuable card the product produces.
    peak_daily = max((abs(float(d.get("exc", 0.0))) for d in wd), default=0.0)
    evidence = max(abs(excess), peak_daily)
    gated = False
    if evidence < MATERIAL_MOVE and tier in ("critical", "notable"):
        tier = "minor"
        gated = True

    for note in win.notes:
        if note not in reasons:
            reasons.append(note)
            confidence = "reduced"
    if win.capped:
        reasons.append("window capped at 30 trading days")
    if latest.stale:
        confidence = "reduced"
        reasons.append("price is stale")
    if base.frozen_reason:
        confidence = "reduced"
        reasons.append(base.frozen_reason)
    if base.sample_days < 200:
        confidence = "reduced"
        reasons.append("baseline still thin")

    return ScoreResult(
        ticker=base.ticker,
        attention=attention,
        tier=tier,
        direction="down" if excess < 0 else "up",
        z_move=zm,
        z_path=zp,
        z_path_on=zp_on,
        vol_score=vs,
        vol_ratio=vratio,
        breach=br,
        excess=excess,
        cum_return=cum,
        bench_return=bmove,
        sigma_expected=sigma_exp,
        n_days=win.n_days,
        n_eff=win.n_eff,
        window_path=signals.window_path(wd, excess, win.n_eff),
        beta_used=beta,
        earnings_days=earn,
        confidence=confidence,
        confidence_reasons=reasons,
        gated=gated,
        window=win,
    )
