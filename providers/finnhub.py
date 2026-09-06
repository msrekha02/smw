"""Finnhub: the fast clock.

Free tier gives 60 REST calls/min (metered here at 45 to leave headroom),
real-time US quotes, a WebSocket capped at 50 symbols, free sector lookup via
`/stock/profile2`, and both earnings endpoints.

`/stock/candle` is NOT usable: it returns 403 on free keys, historical OHLCV
being a premium product. That single fact is why this system has two providers.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import random
from collections.abc import AsyncIterator, Iterable, Sequence

import httpx
import websockets

from api import clock
from api.calendar_ny import UTC, get_calendar
from api.config import (
    FINNHUB_BUDGET_PER_MIN,
    FINNHUB_SECTOR_ALIASES,
    WS_HEARTBEAT_S,
    WS_RECONNECT_MAX_S,
    WS_RECONNECT_MIN_S,
    settings,
)
from providers.base import Profile, ProviderError, Quote, QuotaExhausted, Tick

BASE = "https://finnhub.io/api/v1"
WS_URL = "wss://ws.finnhub.io"


class _TokenBucket:
    def __init__(self, per_min: int) -> None:
        self.capacity = per_min
        self.tokens = float(per_min)
        self.rate = per_min / 60.0
        self._last: float | None = None
        self._lock = asyncio.Lock()

    async def take(self, n: int = 1) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            while True:
                now = loop.time()
                if self._last is None:
                    self._last = now
                self.tokens = min(
                    self.capacity, self.tokens + (now - self._last) * self.rate
                )
                self._last = now
                if self.tokens >= n:
                    self.tokens -= n
                    return
                await asyncio.sleep((n - self.tokens) / self.rate)


class FinnhubQuotes:
    name = "finnhub"
    supports_stream = True

    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None):
        self.api_key = api_key or settings.finnhub_api_key
        if not self.api_key:
            raise ProviderError("FINNHUB_API_KEY is required in live mode", retryable=False)
        self._client = client or httpx.AsyncClient(timeout=15.0, base_url=BASE)
        self._bucket = _TokenBucket(FINNHUB_BUDGET_PER_MIN)
        self.calls = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict) -> dict | list:
        await self._bucket.take()
        self.calls += 1
        try:
            r = await self._client.get(path, params={**params, "token": self.api_key})
        except httpx.HTTPError as e:
            raise ProviderError(f"finnhub transport: {e}") from e
        if r.status_code == 429:
            raise QuotaExhausted("finnhub 429")
        if r.status_code == 403:
            raise ProviderError(
                f"finnhub 403 on {path} -- premium endpoint on a free key",
                retryable=False,
                status=403,
            )
        if r.status_code >= 400:
            raise ProviderError(
                f"finnhub {r.status_code}: {r.text[:200]}",
                retryable=r.status_code >= 500,
                status=r.status_code,
            )
        return r.json()

    # -- QuoteProvider ---------------------------------------------------

    async def quote(self, ticker: str) -> Quote:
        d = await self._get("/quote", {"symbol": ticker.upper()})
        assert isinstance(d, dict)
        px = float(d.get("c") or 0.0)
        if px <= 0:
            raise ProviderError(f"finnhub quote {ticker}: no price", retryable=False)
        at = (
            dt.datetime.fromtimestamp(int(d["t"]), UTC)
            if d.get("t")
            else clock.now()
        )
        return Quote(
            ticker=ticker.upper(),
            price=px,
            prev_close=float(d["pc"]) if d.get("pc") else None,
            day_volume=None,
            at=at,
            is_extended_hours=not get_calendar().is_open(at),
            source="rest",
        )

    async def quotes(self, tickers: Sequence[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for t in tickers:
            try:
                out[t.upper()] = await self.quote(t)
            except ProviderError:
                continue
        return out

    async def profile(self, ticker: str) -> Profile:
        d = await self._get("/stock/profile2", {"symbol": ticker.upper()})
        assert isinstance(d, dict)
        raw = d.get("finnhubIndustry")
        return Profile(
            ticker=ticker.upper(),
            name=d.get("name"),
            sector=FINNHUB_SECTOR_ALIASES.get(raw or "", None),
        )

    async def earnings_history(self, ticker: str) -> list[dt.date]:
        d = await self._get("/stock/earnings", {"symbol": ticker.upper()})
        rows = d if isinstance(d, list) else []
        out: list[dt.date] = []
        for r in rows:
            per = r.get("period")
            if per:
                with contextlib.suppress(ValueError, TypeError):
                    out.append(dt.date.fromisoformat(str(per)[:10]))
        return sorted(set(out))

    async def earnings_calendar(
        self, start: dt.date, end: dt.date, tickers: Iterable[str] | None = None
    ) -> dict[str, list[dt.date]]:
        d = await self._get(
            "/calendar/earnings", {"from": start.isoformat(), "to": end.isoformat()}
        )
        assert isinstance(d, dict)
        want = {t.upper() for t in tickers} if tickers else None
        out: dict[str, list[dt.date]] = {}
        for r in d.get("earningsCalendar") or []:
            sym = (r.get("symbol") or "").upper()
            if not sym or (want and sym not in want):
                continue
            with contextlib.suppress(ValueError, TypeError):
                out.setdefault(sym, []).append(dt.date.fromisoformat(str(r["date"])[:10]))
        return out

    # -- stream ----------------------------------------------------------

    async def stream(self, tickers: Sequence[str]) -> AsyncIterator[Tick]:
        """Reconnect with jittered backoff; never raise upward."""
        delay = WS_RECONNECT_MIN_S
        url = f"{WS_URL}?token={self.api_key}"
        while True:
            try:
                async with websockets.connect(
                    url, ping_interval=WS_HEARTBEAT_S, ping_timeout=WS_HEARTBEAT_S * 2
                ) as ws:
                    for t in tickers:
                        await ws.send(json.dumps({"type": "subscribe", "symbol": t.upper()}))
                    delay = WS_RECONNECT_MIN_S
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") != "trade":
                            continue
                        for d in msg.get("data") or []:
                            yield Tick(
                                ticker=str(d["s"]).upper(),
                                price=float(d["p"]),
                                volume=int(d["v"]) if d.get("v") is not None else None,
                                at=dt.datetime.fromtimestamp(int(d["t"]) / 1000.0, UTC),
                            )
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay + random.uniform(0, delay * 0.3))
                delay = min(delay * 2, WS_RECONNECT_MAX_S)
