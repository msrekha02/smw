"""A fixture-backed harness that drives the PRODUCTION scorer without a database.

`scripts/calibrate.py` and the scenario tests both run through here. The point
is that neither of them reimplements any scoring: they build the same
`Baseline`, `Window` and `PricePoint` objects the API builds, and call the same
`score()`. A calibration number produced by a parallel implementation would
measure the wrong thing.
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import pathlib
from dataclasses import dataclass

from api.calendar_ny import get_calendar
from api.scoring.score import Baseline, PricePoint, ScoreResult, score
from api.scoring.window import Snapshot, resolve_window
from providers.base import Bar
from worker.baseline.seed import classify, compute_baseline, resolve_benchmark

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"


@functools.lru_cache(maxsize=256)
def _bars_raw(ticker: str) -> tuple[tuple, ...]:
    f = FIXTURES / "bars" / f"{ticker.upper()}.json"
    if not f.exists():
        return ()
    return tuple(tuple(r) for r in json.loads(f.read_text(encoding="utf-8"))["bars"])


@functools.lru_cache(maxsize=8)
def _overlay(scenario: str) -> dict:
    f = FIXTURES / "scenarios" / f"{scenario}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"overlay": {}}


@functools.lru_cache(maxsize=512)
def bars(ticker: str, scenario: str = "") -> tuple[Bar, ...]:
    rows = {r[0]: r for r in _bars_raw(ticker)}
    if scenario:
        for r in _overlay(scenario)["overlay"].get(ticker.upper(), []):
            rows[r[0]] = r
    out = []
    for d in sorted(rows):
        _, o, h, low, c, v = rows[d]
        out.append(
            Bar(dt.date.fromisoformat(d), float(o), float(h), float(low), float(c), int(v))
        )
    return tuple(out)


@functools.lru_cache(maxsize=1)
def profiles() -> dict:
    return json.loads((FIXTURES / "profiles.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def earnings() -> dict[str, list[dt.date]]:
    raw = json.loads((FIXTURES / "earnings.json").read_text(encoding="utf-8"))
    return {k: [dt.date.fromisoformat(x) for x in v] for k, v in raw.items()}


def universe() -> list[str]:
    return sorted(p.stem for p in (FIXTURES / "bars").glob("*.json"))


def benchmark_for(ticker: str) -> tuple[str, str | None]:
    ic = classify(ticker)
    sector = (profiles().get(ticker.upper()) or {}).get("sector")
    return ic, resolve_benchmark(ticker, ic, sector)


@dataclass
class Book:
    """Baselines as of a given date, plus the bar series they were built from."""

    as_of: dt.date
    scenario: str
    baselines: dict[str, Baseline]
    series: dict[str, dict[dt.date, Bar]]

    def close_on(self, ticker: str, d: dt.date) -> float | None:
        s = self.series.get(ticker.upper())
        if not s:
            return None
        b = s.get(d)
        return b.close if b else None


def build_book(
    tickers: list[str], as_of: dt.date, scenario: str = "", n_bars: int = 1260
) -> Book:
    """Compute every baseline from bars up to and including `as_of`."""
    needed = set(t.upper() for t in tickers)
    for t in list(needed):
        _, bm = benchmark_for(t)
        if bm:
            needed.add(bm)

    series: dict[str, dict[dt.date, Bar]] = {}
    for t in needed:
        rows = [b for b in bars(t, scenario) if b.bar_date <= as_of]
        series[t] = {b.bar_date: b for b in rows}

    baselines: dict[str, Baseline] = {}
    for t in sorted(needed):
        ic, bm = benchmark_for(t)
        sb = [b for b in bars(t, scenario) if b.bar_date <= as_of][-n_bars:]
        bb = [b for b in bars(bm, scenario) if b.bar_date <= as_of][-n_bars:] if bm else None
        if len(sb) < 60:
            continue
        res = compute_baseline(t, ic, bm, sb, bb)
        baselines[t] = Baseline(
            ticker=t,
            instrument_class=ic,
            benchmark_ticker=bm,
            beta_used=res.beta_used,
            beta_raw=res.beta_raw,
            r2=res.r2,
            sigma_idio=res.sigma_idio,
            adv20=res.adv20,
            wk52_high=res.wk52_high,
            wk52_low=res.wk52_low,
            recent_daily=res.recent_daily,
            sample_days=res.sample_days,
            last_bar_date=res.last_bar_date,
        )
    return Book(as_of, scenario, baselines, series)


def score_at(
    book: Book, ticker: str, last_seen_at: dt.datetime, now: dt.datetime
) -> ScoreResult | None:
    """Score one ticker as an end-of-day snapshot, exactly as the API would."""
    cal = get_calendar()
    t = ticker.upper()
    base = book.baselines.get(t)
    if base is None:
        return None
    px = book.close_on(t, book.as_of)
    if px is None:
        return None

    ref_day = cal.session_on_or_before(last_seen_at.astimezone(cal_tz()).date())
    snap = Snapshot(
        ticker=t,
        last_seen_price=book.close_on(t, ref_day) or px,
        last_seen_bench=(
            book.close_on(base.benchmark_ticker, ref_day) if base.benchmark_ticker else 0.0
        )
        or 0.0,
        last_seen_bench_ticker=base.benchmark_ticker or "SPY",
        last_seen_at=last_seen_at,
    )
    win = resolve_window(snap, now, cal, base.benchmark_ticker, book.close_on)
    latest = PricePoint(price=px, source="eod", bar_date=book.as_of, at=now)
    bench = None
    if base.benchmark_ticker:
        bpx = book.close_on(base.benchmark_ticker, book.as_of)
        if bpx:
            bench = PricePoint(price=bpx, source="eod", bar_date=book.as_of, at=now)
    return score(
        base,
        latest,
        bench,
        win,
        earnings().get(t, []),
        now,
        cal,
        bench_close_on=book.close_on,
    )


def cal_tz():
    from api.calendar_ny import ET

    return ET
