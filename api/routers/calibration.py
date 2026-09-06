"""The calibration surface.

Everything else in this system validates the model against itself. Two numbers
here do not:

  the alert RATE, measured by replaying a year of stored bars through the
  production scorer and comparing it against a normal null; and

  precision@critical, the fraction of criticals a human agreed with.

The second is the only check on whether "meaningful" is meaningful to a person,
which is what the brief actually asked.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock
from api.config import settings
from api.db import get_session
from api.schemas import CalibrationOut

router = APIRouter(tags=["calibration"])


def _artifact_path() -> pathlib.Path:
    p = pathlib.Path(settings.fixtures_dir)
    if not p.is_absolute():
        p = pathlib.Path(__file__).resolve().parent.parent.parent / p
    return p / "calibration.json"


async def precision_at_critical(session: AsyncSession, days: int = 90) -> dict:
    """What fraction of criticals did a human agree with?

    A thumb is an explicit signal; a click-through is a weak positive; a fast
    dismissal is a weak negative. They are reported separately rather than
    blended, because an unlabelled composite would be exactly the kind of number
    this page exists to avoid.
    """
    # `clock.now()`, not the wall clock: feedback rows are stamped with the
    # system clock, and under the replay providers that sits on a fixture date.
    # A wall-clock window would silently exclude every row.
    since = clock.now() - dt.timedelta(days=days)
    row = (
        await session.execute(
            text(
                """
        SELECT tier,
               count(*)                                            AS shown,
               count(*) FILTER (WHERE thumb =  1)                   AS up,
               count(*) FILTER (WHERE thumb = -1)                   AS down,
               count(*) FILTER (WHERE clicked_through)              AS clicked,
               count(*) FILTER (WHERE dismissed_fast)               AS dismissed
          FROM digest_feedback
         WHERE shown_at >= :since
         GROUP BY tier
        """
            ),
            {"since": since},
        )
    ).mappings().all()

    by_tier = {r["tier"]: dict(r) for r in row}
    crit = by_tier.get("critical", {})
    up, down = int(crit.get("up", 0)), int(crit.get("down", 0))
    judged = up + down
    shown = int(crit.get("shown", 0))
    clicked = int(crit.get("clicked", 0))
    dismissed = int(crit.get("dismissed", 0))

    return {
        "window_days": days,
        "critical_shown": shown,
        "explicit_judgements": judged,
        "precision": round(up / judged, 4) if judged else None,
        "click_through_rate": round(clicked / shown, 4) if shown else None,
        "fast_dismiss_rate": round(dismissed / shown, 4) if shown else None,
        "by_tier": by_tier,
        "note": (
            "Precision is over explicit thumbs only. With no thumbs yet it is "
            "null rather than 1.0: an unjudged critical is not a correct one."
            if not judged
            else "Precision is over explicit thumbs on critical cards."
        ),
    }


@router.get("/calibration", response_model=CalibrationOut)
async def calibration(
    session: AsyncSession = Depends(get_session),
) -> CalibrationOut:
    """Unauthenticated, because nothing here is anybody's.

    The rates are a replay of stored bars through the scorer, and
    `precision_at_critical` aggregates every vote in `digest_feedback` rather
    than the caller's. There is no row on this page that a `user_id` would
    filter, so requiring a token would only hide the evidence.
    """
    path = _artifact_path()
    if not path.exists():
        raise HTTPException(
            503,
            "No calibration run yet. Run `python -m scripts.calibrate` to replay "
            "12 months through the production scorer.",
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["precision_at_critical"] = await precision_at_critical(session)
    data["generated_at"] = dt.datetime.fromisoformat(data["generated_at"])
    return CalibrationOut(**data)
