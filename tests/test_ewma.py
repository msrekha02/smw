"""The estimator, checked against independent references."""
from __future__ import annotations

import json
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from api.config import LAMBDA_BETA, SEED_SAMPLE_BARS, SIGMA_FLOOR
from worker.baseline.ewma import BaselineState, ewma_step, seed_from_sample
from worker.baseline.seed import compute_baseline

FIX = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "bars"


def closes(t: str) -> np.ndarray:
    rows = json.loads((FIX / f"{t}.json").read_text(encoding="utf-8"))["bars"]
    return np.array([r[4] for r in rows], dtype=float)


def rets(t: str) -> np.ndarray:
    c = closes(t)
    return c[1:] / c[:-1] - 1.0


def test_matches_pandas_ewm_reference():
    """`ewma_step` is the standard incremental exponentially-weighted moment
    recursion, so it must agree with pandas `ewm(adjust=False)`."""
    x = rets("NVDA")[:600]
    y = rets("XLK")[:600]

    st = BaselineState(ticker="NVDA")
    for a, b in zip(x, y):
        ewma_step(st, a, b)

    alpha = 1 - LAMBDA_BETA
    sx = pd.Series(x)
    sy = pd.Series(y)
    ref_mean = sx.ewm(alpha=alpha, adjust=False).mean().iloc[-1]
    ref_var = sx.ewm(alpha=alpha, adjust=False).var(bias=True).iloc[-1]
    ref_cov = sx.ewm(alpha=alpha, adjust=False).cov(sy, bias=True).iloc[-1]

    # pandas seeds its mean at x[0] and this seeds at 0, so the two agree to
    # the residue of that initialisation, not to machine epsilon. Beta -- the
    # quantity the scorer actually reads -- agrees far more tightly, because the
    # initialisation cancels between the covariance and the variance.
    ref_beta = ref_cov / sy.ewm(alpha=alpha, adjust=False).var(bias=True).iloc[-1]
    assert st.mean_ret == pytest.approx(ref_mean, rel=1e-3)
    assert st.var_stock == pytest.approx(ref_var, rel=1e-4)
    assert st.cov == pytest.approx(ref_cov, rel=1e-4)
    assert st.beta_raw == pytest.approx(ref_beta, rel=1e-5)


def test_deviations_are_taken_against_the_prior_mean():
    """Updating the mean first shrinks every deviation by lambda and biases
    variance low by lambda squared -- about 12% at lambda_vol = 0.94, which
    inflates every z by ~6%. That error pushes toward over-alerting."""
    x = rets("AAPL")[:400]

    st = BaselineState(ticker="AAPL")
    for a in x:
        ewma_step(st, a, 0.0)
    correct = st.var_stock

    # The wrong recursion, written out explicitly.
    lam, a_b = LAMBDA_BETA, 1 - LAMBDA_BETA
    mean = var = 0.0
    for r in x:
        mean += a_b * (r - mean)
        d = r - mean          # posterior mean: the bug
        var = lam * (var + a_b * d * d)

    assert var < correct
    assert var / correct == pytest.approx(LAMBDA_BETA**2, rel=0.05)


def test_seed_beta_matches_ols_over_the_same_window():
    """The seed is plain sample statistics of the first 250 returns, so it must
    reproduce an OLS slope over exactly those returns."""
    x = rets("NVDA")[:SEED_SAMPLE_BARS]
    y = rets("XLK")[:SEED_SAMPLE_BARS]

    st = BaselineState(ticker="NVDA")
    seed_from_sample(st, list(x), list(y))

    ols = float(np.polyfit(y, x, 1)[0])
    assert abs(st.beta_raw - ols) < 0.05
    assert st.beta_used == pytest.approx(st.beta_raw, abs=1e-9)
    assert st.sample_days == SEED_SAMPLE_BARS


def test_broad_etf_pins_beta_to_zero():
    """Without this an ETF benchmarks against itself, excess is identically
    zero, and it can never alert -- silently, with no error and no null."""
    st = BaselineState(ticker="SPY", instrument_class="broad_etf")
    seed_from_sample(st, list(rets("SPY")[:250]), [0.0] * 250)
    for r in rets("SPY")[250:400]:
        excess = ewma_step(st, r, 0.0)
        assert excess == pytest.approx(r)
    assert st.beta_used == 0.0


def _shocked_sigma(sessions_before_end: int, winsor_mult: float) -> tuple[float, float]:
    """Drop one -20% day into AAPL's history and report sigma before and after.

    The whole series after the shock is scaled too, so exactly one daily RETURN
    is anomalous -- which is what a real crash looks like, and what the
    estimator has to survive.
    """
    import datetime as dt

    import worker.baseline.ewma as ewma_mod
    from providers.base import Bar

    def to_bars(name):
        rows = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["bars"]
        return [
            Bar(dt.date.fromisoformat(r[0]), r[1], r[2], r[3], r[4], r[5]) for r in rows
        ]

    bench = to_bars("XLK")[-1260:]
    clean = to_bars("AAPL")[-1260:]
    base = compute_baseline("AAPL", "stock", "XLK", clean, bench)

    shocked = list(clean)
    i = len(shocked) - sessions_before_end
    f = 0.80
    b = shocked[i]
    shocked[i] = Bar(b.bar_date, b.open, b.high, b.low * f, b.close * f, b.volume)
    for j in range(i + 1, len(shocked)):
        c = shocked[j]
        shocked[j] = Bar(
            c.bar_date, c.open * f, c.high * f, c.low * f, c.close * f, c.volume
        )

    saved = ewma_mod.WINSOR_MAD_MULT
    ewma_mod.WINSOR_MAD_MULT = winsor_mult
    try:
        hit = compute_baseline("AAPL", "stock", "XLK", shocked, bench)
    finally:
        ewma_mod.WINSOR_MAD_MULT = saved
    return base.sigma_idio, hit.sigma_idio


def test_winsorisation_contains_a_single_crash_day():
    """One -20% day otherwise inflates EWMA variance for weeks, suppressing
    alerts during exactly the period the stock is most interesting."""
    base, clipped = _shocked_sigma(1, 5.0)
    _, raw = _shocked_sigma(1, 1e9)

    inflation_clipped = clipped / base - 1.0
    inflation_raw = raw / base - 1.0

    assert inflation_raw > 5.0, "unclipped, the shock should be catastrophic"
    assert inflation_clipped < 0.5
    # An order of magnitude, which is the point of the clip.
    assert inflation_clipped < inflation_raw / 10.0


def test_winsorised_sigma_recovers_within_a_month():
    """BUILD.md asks for < 15%; that is reached about 21 sessions after the
    shock. Unclipped it is still +320% at the same horizon."""
    base, clipped = _shocked_sigma(30, 5.0)
    _, raw = _shocked_sigma(30, 1e9)
    assert abs(clipped / base - 1.0) < 0.15
    assert raw / base - 1.0 > 1.0


def test_sigma_floor_applies():
    st = BaselineState(ticker="DUK")
    seed_from_sample(st, [0.0001] * 250, [0.0] * 250)
    assert st.sigma_idio >= SIGMA_FLOOR
    assert not math.isnan(st.sigma_idio)
