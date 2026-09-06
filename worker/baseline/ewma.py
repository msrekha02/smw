"""The EWMA recursion.

Two decay constants, because the two things being estimated move at different
speeds. Beta is structural, so lambda_beta = 0.98 (34-day half-life); a
fast-decaying beta is mostly noise. Volatility regimes genuinely shift fast, so
lambda_vol = 0.94 (11-day, RiskMetrics).

Deviations are taken against the PRIOR mean. Updating the mean first and then
measuring deviation from the updated mean shrinks every deviation by lambda and
biases variance low by lambda-squared -- about 12% at lambda = 0.94, which
inflates every z-score by roughly 6%. That error pushes toward over-alerting,
which is the exact direction this product cannot afford.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from api.config import (
    BETA_CLIP,
    BETA_SHRINK_K,
    LAMBDA_BETA,
    LAMBDA_VOL,
    MAD_WINDOW,
    SIGMA_FLOOR,
    SIGMA_PRIOR,
    SIGMA_SHRINK_K,
    WINSOR_MAD_MULT,
)


def clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def median(xs) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    m = n // 2
    return s[m] if n % 2 else 0.5 * (s[m - 1] + s[m])


@dataclass
class BaselineState:
    """Everything the recursion carries between days."""

    ticker: str = ""
    instrument_class: str = "stock"

    sample_days: int = 0
    mean_ret: float = 0.0
    var_stock: float = 0.0
    mean_bench: float = 0.0
    var_bench: float = 0.0
    cov: float = 0.0
    beta_raw: float = 1.0
    beta_used: float = 1.0
    r2: float = 0.0
    mean_excess: float = 0.0
    var_excess: float = SIGMA_PRIOR**2
    sigma_idio: float = SIGMA_PRIOR
    sigma_mad: float = SIGMA_PRIOR

    _mad_window: deque = field(default_factory=lambda: deque(maxlen=MAD_WINDOW), repr=False)

    @property
    def is_broad(self) -> bool:
        return self.instrument_class == "broad_etf"


def ewma_step(s: BaselineState, r_stock: float, r_bench: float) -> float:
    """Advance one trading day. Returns the UNWINSORISED excess return.

    The caller feeds that value to the residual histogram: winsorisation must
    protect the variance estimate without hiding genuine tails from the honest
    picture shown on the detail page.
    """
    a_v = 1.0 - LAMBDA_VOL
    a_b = 1.0 - LAMBDA_BETA

    if s.is_broad:
        # A broad ETF benchmarked against itself gives excess identically zero,
        # so it could never alert -- silently, with no error and no null. Pin
        # beta at 0 and score the raw return.
        excess = r_stock
        s.beta_raw = 0.0
        s.beta_used = 0.0
        s.r2 = 0.0
        dx = r_stock - s.mean_ret
        s.mean_ret += a_b * dx
        s.var_stock = LAMBDA_BETA * (s.var_stock + a_b * dx * dx)
    else:
        dx = r_stock - s.mean_ret  # PRIOR means, both of them
        dy = r_bench - s.mean_bench
        s.mean_ret += a_b * dx
        s.mean_bench += a_b * dy
        s.var_stock = LAMBDA_BETA * (s.var_stock + a_b * dx * dx)
        s.var_bench = LAMBDA_BETA * (s.var_bench + a_b * dy * dy)
        s.cov = LAMBDA_BETA * (s.cov + a_b * dx * dy)
        s.beta_raw = s.cov / max(s.var_bench, 1e-12)
        s.r2 = (s.cov**2) / max(s.var_stock * s.var_bench, 1e-18)
        excess = r_stock - s.beta_used * r_bench

    # One -20% day otherwise inflates EWMA variance for weeks, suppressing
    # alerts during exactly the period the stock is most interesting.
    bound = WINSOR_MAD_MULT * max(s.sigma_mad, SIGMA_FLOOR)
    excess_w = clip(excess, -bound, bound)

    de = excess_w - s.mean_excess  # prior mean again
    s.mean_excess += a_v * de
    s.var_excess = LAMBDA_VOL * (s.var_excess + a_v * de * de)

    s.sample_days += 1
    s._mad_window.append(excess)
    derive(s)
    return excess


def derive(s: BaselineState) -> None:
    """Recompute the shrunk, floored quantities the scorer actually reads."""
    if s.is_broad:
        s.beta_raw = 0.0
        s.beta_used = 0.0
    else:
        # Shrink toward 1.0, weighted by fit quality AND sample size. A young or
        # poorly-explained regression should not hand the scorer a beta of 2.4.
        w = s.r2 * s.sample_days / (s.sample_days + BETA_SHRINK_K)
        s.beta_used = clip(w * s.beta_raw + (1.0 - w) * 1.0, *BETA_CLIP)

    ws = s.sample_days / (s.sample_days + SIGMA_SHRINK_K)
    var = ws * max(s.var_excess, 0.0) + (1.0 - ws) * SIGMA_PRIOR**2
    # The sigma floor matters more than it looks: a utility with a genuine
    # 0.25%/day idiosyncratic sigma would score 4 sigma on a 1% move and
    # dominate every digest.
    s.sigma_idio = max(math.sqrt(max(var, 0.0)), SIGMA_FLOOR)

    if len(s._mad_window) >= 20:
        med = median(s._mad_window)
        s.sigma_mad = max(
            1.4826 * median([abs(x - med) for x in s._mad_window]), SIGMA_FLOOR
        )


def seed_from_sample(
    s: BaselineState, r_stock: list[float], r_bench: list[float]
) -> None:
    """Initialise from plain sample statistics of the first N returns.

    This removes EWMA initialisation bias without a 1/(1-lambda^n) correction,
    and it matters asymmetrically: residual bias after 250 bars is negligible at
    lambda_vol = 0.94 but would be material at lambda_beta = 0.98. Beta's slow
    decay is exactly what makes it need a real seed.
    """
    n = len(r_stock)
    if n == 0:
        return
    s.mean_ret = sum(r_stock) / n
    s.var_stock = sum((x - s.mean_ret) ** 2 for x in r_stock) / max(n - 1, 1)

    if s.is_broad:
        s.mean_bench = 0.0
        s.var_bench = 0.0
        s.cov = 0.0
        s.beta_raw = 0.0
        s.beta_used = 0.0
        s.r2 = 0.0
        excess = list(r_stock)
    else:
        s.mean_bench = sum(r_bench) / n
        s.var_bench = sum((y - s.mean_bench) ** 2 for y in r_bench) / max(n - 1, 1)
        s.cov = sum(
            (x - s.mean_ret) * (y - s.mean_bench) for x, y in zip(r_stock, r_bench)
        ) / max(n - 1, 1)
        s.beta_raw = s.cov / max(s.var_bench, 1e-12)
        s.r2 = (s.cov**2) / max(s.var_stock * s.var_bench, 1e-18)
        # The seed hands the recursion a real beta, not the shrunk one: the
        # shrinkage exists to protect against a thin sample, and 250 bars is not
        # a thin sample.
        s.beta_used = clip(s.beta_raw, *BETA_CLIP)
        excess = [x - s.beta_used * y for x, y in zip(r_stock, r_bench)]

    s.mean_excess = sum(excess) / n
    s.var_excess = sum((e - s.mean_excess) ** 2 for e in excess) / max(n - 1, 1)
    s.sample_days = n
    s._mad_window.clear()
    s._mad_window.extend(excess[-MAD_WINDOW:])
    med = median(s._mad_window)
    s.sigma_mad = max(
        1.4826 * median([abs(x - med) for x in s._mad_window]), SIGMA_FLOOR
    )
    ws = s.sample_days / (s.sample_days + SIGMA_SHRINK_K)
    s.sigma_idio = max(
        math.sqrt(ws * max(s.var_excess, 0.0) + (1.0 - ws) * SIGMA_PRIOR**2),
        SIGMA_FLOOR,
    )
