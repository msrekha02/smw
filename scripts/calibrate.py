"""Measure the alert rate the production scorer actually produces.

Twelve months of stored bars for a 40-ticker basket, replayed through
`api.scoring.score.score` -- the same function the digest endpoint calls. A
calibration number produced by a parallel implementation would measure the wrong
thing, so this file contains no scoring logic of its own.

Two numbers sit side by side on `/calibration`:

  predicted  the rate under a NORMAL null. For every real check, z_move and
             z_path are replaced by standard-normal draws while the volume and
             breach terms are held at their observed values. That isolates
             exactly one assumption -- Gaussian residuals -- instead of
             comparing against a hand-derived figure that shares none of the
             scorer's gates.

  observed   the rate on real (synthetic-but-fat-tailed) returns.

The gap between them IS the fat-tail correction. Reporting it beats assuming it.

Run: python -m scripts.calibrate [--out fixtures/calibration.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from api.calendar_ny import get_calendar  # noqa: E402
from api.config import (  # noqa: E402
    MATERIAL_MOVE,
    TIER_CRITICAL,
    TIER_MINOR,
    TIER_NOTABLE,
    W_BREACH,
    W_MOVE,
    W_PATH,
    W_VOL,
    Z_CLAMP,
)
from api.scoring.score import Baseline, PricePoint, score, tier_of  # noqa: E402
from api.scoring.window import Snapshot, resolve_window  # noqa: E402
from scripts import offline  # noqa: E402
from worker.baseline.ewma import BaselineState, ewma_step, seed_from_sample  # noqa: E402
from worker.baseline.seed import RECENT_DAYS, WK52_DAYS, ADV_DAYS  # noqa: E402

BASKET = [
    "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "CRM", "ADBE", "INTC", "ORCL", "QCOM",
    "JPM", "BAC", "GS", "WFC", "MS", "XOM", "CVX", "COP", "SLB",
    "JNJ", "UNH", "PFE", "LLY", "ABBV", "CAT", "BA", "HON", "GE",
    "AMZN", "TSLA", "HD", "NKE", "PG", "KO", "PEP", "WMT",
    "GOOGL", "META", "NFLX", "DIS",
]
WATCHLIST_SIZE = 20        # the size the predicted rates in ARCHITECTURE assume
CHECK_SESSIONS = 252       # twelve months
SEED_SAMPLE = 250


@dataclass
class DaySnap:
    """The baseline as it stood at the END of one session -- which is what the
    next morning's scoring actually reads."""

    d: dt.date
    sigma_idio: float
    beta_used: float
    beta_raw: float
    r2: float
    row: dict = field(default_factory=dict)   # the recent_daily entry for this day
    adv20: float = 0.0
    wk52_high: float = 0.0
    wk52_low: float = 0.0


def walk(ticker: str, scenario: str = "") -> list[DaySnap]:
    """One forward EWMA pass, snapshotting after every session.

    Uses the production `seed_from_sample` and `ewma_step`; nothing here
    reimplements the estimator.
    """
    ic, bm = offline.benchmark_for(ticker)
    sb = list(offline.bars(ticker, scenario))
    if not sb:
        return []
    if bm:
        by = {b.bar_date: b for b in offline.bars(bm, scenario)}
        sb = [b for b in sb if b.bar_date in by]
        bb = [by[b.bar_date] for b in sb]
    else:
        bb = []
    if len(sb) < SEED_SAMPLE + 60:
        return []

    r_s = [sb[i].close / sb[i - 1].close - 1.0 for i in range(1, len(sb))]
    r_b = (
        [bb[i].close / bb[i - 1].close - 1.0 for i in range(1, len(bb))]
        if bb
        else [0.0] * len(r_s)
    )

    st = BaselineState(ticker=ticker, instrument_class=ic)
    seed_from_sample(st, r_s[:SEED_SAMPLE], r_b[:SEED_SAMPLE])

    out: list[DaySnap] = []
    for i in range(SEED_SAMPLE, len(r_s)):
        bar = sb[i + 1]
        exc = ewma_step(st, r_s[i], r_b[i])

        j = i + 1
        vols = [b.volume for b in sb[max(0, j - ADV_DAYS + 1) : j + 1] if b.volume]
        adv = sum(vols) / len(vols) if vols else 0.0
        prior = sb[max(0, j - WK52_DAYS) : j]
        yr = sb[max(0, j - WK52_DAYS + 1) : j + 1]
        out.append(
            DaySnap(
                d=bar.bar_date,
                sigma_idio=st.sigma_idio,
                beta_used=st.beta_used,
                beta_raw=st.beta_raw,
                r2=st.r2,
                row={
                    "d": bar.bar_date.isoformat(),
                    "exc": exc,
                    "volr": (bar.volume / adv) if (adv and bar.volume) else 1.0,
                    "close": bar.close,
                    "high": bar.high,
                    "low": bar.low,
                    "hh": max((x.high for x in prior), default=None),
                    "ll": min((x.low for x in prior), default=None),
                },
                adv20=adv,
                wk52_high=max(b.high for b in yr),
                wk52_low=min(b.low for b in yr),
            )
        )
    return out


def run(window_days: int = 1, scenario: str = "") -> dict:
    cal = get_calendar()
    walks = {t: walk(t, scenario) for t in BASKET}
    walks = {t: w for t, w in walks.items() if w}
    if not walks:
        raise SystemExit("no usable history; run scripts/record_fixtures.py first")

    rng = np.random.default_rng(7)
    observed: Counter[str] = Counter()
    predicted: Counter[str] = Counter()
    attentions: list[float] = []
    residuals: list[float] = []
    checks = 0

    for ticker, w in walks.items():
        ic, bm = offline.benchmark_for(ticker)
        by_date = {s.d: s for s in w}
        dates = [s.d for s in w]
        start = max(len(dates) - CHECK_SESSIONS, window_days + 1)

        for k in range(start, len(dates)):
            today = dates[k]
            ref_day = dates[k - window_days]
            prev = w[k - 1]           # last night's baseline: what scoring reads

            recent = [w[i].row for i in range(max(0, k - RECENT_DAYS + 1), k + 1)]

            base = Baseline(
                ticker=ticker,
                instrument_class=ic,
                benchmark_ticker=bm,
                beta_used=prev.beta_used,
                beta_raw=prev.beta_raw,
                r2=prev.r2,
                sigma_idio=prev.sigma_idio,
                adv20=prev.adv20,
                wk52_high=prev.wk52_high,
                wk52_low=prev.wk52_low,
                recent_daily=recent,
                sample_days=SEED_SAMPLE + k,
                last_bar_date=today,
            )

            ref_close = by_date[ref_day].row["close"]
            bref = offline.bars(bm, scenario) if bm else ()
            bench_by = {b.bar_date: b.close for b in bref}
            snap = Snapshot(
                ticker=ticker,
                last_seen_price=ref_close,
                last_seen_bench=bench_by.get(ref_day, 0.0),
                last_seen_bench_ticker=bm or "SPY",
                last_seen_at=cal.bounds(ref_day).close_utc,
            )
            now = cal.bounds(today).close_utc

            def close_on(t: str, d: dt.date, _bm=bm, _tk=ticker) -> float | None:
                if t == _tk:
                    s = by_date.get(d)
                    return s.row["close"] if s else None
                return bench_by.get(d)

            win = resolve_window(snap, now, cal, bm, close_on)
            latest = PricePoint(
                price=by_date[today].row["close"], source="eod", bar_date=today, at=now
            )
            bench_pp = (
                PricePoint(price=bench_by[today], source="eod", bar_date=today, at=now)
                if bm and today in bench_by
                else None
            )
            res = score(
                base, latest, bench_pp, win,
                offline.earnings().get(ticker, []), now, cal,
                bench_close_on=close_on,
            )

            checks += 1
            observed[res.tier] += 1
            attentions.append(res.attention)
            residuals.append(res.z_move)

            # --- the normal null -------------------------------------
            # Same volume and breach terms, same material-move gate, same
            # tiering. Only the return distribution is replaced.
            zm = float(rng.standard_normal())
            zp = abs(float(rng.standard_normal())) if window_days == 1 else max(
                abs(float(x)) for x in rng.standard_normal(window_days)
            )
            att = (
                W_MOVE * min(abs(zm), Z_CLAMP)
                + W_PATH * min(zp, Z_CLAMP)
                + W_VOL * res.vol_score
                + W_BREACH * res.breach.score
            )
            tier = tier_of(att)
            null_excess = zm * res.sigma_expected
            if abs(null_excess) < MATERIAL_MOVE and tier in ("critical", "notable"):
                tier = "minor"
            predicted[tier] += 1

    def per_watchlist(counter: Counter, tier: str, per: str) -> float:
        """Convert a per-check rate into the units the design brief uses."""
        rate = counter[tier] / checks if checks else 0.0
        daily = rate * WATCHLIST_SIZE
        return round(daily * (5.0 if per == "week" else 1.0), 3)

    edges = [round(x, 2) for x in np.arange(0, 8.5, 0.25)]
    counts, _ = np.histogram(attentions, bins=edges + [99.0])

    arr = np.array(residuals)
    resid = {
        "n": int(arr.size),
        "sd": round(float(arr.std(ddof=1)), 4),
        "kurtosis": round(float(((arr - arr.mean()) ** 4).mean() / arr.var() ** 2), 3),
        "tail_2s": round(float((np.abs(arr) >= 2).mean()), 5),
        "tail_3s": round(float((np.abs(arr) >= 3).mean()), 5),
        "normal_tail_2s": 0.0455,
        "normal_tail_3s": 0.0027,
    }

    # The same residuals as a distribution rather than four summary numbers, so
    # the calibration page can show WHERE the extra alerts come from instead of
    # only asserting that they exist. 40 bins over [-8, 8] matches the per-ticker
    # histogram stored on each baseline, so the two read on the same scale.
    hist_edges = np.linspace(-8.0, 8.0, 41)
    hist_counts, _ = np.histogram(arr, bins=hist_edges)
    resid_hist = {
        "bins": 40,
        "lo": -8.0,
        "hi": 8.0,
        "counts": [int(x) for x in hist_counts],
        "under": int((arr < -8.0).sum()),
        "over": int((arr > 8.0).sum()),
        "n": int(arr.size),
    }

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "universe": len(walks),
        "sessions": CHECK_SESSIONS,
        "checks": checks,
        "window_days": window_days,
        "watchlist_size": WATCHLIST_SIZE,
        "thresholds": {
            "critical": TIER_CRITICAL, "notable": TIER_NOTABLE, "minor": TIER_MINOR,
        },
        "predicted": {
            "critical_per_week": per_watchlist(predicted, "critical", "week"),
            "notable_per_day": per_watchlist(predicted, "notable", "day"),
            "critical_rate": round(predicted["critical"] / checks, 5) if checks else 0,
            "notable_rate": round(predicted["notable"] / checks, 5) if checks else 0,
        },
        "observed": {
            "critical_per_week": per_watchlist(observed, "critical", "week"),
            "notable_per_day": per_watchlist(observed, "notable", "day"),
            "critical_rate": round(observed["critical"] / checks, 5) if checks else 0,
            "notable_rate": round(observed["notable"] / checks, 5) if checks else 0,
        },
        "per_check_rates": {
            k: round(observed[k] / checks, 5) if checks else 0.0
            for k in ("critical", "notable", "minor", "quiet")
        },
        "attention_histogram": {"edges": edges, "counts": [int(c) for c in counts]},
        "residual_summary": resid,
        "residual_histogram": resid_hist,
        "notes": [
            "Predicted holds the volume and breach terms at their observed "
            "values and replaces only the return distribution with a standard "
            "normal, so the gap isolates fat tails rather than the weights.",
            f"Rates are per {WATCHLIST_SIZE}-ticker watchlist checked once per "
            f"{'day' if window_days == 1 else str(window_days) + ' sessions'}.",
            "Real returns are fat-tailed, so the observed rate runs higher. "
            "That is reported, not corrected for.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-days", type=int, default=1)
    ap.add_argument("--scenario", default="")
    ap.add_argument(
        "--out",
        default=str(pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "calibration.json"),
    )
    args = ap.parse_args()

    result = run(args.window_days, args.scenario)
    pathlib.Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")

    o, p = result["observed"], result["predicted"]
    print(f"universe {result['universe']}  checks {result['checks']}")
    print(f"{'':22s} {'predicted':>12s} {'observed':>12s}")
    print(f"{'critical / week':22s} {p['critical_per_week']:>12.2f} {o['critical_per_week']:>12.2f}")
    print(f"{'notable / day':22s} {p['notable_per_day']:>12.2f} {o['notable_per_day']:>12.2f}")
    r = result["residual_summary"]
    print(f"residual sd {r['sd']}  kurtosis {r['kurtosis']}  "
          f"P(|z|>3) {r['tail_3s']} vs {r['normal_tail_3s']} under normal")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
