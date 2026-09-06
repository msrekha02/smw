"""Baseline seeding and recomputation.

`compute_baseline` is a pure function of stored bars. That is the whole reason
the nightly job splits fetch from compute: fetch is quota-bound and
non-idempotent, compute costs nothing and always produces the same answer, so
only the fetch phase needs recovery machinery.

Five years of bars rather than one, because bar count is free on Twelve Data's
`/time_series`. The extra history does little for the EWMA -- it decays
regardless -- but it makes the residual distribution meaningful and gives the
calibration script real data.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

from api.config import (
    BROAD_ETFS,
    DEFAULT_BENCHMARK,
    SECTOR_BENCHMARKS,
    SECTOR_ETFS,
    SEED_SAMPLE_BARS,
)
from providers.base import Bar
from worker.baseline.ewma import BaselineState, ewma_step, seed_from_sample

RESIDUAL_BINS = 40
RESIDUAL_LO, RESIDUAL_HI = -8.0, 8.0
RECENT_DAYS = 30
ADV_DAYS = 20
WK52_DAYS = 252


def classify(ticker: str) -> str:
    t = ticker.upper()
    if t in BROAD_ETFS:
        return "broad_etf"
    if t in SECTOR_ETFS:
        return "sector_etf"
    return "stock"


def resolve_benchmark(ticker: str, instrument_class: str, sector: str | None) -> str | None:
    """Without this an ETF benchmarks against itself, excess is identically
    zero, and it can never alert -- silently. The same bug made the regime
    banner dead code, since SPY against SPY can never reach 1.5 sigma."""
    if instrument_class == "broad_etf":
        return None
    if instrument_class == "sector_etf":
        return DEFAULT_BENCHMARK
    return SECTOR_BENCHMARKS.get(sector or "", DEFAULT_BENCHMARK)


@dataclass
class BaselineResult:
    ticker: str
    instrument_class: str
    benchmark_ticker: str | None
    sample_days: int
    mean_ret: float
    var_stock: float
    mean_bench: float
    var_bench: float
    cov: float
    beta_raw: float
    beta_used: float
    r2: float
    mean_excess: float
    var_excess: float
    sigma_idio: float
    sigma_mad: float
    adv20: float | None
    wk52_high: float | None
    wk52_low: float | None
    recent_daily: list[dict[str, Any]] = field(default_factory=list)
    residual_hist: dict[str, Any] | None = None
    last_bar_date: dt.date | None = None
    residuals: list[float] = field(default_factory=list, repr=False)

    def as_row(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "sample_days": self.sample_days,
            "mean_ret": self.mean_ret,
            "var_stock": self.var_stock,
            "mean_bench": self.mean_bench,
            "var_bench": self.var_bench,
            "cov": self.cov,
            "beta_raw": self.beta_raw,
            "beta_used": self.beta_used,
            "r2": self.r2,
            "mean_excess": self.mean_excess,
            "var_excess": self.var_excess,
            "sigma_idio": self.sigma_idio,
            "sigma_mad": self.sigma_mad,
            "adv20": self.adv20,
            "wk52_high": self.wk52_high,
            "wk52_low": self.wk52_low,
            "recent_daily": self.recent_daily,
            "residual_hist": self.residual_hist,
            "last_bar_date": self.last_bar_date,
        }


class NotEnoughBars(ValueError):
    pass


def _returns(bars: list[Bar]) -> list[float]:
    return [bars[i].close / bars[i - 1].close - 1.0 for i in range(1, len(bars))]


def _histogram(values: list[float]) -> dict[str, Any]:
    counts = [0] * RESIDUAL_BINS
    width = (RESIDUAL_HI - RESIDUAL_LO) / RESIDUAL_BINS
    under = over = 0
    for v in values:
        if v < RESIDUAL_LO:
            under += 1
            continue
        if v >= RESIDUAL_HI:
            over += 1
            continue
        counts[int((v - RESIDUAL_LO) / width)] += 1
    n = len(values)
    mean = sum(values) / n if n else 0.0
    var = sum((v - mean) ** 2 for v in values) / max(n - 1, 1) if n else 0.0
    sd = math.sqrt(var)
    kurt = (
        sum((v - mean) ** 4 for v in values) / n / (var**2)
        if n and var > 0
        else 0.0
    )
    return {
        "bins": RESIDUAL_BINS,
        "lo": RESIDUAL_LO,
        "hi": RESIDUAL_HI,
        "counts": counts,
        "under": under,
        "over": over,
        "n": n,
        "sd": round(sd, 4),
        "kurtosis": round(kurt, 3),
        # The share of days beyond 3 sigma. Under a normal null this is 0.0027;
        # the gap between the two numbers is the fat-tail correction the
        # calibration page reports rather than assumes.
        "tail_3s": round(sum(1 for v in values if abs(v) >= 3.0) / n, 5) if n else 0.0,
    }


def compute_baseline(
    ticker: str,
    instrument_class: str,
    benchmark_ticker: str | None,
    stock_bars: list[Bar],
    bench_bars: list[Bar] | None,
) -> BaselineResult:
    """Pure. Same bars in, same baseline out, every time."""
    stock_bars = sorted(stock_bars, key=lambda b: b.bar_date)
    is_broad = instrument_class == "broad_etf"

    if is_broad or not bench_bars:
        aligned = stock_bars
        bench_aligned: list[Bar] = []
        if not is_broad and benchmark_ticker:
            # Benchmark missing entirely: fall back to beta 1.0 against nothing
            # is meaningless, so treat the series as its own excess and let the
            # caller mark confidence: reduced.
            pass
    else:
        by_date = {b.bar_date: b for b in bench_bars}
        aligned = [b for b in stock_bars if b.bar_date in by_date]
        bench_aligned = [by_date[b.bar_date] for b in aligned]

    if len(aligned) < 30:
        raise NotEnoughBars(f"{ticker}: {len(aligned)} usable bars")

    r_stock = _returns(aligned)
    r_bench = _returns(bench_aligned) if bench_aligned else [0.0] * len(r_stock)
    dates = [b.bar_date for b in aligned[1:]]

    st = BaselineState(ticker=ticker.upper(), instrument_class=instrument_class)
    n_seed = min(SEED_SAMPLE_BARS, max(len(r_stock) // 2, 1))
    seed_from_sample(st, r_stock[:n_seed], r_bench[:n_seed])

    excess_by_date: dict[dt.date, float] = {}
    residuals: list[float] = []
    for i in range(n_seed):
        e = r_stock[i] - st.beta_used * r_bench[i]
        excess_by_date[dates[i]] = e
    for i in range(n_seed, len(r_stock)):
        # One array append inside a loop that already runs: the standardised
        # residual is what the detail page shows as the empirical distribution.
        sigma_before = st.sigma_idio
        e = ewma_step(st, r_stock[i], r_bench[i])
        excess_by_date[dates[i]] = e
        residuals.append(e / max(sigma_before, 1e-9))

    tail = aligned[-RECENT_DAYS:]
    vols = [b.volume for b in aligned[-ADV_DAYS:] if b.volume]
    adv20 = sum(vols) / len(vols) if vols else None

    yr = aligned[-WK52_DAYS:]
    wk52_high = max(b.high for b in yr)
    wk52_low = min(b.low for b in yr)

    # Each recent row carries the 52-week extremes as they stood at the END of
    # the PRIOR session. A window that opens on day D must be measured against
    # the record D inherited, not against a record D itself set -- otherwise a
    # new high is always exactly at its own high, the distance beyond it is
    # identically zero, and a continuous breach signal collapses to a binary
    # touch. Storing it per row makes this exact for any window up to 30 days.
    n_all = len(aligned)
    start = n_all - len(tail)
    recent = []
    for k, b in enumerate(tail):
        i = start + k
        prior = aligned[max(0, i - WK52_DAYS) : i]
        recent.append(
            {
                "d": b.bar_date.isoformat(),
                "exc": round(excess_by_date.get(b.bar_date, 0.0), 6),
                "volr": round((b.volume / adv20), 3) if (adv20 and b.volume) else 1.0,
                "close": round(b.close, 4),
                "high": round(b.high, 4),
                "low": round(b.low, 4),
                "hh": round(max(x.high for x in prior), 4) if prior else None,
                "ll": round(min(x.low for x in prior), 4) if prior else None,
            }
        )

    return BaselineResult(
        ticker=ticker.upper(),
        instrument_class=instrument_class,
        benchmark_ticker=benchmark_ticker,
        sample_days=st.sample_days,
        mean_ret=st.mean_ret,
        var_stock=st.var_stock,
        mean_bench=st.mean_bench,
        var_bench=st.var_bench,
        cov=st.cov,
        beta_raw=st.beta_raw,
        beta_used=st.beta_used,
        r2=st.r2,
        mean_excess=st.mean_excess,
        var_excess=st.var_excess,
        sigma_idio=st.sigma_idio,
        sigma_mad=st.sigma_mad,
        adv20=adv20,
        wk52_high=wk52_high,
        wk52_low=wk52_low,
        recent_daily=recent,
        residual_hist=_histogram(residuals),
        last_bar_date=aligned[-1].bar_date,
        residuals=residuals,
    )
