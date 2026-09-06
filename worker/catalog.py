"""The local symbol catalog.

`/stocks?country=US` is one credit and returns the whole US universe, so search
costs nothing per query: it is a sub-millisecond local trigram query that keeps
working during a provider outage and validates adds against a known universe
rather than against whatever the user typed.

Ranking is exact ticker, then prefix, then trigram similarity, then watcher
count -- so "aapl" returns AAPL first and not Apple Hospitality REIT.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock
from api.quota import Exhausted, catalog_budget
from providers import get_providers
from providers.base import ProviderError

log = logging.getLogger("smw.catalog")

# US-listed equities and ETFs only, enforced at add time: both free tiers are
# US-only, so anything else would resolve to a price the system cannot explain.
ALLOWED_TYPES = (
    "Common Stock", "COMMON STOCK", "ETF", "American Depositary Receipt",
    "Depositary Receipt", "REIT", "Class A", "Class B",
)


async def sync_catalog(session: AsyncSession) -> int:
    budget = catalog_budget()
    try:
        await budget.spend(session, 2)
    except Exhausted:
        log.info("catalog partition exhausted; keeping yesterday's catalog")
        return 0
    try:
        rows = await get_providers().history.list_symbols()
    except ProviderError as e:
        log.warning("catalog sync failed: %s", e)
        return 0
    if not rows:
        return 0

    await session.execute(
        text(
            """
        INSERT INTO symbol_catalog (ticker, name, exchange, type, is_active, refreshed_at)
        VALUES (:t, :n, :e, :ty, true, :now)
        ON CONFLICT (ticker) DO UPDATE SET
            name = EXCLUDED.name, exchange = EXCLUDED.exchange,
            type = EXCLUDED.type, is_active = true,
            refreshed_at = EXCLUDED.refreshed_at
        """
        ),
        [
            {
                "t": r.ticker.upper(), "n": r.name, "e": r.exchange,
                "ty": r.type, "now": clock.now(),
            }
            for r in rows
        ],
    )
    # Anything absent from today's catalog is delisted, not deleted: a user may
    # still be watching it and deserves "symbol no longer resolves", not a gap.
    await session.execute(
        text(
            "UPDATE symbol_catalog SET is_active = false"
            " WHERE refreshed_at IS DISTINCT FROM :now"
        ),
        {"now": clock.now()},
    )
    await refresh_refcounts(session)
    log.info("catalog synced: %d symbols", len(rows))
    return len(rows)


async def refresh_refcounts(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
        UPDATE symbol_catalog c
           SET refcount = COALESCE(x.n, 0)
          FROM (SELECT ticker, count(*) AS n FROM watchlist_items GROUP BY ticker) x
         WHERE c.ticker = x.ticker
        """
        )
    )


SEARCH_SQL = """
SELECT c.ticker, c.name, c.exchange, c.type, c.refcount,
       (t.ticker IS NOT NULL AND t.status = 'active') AS seeded,
       (w.ticker IS NOT NULL) AS watched,
       CASE WHEN upper(c.ticker) = upper(:q)                    THEN 0
            WHEN upper(c.ticker) LIKE upper(:q) || '%'           THEN 1
            WHEN upper(coalesce(c.name,'')) LIKE upper(:q) || '%' THEN 2
            ELSE 3 END AS rank_band,
       similarity(c.ticker || ' ' || coalesce(c.name,''), :q) AS sim
  FROM symbol_catalog c
  LEFT JOIN tickers t ON t.ticker = c.ticker
  LEFT JOIN watchlist_items w ON w.ticker = c.ticker AND w.user_id = :uid
 WHERE c.is_active
   AND (upper(c.ticker) LIKE upper(:q) || '%'
        OR upper(coalesce(c.name,'')) LIKE '%' || upper(:q) || '%'
        OR (c.ticker || ' ' || coalesce(c.name,'')) % :q)
 ORDER BY rank_band ASC, sim DESC, c.refcount DESC, c.ticker ASC
 LIMIT :n
"""


async def search(session: AsyncSession, q: str, user_id, limit: int = 12) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return []
    rows = (
        await session.execute(
            text(SEARCH_SQL), {"q": q, "uid": user_id, "n": limit}
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def is_listed(session: AsyncSession, ticker: str) -> bool:
    n = (
        await session.execute(
            text(
                "SELECT count(*) FROM symbol_catalog"
                " WHERE ticker = :t AND is_active"
            ),
            {"t": ticker.upper()},
        )
    ).scalar_one()
    return int(n) > 0
