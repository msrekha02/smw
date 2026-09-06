"""Twelve Data: the slow clock.

`/time_series` costs one credit per symbol regardless of `outputsize` (up to
5000) and supports `adjust=splits`. One credit buys five years of split-adjusted
daily bars, which is why the baseline seeds from 1260 bars rather than 250 --
the extra history is free, and it is what makes the residual distribution and
the calibration script meaningful.

Free tier: 8 credits/min, 800/day. Spending is metered by `api.quota`, not here;
this class only makes calls and reports failures honestly.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Sequence

import httpx

from api.config import TD_PER_MIN, settings
from providers.base import Bar, ProviderError, QuotaExhausted, SymbolRow

BASE = "https://api.twelvedata.com"


class _MinuteBucket:
    """8 credits/min. A shared async gate, not a retry loop."""

    def __init__(self, per_min: int) -> None:
        self.per_min = per_min
        self._times: list[float] = []
        self._lock = asyncio.Lock()

    async def take(self, n: int = 1) -> None:
        async with self._lock:
            while True:
                loop = asyncio.get_running_loop()
                now = loop.time()
                self._times = [t for t in self._times if now - t < 60.0]
                if len(self._times) + n <= self.per_min:
                    self._times.extend([now] * n)
                    return
                await asyncio.sleep(60.0 - (now - self._times[0]) + 0.05)


class TwelveDataHistory:
    name = "twelvedata"

    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None):
        self.api_key = api_key or settings.twelvedata_api_key
        if not self.api_key:
            raise ProviderError("TWELVEDATA_API_KEY is required in live mode", retryable=False)
        self._client = client or httpx.AsyncClient(timeout=30.0, base_url=BASE)
        self._bucket = _MinuteBucket(TD_PER_MIN)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict, credits: int = 1) -> dict:
        await self._bucket.take(credits)
        params = {**params, "apikey": self.api_key}
        try:
            r = await self._client.get(path, params=params)
        except httpx.HTTPError as e:
            raise ProviderError(f"twelvedata transport: {e}") from e
        if r.status_code == 429:
            raise QuotaExhausted("twelvedata 429")
        if r.status_code >= 500:
            raise ProviderError(f"twelvedata {r.status_code}", status=r.status_code)
        if r.status_code >= 400:
            raise ProviderError(
                f"twelvedata {r.status_code}: {r.text[:200]}",
                retryable=False,
                status=r.status_code,
            )
        data = r.json()
        # Twelve Data reports errors in a 200 body.
        if isinstance(data, dict) and data.get("status") == "error":
            code = data.get("code")
            msg = data.get("message", "")
            if code == 429:
                raise QuotaExhausted(f"twelvedata quota: {msg}")
            raise ProviderError(f"twelvedata error {code}: {msg}", retryable=code in (500, 503))
        return data

    # -- HistoryProvider ------------------------------------------------

    async def fetch_time_series_raw(self, ticker: str, outputsize: int) -> dict:
        return await self._get(
            "/time_series",
            {
                "symbol": ticker.upper(),
                "interval": "1day",
                "outputsize": min(max(outputsize, 1), 5000),
                "adjust": "splits",
                "order": "DESC",
                "timezone": "America/New_York",
            },
        )

    def parse_time_series(self, payload: dict) -> list[Bar]:
        vals = payload.get("values") or []
        out: list[Bar] = []
        for v in vals:
            try:
                out.append(
                    Bar(
                        dt.date.fromisoformat(str(v["datetime"])[:10]),
                        float(v["open"]),
                        float(v["high"]),
                        float(v["low"]),
                        float(v["close"]),
                        int(float(v["volume"])) if v.get("volume") not in (None, "") else None,
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda b: b.bar_date)
        return out

    async def daily_bars(self, ticker: str, outputsize: int) -> list[Bar]:
        return self.parse_time_series(await self.fetch_time_series_raw(ticker, outputsize))

    async def list_symbols(self) -> list[SymbolRow]:
        data = await self._get("/stocks", {"country": "US"}, credits=1)
        rows = data.get("data") or []
        etf = await self._get("/etf", {"country": "US"}, credits=1)
        rows += etf.get("data") or []
        out: list[SymbolRow] = []
        seen: set[str] = set()
        for r in rows:
            t = (r.get("symbol") or "").upper()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(
                SymbolRow(t, r.get("name"), r.get("exchange"), r.get("type") or "ETF")
            )
        return out

    async def market_state(self) -> str:
        try:
            data = await self._get("/market_state", {"exchange": "NYSE"}, credits=1)
        except ProviderError:
            return "unknown"
        rows = data if isinstance(data, list) else data.get("data", [])
        for r in rows:
            if r.get("is_market_open") is not None:
                return "open" if r["is_market_open"] else "closed"
        return "unknown"

    async def quotes_eod(self, tickers: Sequence[str]) -> dict[str, float]:
        """Last close, one credit per symbol. Used only as a WS-outage fallback."""
        out: dict[str, float] = {}
        for t in tickers:
            data = await self._get("/eod", {"symbol": t.upper()})
            if "close" in data:
                out[t.upper()] = float(data["close"])
        return out
