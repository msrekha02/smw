"""The compute phase, callable on its own.

Compute is a pure function of stored bars, so re-running it costs nothing and
always produces the same answer. That is what lets `worker/nightly/fetch.py`
treat a crash as "redo the compute" rather than "reconcile partial state", and
it is what makes `scripts/calibrate.py` able to rebuild a year of baselines
without touching a provider.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from api.db import session_scope
from worker.baseline.persist import recompute

log = logging.getLogger("smw.compute")


async def recompute_all(only: list[str] | None = None) -> dict[str, int]:
    async with session_scope() as s:
        if only:
            tickers = [t.upper() for t in only]
        else:
            tickers = [
                r[0]
                for r in (
                    await s.execute(
                        text(
                            "SELECT ticker FROM tickers WHERE status IN"
                            " ('active','seeding') ORDER BY ticker"
                        )
                    )
                ).all()
            ]

    ok = skipped = 0
    for t in tickers:
        async with session_scope() as s:
            res = await recompute(s, t)
        if res is None:
            skipped += 1
        else:
            ok += 1
    log.info("recomputed %d baselines, skipped %d", ok, skipped)
    return {"recomputed": ok, "skipped": skipped}
