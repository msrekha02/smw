"""Replay providers. `docker compose up` with no API keys must boot fully
working, and this is what makes that true.

`ReplayHistory` serves the deterministic bar fixtures, so the baseline maths can
be tested against a known generative model. `ReplayQuotes` serves an intraday
path that is a pure function of (ticker, session, instant), so the product is
demoable at any hour and two runs at the same instant agree exactly.
"""
from __future__ import annotations

import bisect
import datetime as dt
import functools
import hashlib
import json
import pathlib
from collections.abc import AsyncIterator, Iterable, Sequence

import numpy as np

from api import clock
from api.calendar_ny import get_calendar
from api.config import BROAD_ETFS, SECTOR_ETFS, settings
from providers.base import (
    Bar,
    Profile,
    Quote,
    SymbolRow,
    Tick,
)

TICKS_PER_SESSION = 390  # one per regular-session minute


def _root() -> pathlib.Path:
    p = pathlib.Path(settings.fixtures_dir)
    if not p.is_absolute():
        p = pathlib.Path(__file__).resolve().parent.parent / p
    return p


@functools.lru_cache(maxsize=1)
def _scenario(name: str) -> dict:
    f = _root() / "scenarios" / f"{name}.json"
    if not f.exists():
        return {"name": name, "overlay": {}, "as_of": None, "description": ""}
    return json.loads(f.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=256)
def _base_bars(ticker: str) -> tuple[tuple, ...]:
    f = _root() / "bars" / f"{ticker.upper()}.json"
    if not f.exists():
        return ()
    return tuple(tuple(b) for b in json.loads(f.read_text(encoding="utf-8"))["bars"])


@functools.lru_cache(maxsize=256)
def _full_bars(ticker: str, scenario: str) -> tuple[Bar, ...]:
    """Base history plus the scenario overlay, ascending, de-duplicated."""
    rows = {r[0]: r for r in _base_bars(ticker)}
    for r in _scenario(scenario)["overlay"].get(ticker.upper(), []):
        rows[r[0]] = r
    out = []
    for d in sorted(rows):
        _, o, h, low, c, v = rows[d]
        out.append(
            Bar(dt.date.fromisoformat(d), float(o), float(h), float(low), float(c), int(v))
        )
    return tuple(out)


def clear_caches() -> None:
    _scenario.cache_clear()
    _base_bars.cache_clear()
    _full_bars.cache_clear()
    _intraday_path.cache_clear()


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class ReplayHistory:
    """Deterministic split-adjusted daily bars from `fixtures/`."""

    name = "replay-history"

    def __init__(self, scenario: str | None = None) -> None:
        self.scenario = scenario or settings.replay_scenario
        self.calls = 0

    def _visible(self, ticker: str) -> list[Bar]:
        """Bars up to and including the current replay session.

        A fixture file holds the scenario's future too; serving it would let the
        nightly job see tomorrow.
        """
        today = clock.today_et()
        return [b for b in _full_bars(ticker, self.scenario) if b.bar_date <= today]

    async def fetch_time_series_raw(self, ticker: str, outputsize: int) -> dict:
        self.calls += 1
        bars = self._visible(ticker)[-outputsize:]
        # Mirror Twelve Data's shape: newest first, everything a string.
        return {
            "meta": {"symbol": ticker.upper(), "interval": "1day", "type": "replay"},
            "values": [
                {
                    "datetime": b.bar_date.isoformat(),
                    "open": f"{b.open:.4f}",
                    "high": f"{b.high:.4f}",
                    "low": f"{b.low:.4f}",
                    "close": f"{b.close:.4f}",
                    "volume": str(b.volume or 0),
                }
                for b in reversed(bars)
            ],
            "status": "ok",
        }

    def parse_time_series(self, payload: dict) -> list[Bar]:
        out = [
            Bar(
                dt.date.fromisoformat(v["datetime"][:10]),
                float(v["open"]),
                float(v["high"]),
                float(v["low"]),
                float(v["close"]),
                int(float(v["volume"])) if v.get("volume") not in (None, "") else None,
            )
            for v in payload.get("values", [])
        ]
        out.sort(key=lambda b: b.bar_date)
        return out

    async def daily_bars(self, ticker: str, outputsize: int) -> list[Bar]:
        return self.parse_time_series(
            await self.fetch_time_series_raw(ticker, outputsize)
        )

    async def list_symbols(self) -> list[SymbolRow]:
        f = _root() / "symbols.json"
        rows = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        return [
            SymbolRow(r["ticker"], r.get("name"), r.get("exchange"), r.get("type"))
            for r in rows
        ]

    async def market_state(self) -> str:
        return "open" if get_calendar().is_open(clock.now()) else "closed"


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


def _seed_for(ticker: str, session: dt.date) -> int:
    h = hashlib.blake2b(f"{ticker}:{session.isoformat()}".encode(), digest_size=8)
    return int.from_bytes(h.digest(), "big") % (2**31)


@functools.lru_cache(maxsize=512)
def _intraday_path(
    ticker: str, session: dt.date, prev_close: float, target_close: float
) -> tuple[float, ...]:
    """A Brownian bridge from the previous close to the session's close.

    Seeded by (ticker, session), so the price at 11:04 is the same on every
    machine and every run, and the close the bridge lands on is the fixture's
    close -- the live path and the stored bar never disagree.
    """
    rng = np.random.default_rng(_seed_for(ticker, session))
    n = TICKS_PER_SESSION
    drift = (target_close / prev_close) - 1.0
    scale = max(abs(drift), 0.004) * 0.55
    steps = rng.normal(0.0, scale / np.sqrt(n), size=n)
    walk = np.cumsum(steps)
    # Pin both ends: subtract the linear interpolation of the terminal error.
    walk = walk - np.linspace(0.0, 1.0, n) * walk[-1]
    path = prev_close * (1.0 + walk + np.linspace(0.0, 1.0, n) * drift)
    path[-1] = target_close
    return tuple(round(float(x), 4) for x in path)


class ReplayQuotes:
    """Intraday prices, sector profiles and earnings dates from `fixtures/`."""

    name = "replay-quotes"
    supports_stream = True

    def __init__(self, scenario: str | None = None) -> None:
        self.scenario = scenario or settings.replay_scenario
        self.calls = 0

    # -- price ---------------------------------------------------------

    def _bars(self, ticker: str) -> tuple[Bar, ...]:
        return _full_bars(ticker, self.scenario)

    def price_at(self, ticker: str, at: dt.datetime) -> tuple[float, float, dt.date, bool]:
        """Return (price, prev_close, session, is_extended_hours)."""
        cal = get_calendar()
        bars = self._bars(ticker)
        if not bars:
            raise KeyError(ticker)
        dates = [b.bar_date for b in bars]
        d = cal.current_or_last_session(at)
        i = bisect.bisect_right(dates, d) - 1
        if i < 0:
            raise KeyError(ticker)
        bar = bars[i]
        prev = bars[i - 1].close if i > 0 else bar.open

        if bar.bar_date != d or not cal.is_open(at):
            # Outside the regular session: the session's close is the last
            # scoreable price. Extended-hours prints are display-only.
            return bar.close, prev, bar.bar_date, not cal.is_open(at)

        frac = cal.session_fraction_elapsed(at)
        path = _intraday_path(ticker.upper(), d, prev, bar.close)
        idx = min(int(frac * (TICKS_PER_SESSION - 1)), TICKS_PER_SESSION - 1)
        return path[idx], prev, d, False

    def _volume_at(self, ticker: str, session: dt.date, frac: float) -> int:
        bars = {b.bar_date: b for b in self._bars(ticker)}
        b = bars.get(session)
        if b is None or b.volume is None:
            return 0
        return int(b.volume * max(frac, 0.02))

    async def quote(self, ticker: str) -> Quote:
        self.calls += 1
        at = clock.now()
        px, prev, session, ext = self.price_at(ticker, at)
        cal = get_calendar()
        frac = cal.session_fraction_elapsed(at) if not ext else 1.0
        return Quote(
            ticker=ticker.upper(),
            price=px,
            prev_close=prev,
            day_volume=self._volume_at(ticker, session, frac),
            at=at,
            is_extended_hours=ext,
            source="mock",
        )

    async def quotes(self, tickers: Sequence[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for t in tickers:
            try:
                out[t.upper()] = await self.quote(t)
            except KeyError:
                continue
        return out

    # -- reference data ------------------------------------------------

    @functools.cached_property
    def _profiles(self) -> dict:
        f = _root() / "profiles.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    @functools.cached_property
    def _earnings(self) -> dict:
        f = _root() / "earnings.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    async def profile(self, ticker: str) -> Profile:
        t = ticker.upper()
        p = self._profiles.get(t, {})
        return Profile(ticker=t, name=p.get("name"), sector=p.get("sector"))

    async def earnings_history(self, ticker: str) -> list[dt.date]:
        today = clock.today_et()
        return [
            d
            for d in (dt.date.fromisoformat(x) for x in self._earnings.get(ticker.upper(), []))
            if d <= today
        ]

    async def earnings_calendar(
        self, start: dt.date, end: dt.date, tickers: Iterable[str] | None = None
    ) -> dict[str, list[dt.date]]:
        want = {t.upper() for t in tickers} if tickers else None
        out: dict[str, list[dt.date]] = {}
        for t, ds in self._earnings.items():
            if want and t not in want:
                continue
            hits = [
                d for d in (dt.date.fromisoformat(x) for x in ds) if start <= d <= end
            ]
            if hits:
                out[t] = hits
        return out

    # -- stream --------------------------------------------------------

    async def stream(self, tickers: Sequence[str]) -> AsyncIterator[Tick]:
        """Emit one tick per symbol per second of replay time."""
        import asyncio

        while True:
            at = clock.now()
            for t in tickers:
                try:
                    px, _prev, session, ext = self.price_at(t, at)
                except KeyError:
                    continue
                if ext:
                    continue
                yield Tick(t.upper(), px, None, at)
            await asyncio.sleep(1.0)


def classify(ticker: str, sector: str | None) -> str:
    t = ticker.upper()
    if t in BROAD_ETFS:
        return "broad_etf"
    if t in SECTOR_ETFS:
        return "sector_etf"
    del sector
    return "stock"
