"""Provider protocols.

Two interfaces, because no free provider does both well. Finnhub's
`/stock/candle` returns 403 on free keys, so historical OHLCV cannot come from
there at all; Twelve Data charges one credit per `/time_series` call regardless
of bar count, so five years of split-adjusted history costs the same as one day.

The mocks serve different purposes too: `ReplayHistory` gives deterministic
baselines for testing the maths, `ReplayQuotes` makes the product demoable at
any hour.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Bar:
    bar_date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


@dataclass(frozen=True, slots=True)
class Quote:
    ticker: str
    price: float
    prev_close: float | None
    day_volume: int | None
    at: dt.datetime
    is_extended_hours: bool = False
    source: str = "rest"


@dataclass(frozen=True, slots=True)
class Tick:
    ticker: str
    price: float
    volume: int | None
    at: dt.datetime


@dataclass(frozen=True, slots=True)
class SymbolRow:
    ticker: str
    name: str | None
    exchange: str | None
    type: str | None


@dataclass(frozen=True, slots=True)
class Profile:
    ticker: str
    name: str | None = None
    sector: str | None = None


class ProviderError(RuntimeError):
    """Any provider-side failure. Carries whether a retry could help."""

    def __init__(self, message: str, *, retryable: bool = True, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class QuotaExhausted(ProviderError):
    def __init__(self, message: str = "provider quota exhausted"):
        super().__init__(message, retryable=False)


@runtime_checkable
class HistoryProvider(Protocol):
    """Daily bars, the symbol catalog, and session state. The slow clock."""

    name: str

    async def fetch_time_series_raw(
        self, ticker: str, outputsize: int
    ) -> dict[str, Any]:
        """One credit. Returns the provider payload UNPARSED.

        The nightly job writes this to `provider_response_cache` before parsing,
        so a crash between the HTTP call and the parse cannot double-spend the
        credit on retry.
        """
        ...

    def parse_time_series(self, payload: dict[str, Any]) -> list[Bar]:
        """Pure. Ascending by date."""
        ...

    async def daily_bars(self, ticker: str, outputsize: int) -> list[Bar]:
        ...

    async def list_symbols(self) -> list[SymbolRow]:
        ...

    async def market_state(self) -> str:
        """`open` | `closed` | `unknown`."""
        ...


@runtime_checkable
class QuoteProvider(Protocol):
    """Real-time prices, sector lookup, earnings dates. The fast clock."""

    name: str
    supports_stream: bool

    async def quote(self, ticker: str) -> Quote:
        ...

    async def quotes(self, tickers: Sequence[str]) -> dict[str, Quote]:
        ...

    async def profile(self, ticker: str) -> Profile:
        ...

    async def earnings_history(self, ticker: str) -> list[dt.date]:
        ...

    async def earnings_calendar(
        self, start: dt.date, end: dt.date, tickers: Iterable[str] | None = None
    ) -> dict[str, list[dt.date]]:
        ...

    def stream(self, tickers: Sequence[str]) -> AsyncIterator[Tick]:
        """Yield ticks until cancelled. Reconnects internally."""
        ...


@dataclass
class ProviderBundle:
    history: HistoryProvider
    quotes: QuoteProvider
    mode: str = "replay"
    notes: list[str] = field(default_factory=list)
