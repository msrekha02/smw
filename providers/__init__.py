"""Provider selection.

`PROVIDER_MODE=replay` (the default) is a hard requirement, not a convenience:
nothing downstream should ever be blocked on market hours, a rate limit, or a
provider outage. If live mode is selected but a key is missing, we fall back to
replay for that half and say so, rather than booting a half-dead system.
"""
from __future__ import annotations

import functools

from api.config import settings
from providers.base import (
    Bar,
    HistoryProvider,
    Profile,
    ProviderBundle,
    ProviderError,
    Quote,
    QuotaExhausted,
    QuoteProvider,
    SymbolRow,
    Tick,
)

__all__ = [
    "Bar",
    "HistoryProvider",
    "Profile",
    "ProviderBundle",
    "ProviderError",
    "QuotaExhausted",
    "Quote",
    "QuoteProvider",
    "SymbolRow",
    "Tick",
    "get_providers",
    "reset_providers",
]


@functools.lru_cache(maxsize=1)
def get_providers() -> ProviderBundle:
    from providers.replay import ReplayHistory, ReplayQuotes

    notes: list[str] = []
    if not settings.live:
        return ProviderBundle(ReplayHistory(), ReplayQuotes(), "replay", notes)

    history: object
    quotes: object
    if settings.twelvedata_api_key:
        from providers.twelvedata import TwelveDataHistory

        history = TwelveDataHistory()
    else:
        history = ReplayHistory()
        notes.append("TWELVEDATA_API_KEY unset -- history is on replay fixtures")

    if settings.finnhub_api_key:
        from providers.finnhub import FinnhubQuotes

        quotes = FinnhubQuotes()
    else:
        quotes = ReplayQuotes()
        notes.append("FINNHUB_API_KEY unset -- quotes are on replay fixtures")

    mode = "live" if not notes else "mixed"
    return ProviderBundle(history, quotes, mode, notes)  # type: ignore[arg-type]


def reset_providers() -> None:
    get_providers.cache_clear()
