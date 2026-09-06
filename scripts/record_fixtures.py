"""Generate the replay fixtures.

Deterministic: a fixed seed and a factor model, so `docker compose up` with no
API keys produces the same product on every machine and every run. Bars are
synthetic rather than recorded because redistributing Twelve Data / Finnhub
history would breach both free tiers' terms (see ARCHITECTURE.md section 10).

The generative model is deliberately the one the scorer assumes it is fitting:

    r_sector = beta_sm * r_market + eps_sector
    r_stock  = beta     * r_sector + eps_stock

with Student-t innovations so the tails are fat and the calibration page has
something honest to report. Betas are recoverable, which is what makes the
P4 acceptance test ("seeded beta within 0.05 of a pandas OLS reference")
meaningful rather than circular.

Run: python -m scripts.record_fixtures
"""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from api.calendar_ny import get_calendar  # noqa: E402
from api.config import SECTOR_BENCHMARKS  # noqa: E402

SEED = 20240917
N_BARS = 1300
BASE_AS_OF = dt.date(2025, 8, 29)  # last base bar; scenarios append after it

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"

# ticker -> (name, sector, beta_to_sector, idio_sigma_daily, drift_annual)
STOCKS: dict[str, tuple[str, str, float, float, float]] = {
    "AAPL": ("Apple Inc", "Technology", 1.00, 0.0110, 0.18),
    "MSFT": ("Microsoft Corp", "Technology", 0.95, 0.0100, 0.20),
    "NVDA": ("NVIDIA Corp", "Technology", 1.55, 0.0210, 0.45),
    "AVGO": ("Broadcom Inc", "Technology", 1.35, 0.0170, 0.30),
    "AMD": ("Advanced Micro Devices", "Technology", 1.60, 0.0230, 0.15),
    "CRM": ("Salesforce Inc", "Technology", 1.10, 0.0150, 0.08),
    "ADBE": ("Adobe Inc", "Technology", 1.05, 0.0155, 0.02),
    "INTC": ("Intel Corp", "Technology", 1.15, 0.0200, -0.15),
    "ORCL": ("Oracle Corp", "Technology", 0.90, 0.0135, 0.22),
    "QCOM": ("Qualcomm Inc", "Technology", 1.25, 0.0165, 0.10),
    "JPM": ("JPMorgan Chase & Co", "Financial Services", 1.05, 0.0090, 0.16),
    "BAC": ("Bank of America Corp", "Financial Services", 1.15, 0.0105, 0.10),
    "GS": ("Goldman Sachs Group", "Financial Services", 1.10, 0.0110, 0.18),
    "WFC": ("Wells Fargo & Co", "Financial Services", 1.10, 0.0115, 0.12),
    "MS": ("Morgan Stanley", "Financial Services", 1.12, 0.0110, 0.14),
    "XOM": ("Exxon Mobil Corp", "Energy", 0.90, 0.0090, 0.09),
    "CVX": ("Chevron Corp", "Energy", 0.88, 0.0092, 0.06),
    "COP": ("ConocoPhillips", "Energy", 1.05, 0.0110, 0.07),
    "SLB": ("Schlumberger NV", "Energy", 1.20, 0.0140, -0.04),
    "JNJ": ("Johnson & Johnson", "Healthcare", 0.75, 0.0075, 0.05),
    "UNH": ("UnitedHealth Group", "Healthcare", 0.95, 0.0130, 0.03),
    "PFE": ("Pfizer Inc", "Healthcare", 0.85, 0.0115, -0.08),
    "LLY": ("Eli Lilly & Co", "Healthcare", 1.10, 0.0155, 0.35),
    "ABBV": ("AbbVie Inc", "Healthcare", 0.80, 0.0100, 0.14),
    "CAT": ("Caterpillar Inc", "Industrials", 1.10, 0.0115, 0.15),
    "BA": ("Boeing Co", "Industrials", 1.30, 0.0180, -0.10),
    "HON": ("Honeywell International", "Industrials", 0.85, 0.0090, 0.07),
    "GE": ("GE Aerospace", "Industrials", 1.15, 0.0130, 0.25),
    "AMZN": ("Amazon.com Inc", "Consumer Cyclical", 1.15, 0.0140, 0.20),
    "TSLA": ("Tesla Inc", "Consumer Cyclical", 1.70, 0.0290, 0.10),
    "HD": ("Home Depot Inc", "Consumer Cyclical", 0.90, 0.0100, 0.08),
    "NKE": ("NIKE Inc", "Consumer Cyclical", 1.00, 0.0135, -0.12),
    "PG": ("Procter & Gamble Co", "Consumer Defensive", 0.85, 0.0068, 0.05),
    "KO": ("Coca-Cola Co", "Consumer Defensive", 0.80, 0.0070, 0.06),
    "PEP": ("PepsiCo Inc", "Consumer Defensive", 0.82, 0.0072, 0.02),
    "WMT": ("Walmart Inc", "Consumer Defensive", 0.90, 0.0095, 0.24),
    # A genuinely low-vol name: the sigma floor is what stops it from scoring
    # 4 sigma on a 1% move. Kept in the basket on purpose.
    "NEE": ("NextEra Energy Inc", "Utilities", 0.95, 0.0072, 0.04),
    "DUK": ("Duke Energy Corp", "Utilities", 0.80, 0.0052, 0.05),
    "SO": ("Southern Co", "Utilities", 0.78, 0.0050, 0.06),
    "AMT": ("American Tower Corp", "Real Estate", 1.05, 0.0105, -0.02),
    "PLD": ("Prologis Inc", "Real Estate", 1.10, 0.0110, 0.03),
    "LIN": ("Linde plc", "Basic Materials", 0.85, 0.0082, 0.12),
    "SHW": ("Sherwin-Williams Co", "Basic Materials", 1.00, 0.0105, 0.07),
    "GOOGL": ("Alphabet Inc", "Communication Services", 1.05, 0.0125, 0.19),
    "META": ("Meta Platforms Inc", "Communication Services", 1.25, 0.0165, 0.30),
    "NFLX": ("Netflix Inc", "Communication Services", 1.20, 0.0180, 0.28),
    "DIS": ("Walt Disney Co", "Communication Services", 1.05, 0.0135, -0.05),
    "T": ("AT&T Inc", "Communication Services", 0.65, 0.0090, 0.08),
}

# sector ETF -> (name, beta_to_market, idio_sigma_daily, drift_annual)
SECTOR_ETF_PARAMS: dict[str, tuple[str, float, float, float]] = {
    "XLK": ("Technology Select Sector SPDR", 1.20, 0.0055, 0.22),
    "XLF": ("Financial Select Sector SPDR", 1.00, 0.0050, 0.14),
    "XLE": ("Energy Select Sector SPDR", 0.95, 0.0085, 0.05),
    "XLV": ("Health Care Select Sector SPDR", 0.70, 0.0050, 0.06),
    "XLI": ("Industrial Select Sector SPDR", 1.00, 0.0045, 0.12),
    "XLY": ("Consumer Discretionary Select SPDR", 1.15, 0.0055, 0.13),
    "XLP": ("Consumer Staples Select SPDR", 0.55, 0.0040, 0.05),
    "XLU": ("Utilities Select Sector SPDR", 0.55, 0.0055, 0.06),
    "XLRE": ("Real Estate Select Sector SPDR", 0.95, 0.0060, 0.02),
    "XLB": ("Materials Select Sector SPDR", 1.00, 0.0055, 0.08),
    "XLC": ("Communication Services Select SPDR", 1.05, 0.0060, 0.18),
}

BROAD_ETF_PARAMS: dict[str, tuple[str, float, float, float]] = {
    "SPY": ("SPDR S&P 500 ETF Trust", 1.00, 0.0000, 0.11),
    "QQQ": ("Invesco QQQ Trust", 1.15, 0.0035, 0.17),
    "IWM": ("iShares Russell 2000 ETF", 1.10, 0.0060, 0.06),
    "DIA": ("SPDR Dow Jones Industrial Average ETF", 0.92, 0.0030, 0.09),
    "VTI": ("Vanguard Total Stock Market ETF", 1.01, 0.0012, 0.11),
    "VOO": ("Vanguard S&P 500 ETF", 1.00, 0.0008, 0.11),
}

# Every path is rescaled so its LAST close lands here. Anchoring the end
# rather than the start keeps five years of fat-tailed compounding from
# producing a $2,400 NVDA in a demo that is otherwise trying to look credible.
END_PRICE = {
    "AAPL": 232.0, "MSFT": 415.0, "NVDA": 176.0, "AVGO": 298.0, "AMD": 158.0,
    "CRM": 245.0, "ADBE": 355.0, "INTC": 24.0, "ORCL": 218.0, "QCOM": 158.0,
    "JPM": 296.0, "BAC": 48.0, "GS": 735.0, "WFC": 79.0, "MS": 152.0,
    "XOM": 111.0, "CVX": 156.0, "COP": 94.0, "SLB": 35.0,
    "JNJ": 176.0, "UNH": 305.0, "PFE": 24.0, "LLY": 745.0, "ABBV": 213.0,
    "CAT": 415.0, "BA": 228.0, "HON": 208.0, "GE": 285.0,
    "AMZN": 228.0, "TSLA": 335.0, "HD": 390.0, "NKE": 72.0,
    "PG": 155.0, "KO": 68.0, "PEP": 145.0, "WMT": 98.0,
    "NEE": 72.0, "DUK": 122.0, "SO": 93.0, "AMT": 198.0, "PLD": 112.0,
    "LIN": 468.0, "SHW": 345.0,
    "GOOGL": 212.0, "META": 745.0, "NFLX": 1180.0, "DIS": 113.0, "T": 28.0,
    "XLK": 268.0, "XLF": 53.0, "XLE": 88.0, "XLV": 139.0, "XLI": 148.0,
    "XLY": 226.0, "XLP": 80.0, "XLU": 85.0, "XLRE": 41.0, "XLB": 88.0,
    "XLC": 112.0, "SPY": 645.0, "QQQ": 575.0, "IWM": 235.0, "DIA": 455.0,
    "VTI": 320.0, "VOO": 592.0,
}

BASE_VOLUME = {
    "AAPL": 55e6, "MSFT": 25e6, "NVDA": 400e6, "AMD": 60e6, "TSLA": 110e6,
    "AMZN": 45e6, "META": 18e6, "GOOGL": 28e6, "SPY": 75e6, "QQQ": 45e6,
}


def _t_noise(rng: np.random.Generator, n: int, df: float = 4.0) -> np.ndarray:
    """Unit-variance Student-t innovations. Fat tails, correct scale."""
    raw = rng.standard_t(df, size=n)
    return raw / math.sqrt(df / (df - 2.0))


def _vol_clusters(rng: np.random.Generator, n: int) -> np.ndarray:
    """A slow multiplicative vol regime, so EWMA vol has something to track."""
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.985 * x[i - 1] + rng.normal(0, 0.18)
    return np.exp(0.5 * x - 0.5 * np.var(x) * 0.25)


def _to_bars(
    sessions: list[dt.date],
    returns: np.ndarray,
    end_price: float,
    base_vol: float,
    rng: np.random.Generator,
) -> list[list]:
    """Turn a return path into OHLCV. Intrabar range scales with |return|.

    The path is rescaled so its final close is `end_price`. Scaling is uniform,
    so every return -- and therefore every beta, sigma and residual -- is
    untouched.
    """
    growth = np.cumprod(1.0 + returns)
    start_price = end_price / float(growth[-1])
    closes = start_price * growth
    bars: list[list] = []
    prev_close = start_price
    vol_mult = np.exp(rng.normal(0, 0.35, size=len(closes)))
    for i, (d, c) in enumerate(zip(sessions, closes)):
        r = returns[i]
        span = abs(r) * 0.55 + 0.004
        o = prev_close * (1.0 + r * rng.uniform(0.15, 0.55))
        hi = max(o, c) * (1.0 + span * rng.uniform(0.25, 1.0))
        lo = min(o, c) * (1.0 - span * rng.uniform(0.25, 1.0))
        # Volume rises with the size of the move: the volume signal needs a
        # real relationship to detect, not noise.
        v = base_vol * vol_mult[i] * (1.0 + 6.0 * abs(r))
        bars.append(
            [
                d.isoformat(),
                round(float(o), 4),
                round(float(hi), 4),
                round(float(lo), 4),
                round(float(c), 4),
                int(v),
            ]
        )
        prev_close = c
    return bars


def build() -> None:
    cal = get_calendar()
    rng = np.random.default_rng(SEED)

    # Sessions: N_BARS trading days ending BASE_AS_OF.
    end = cal.session_on_or_before(BASE_AS_OF)
    sessions: list[dt.date] = []
    cur = end
    for _ in range(N_BARS):
        sessions.append(cur)
        cur = cal.previous_session(cur)
    sessions.reverse()
    n = len(sessions)

    # --- market factor ---------------------------------------------------
    mkt_vol = 0.0085 * _vol_clusters(rng, n)
    r_market = 0.11 / 252 + mkt_vol * _t_noise(rng, n)

    series: dict[str, np.ndarray] = {}
    meta: dict[str, dict] = {}

    for t, (name, b, s, drift) in BROAD_ETF_PARAMS.items():
        r = drift / 252 + b * (r_market - 0.11 / 252)
        if s > 0:
            r = r + s * _t_noise(rng, n)
        series[t] = r
        meta[t] = {"name": name, "sector": None, "instrument_class": "broad_etf"}

    sector_ret: dict[str, np.ndarray] = {}
    for t, (name, b, s, drift) in SECTOR_ETF_PARAMS.items():
        r = drift / 252 + b * (r_market - 0.11 / 252) + s * _t_noise(rng, n)
        series[t] = r
        sector_ret[t] = r
        meta[t] = {"name": name, "sector": None, "instrument_class": "sector_etf"}

    for t, (name, sector, beta, idio, drift) in STOCKS.items():
        etf = SECTOR_BENCHMARKS[sector]
        idio_path = idio * _vol_clusters(rng, n) * _t_noise(rng, n)
        r = drift / 252 + beta * sector_ret[etf] + idio_path
        series[t] = r
        meta[t] = {"name": name, "sector": sector, "instrument_class": "stock"}

    # --- write base bars --------------------------------------------------
    bars_dir = FIXTURES / "bars"
    bars_dir.mkdir(parents=True, exist_ok=True)
    for t, r in series.items():
        base_vol = BASE_VOLUME.get(t, 12e6)
        bars = _to_bars(sessions, r, END_PRICE[t], base_vol, rng)
        (bars_dir / f"{t}.json").write_text(
            json.dumps({"ticker": t, "bars": bars}, separators=(",", ":")),
            encoding="utf-8",
        )

    last_close = {t: series_bars_last(bars_dir, t) for t in series}

    # --- catalog, profiles, earnings -------------------------------------
    catalog = []
    profiles = {}
    for t, m in meta.items():
        is_etf = m["instrument_class"] != "stock"
        catalog.append(
            {
                "ticker": t,
                "name": m["name"],
                "exchange": "NYSE ARCA" if is_etf else "NASDAQ",
                "type": "ETF" if is_etf else "Common Stock",
            }
        )
        profiles[t] = {"name": m["name"], "sector": m["sector"]}
    # A handful of extra catalog rows so search ranking has something to rank.
    for extra, nm in [
        ("AAP", "Advance Auto Parts Inc"),
        ("AA", "Alcoa Corp"),
        ("APLE", "Apple Hospitality REIT"),
        ("MSFU", "Direxion Daily MSFT Bull 2X"),
        ("NVDL", "GraniteShares 2x Long NVDA"),
        ("TSM", "Taiwan Semiconductor Mfg"),
    ]:
        catalog.append(
            {"ticker": extra, "name": nm, "exchange": "NASDAQ", "type": "Common Stock"}
        )

    (FIXTURES / "symbols.json").write_text(
        json.dumps(catalog, indent=1), encoding="utf-8"
    )
    (FIXTURES / "profiles.json").write_text(
        json.dumps(profiles, indent=1), encoding="utf-8"
    )

    # Quarterly earnings for stocks only, staggered by ticker hash.
    earnings: dict[str, list[str]] = {}
    for t, m in meta.items():
        if m["instrument_class"] != "stock":
            continue
        offset = (abs(hash(t)) % 25) - 12
        dates = []
        for i in range(0, n, 63):
            idx = min(max(i + offset, 0), n - 1)
            dates.append(sessions[idx].isoformat())
        earnings[t] = sorted(set(dates))
    (FIXTURES / "earnings.json").write_text(
        json.dumps(earnings, indent=1), encoding="utf-8"
    )

    # --- scenarios --------------------------------------------------------
    scen_dir = FIXTURES / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    nxt = cal.next_session(sessions[-1])

    def overlay_day(day: dt.date, rets: dict[str, float], vol_mult: dict[str, float] | None = None):
        out = {}
        vm = vol_mult or {}
        for t, r in rets.items():
            prev = last_close[t]
            c = prev * (1.0 + r)
            o = prev * (1.0 + r * 0.35)
            hi = max(o, c) * (1.0 + abs(r) * 0.2 + 0.002)
            lo = min(o, c) * (1.0 - abs(r) * 0.2 - 0.002)
            v = int(BASE_VOLUME.get(t, 12e6) * (1.0 + 6 * abs(r)) * vm.get(t, 1.0))
            out[t] = [
                [day.isoformat(), round(o, 4), round(hi, 4), round(lo, 4), round(c, 4), v]
            ]
        return out

    def factor_day(
        mkt: float, rng: np.random.Generator, idio_scale: float = 1.0,
        excess: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """One session generated through the SAME factor structure as history.

        Scenario days must obey the model the baselines were fitted on. Drawing
        each ticker independently decouples the ETFs from their constituents,
        the scorer correctly reports that as a large idiosyncratic move, and the
        fixture manufactures criticals it never meant to.

        `excess` adds an idiosyncratic return on top of the factor-implied one,
        so the intended magnitude is exactly what the scorer will measure.
        """
        exc = excess or {}
        out: dict[str, float] = {}
        for tk, (_n, b, sd, _d) in BROAD_ETF_PARAMS.items():
            out[tk] = b * mkt + float(rng.normal(0, sd)) * idio_scale
        for tk, (_n, b, sd, _d) in SECTOR_ETF_PARAMS.items():
            out[tk] = b * mkt + float(rng.normal(0, sd)) * idio_scale
        for tk, (_n, sector, beta, idio, _d) in STOCKS.items():
            etf = SECTOR_BENCHMARKS[sector]
            out[tk] = beta * out[etf] + float(rng.normal(0, idio)) * idio_scale
        for tk, e in exc.items():
            out[tk] = out[tk] + e
        return out

    # 1. Market-wide -5%: every name moves its beta times the market. The naive
    #    watchlist shows twenty red rows; the digest shows one banner.
    rets = factor_day(-0.05, np.random.default_rng(SEED + 1), idio_scale=0.35)
    _write_scenario(
        scen_dir,
        "market_crash",
        "Market-wide -5% day. Every row is red; nothing is unusual for itself.",
        nxt,
        overlay_day(nxt, rets),
        cal,
    )

    # 2. Single name -6% on a flat sector.
    rets2 = factor_day(
        -0.0005, np.random.default_rng(SEED + 2), idio_scale=0.4,
        excess={"NVDA": -0.062},
    )
    _write_scenario(
        scen_dir,
        "single_name",
        "NVDA -6.2% with XLK and SPY flat. One critical, everything else quiet.",
        nxt,
        overlay_day(nxt, rets2, {"NVDA": 3.5}),
        cal,
    )

    # 3. Spike and revert: +12% then back to roughly flat across five sessions.
    days = [nxt]
    for _ in range(4):
        days.append(cal.next_session(days[-1]))
    amd = [0.121, -0.035, -0.028, -0.030, -0.022]
    rng4 = np.random.default_rng(SEED + 3)
    per_day = [
        factor_day(
            float(rng4.normal(0.0002, 0.004)), rng4, idio_scale=0.5,
            excess={"AMD": amd[i]},
        )
        for i in range(len(days))
    ]
    prevs = dict(last_close)
    overlay: dict[str, list] = {t: [] for t in series}
    for i, d in enumerate(days):
        for t in series:
            r = per_day[i].get(t, 0.0)
            prev = prevs[t]
            c = prev * (1.0 + r)
            o = prev * (1.0 + r * 0.35)
            hi = max(o, c) * (1.0 + abs(r) * 0.2 + 0.002)
            lo = min(o, c) * (1.0 - abs(r) * 0.2 - 0.002)
            v = int(BASE_VOLUME.get(t, 12e6) * (1.0 + 6 * abs(r)) * (3.0 if (t == "AMD" and i == 0) else 1.0))
            overlay[t].append(
                [d.isoformat(), round(o, 4), round(hi, 4), round(lo, 4), round(c, 4), v]
            )
            prevs[t] = c
    _write_scenario(
        scen_dir,
        "spike_revert",
        "AMD +12.1% then round-trips to roughly flat over five sessions. "
        "z_move sees nothing; z_path sees the week.",
        days[-1],
        overlay,
        cal,
        window_sessions=5,
    )

    # 4. The default demo state: an ordinary session with a mix of tiers.
    rets4 = factor_day(
        -0.004, np.random.default_rng(SEED + 4), idio_scale=1.0,
        excess={"BA": -0.058, "META": 0.043, "DUK": 0.010},
    )
    _write_scenario(
        scen_dir,
        "baseline",
        "An ordinary session: one critical, one notable, the rest quiet.",
        nxt,
        overlay_day(nxt, rets4, {"BA": 4.0, "META": 2.5}),
        cal,
    )

    print(f"wrote {len(series)} bar files, {len(catalog)} catalog rows, 4 scenarios")


def series_bars_last(bars_dir: pathlib.Path, ticker: str) -> float:
    data = json.loads((bars_dir / f"{ticker}.json").read_text(encoding="utf-8"))
    return float(data["bars"][-1][4])


def _write_scenario(
    scen_dir: pathlib.Path,
    name: str,
    description: str,
    as_of: dt.date,
    overlay: dict[str, list],
    cal,
    window_sessions: int = 1,
) -> None:
    """A scenario is the base history plus a short overlay of event days.

    `as_if_last_seen` points at the close `window_sessions` sessions before
    `as_of`, which is what makes the demo reproducible without waiting a week
    to accumulate a diff.
    """
    ref = as_of
    for _ in range(window_sessions):
        ref = cal.previous_session(ref)
    bounds = cal.bounds(ref)
    payload = {
        "name": name,
        "description": description,
        "as_of": as_of.isoformat(),
        "as_if_last_seen": bounds.close_utc.isoformat() if bounds else None,
        "window_sessions": window_sessions,
        "overlay": overlay,
    }
    (scen_dir / f"{name}.json").write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8"
    )


if __name__ == "__main__":
    build()
