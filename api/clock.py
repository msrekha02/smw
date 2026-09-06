"""The single source of "now".

Every module asks this instead of `datetime.now()`, so the replay providers can
move the whole system onto a fixture date. In live mode it is a thin passthrough.

Replay clock modes (`REPLAY_CLOCK`):

  compressed  (default) map the real 24-hour wall clock onto the scenario's
              trading session, so prices are always moving and the product is
              demoable at any hour -- which is the entire point of the mocks.
  passthrough keep the real time of day, move only the date. Honest about
              closed markets; less useful at 3am.
  pinned      freeze at `REPLAY_NOW`. What the tests use.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

from api.calendar_ny import ET, UTC, get_calendar
from api.config import settings

_scenario_as_of: dt.date | None = None


def _fixtures_root() -> pathlib.Path:
    p = pathlib.Path(settings.fixtures_dir)
    if not p.is_absolute():
        p = pathlib.Path(__file__).resolve().parent.parent / p
    return p


def scenario_as_of() -> dt.date | None:
    """The last session covered by the active replay scenario."""
    global _scenario_as_of
    if _scenario_as_of is not None:
        return _scenario_as_of
    f = _fixtures_root() / "scenarios" / f"{settings.replay_scenario}.json"
    if not f.exists():
        return None
    _scenario_as_of = dt.date.fromisoformat(
        json.loads(f.read_text(encoding="utf-8"))["as_of"]
    )
    return _scenario_as_of


def reset_cache() -> None:
    global _scenario_as_of
    _scenario_as_of = None


def now() -> dt.datetime:
    """Current instant, UTC-aware."""
    real = dt.datetime.now(UTC)
    if settings.live:
        return real

    pinned = os.environ.get("REPLAY_NOW") or settings.replay_now
    if pinned:
        t = dt.datetime.fromisoformat(pinned)
        return t if t.tzinfo else t.replace(tzinfo=UTC)

    as_of = scenario_as_of()
    if as_of is None:
        return real

    mode = os.environ.get("REPLAY_CLOCK", "compressed")
    cal = get_calendar()
    b = cal.bounds(as_of)
    if b is None:
        return real

    if mode == "passthrough":
        et = real.astimezone(ET)
        return dt.datetime.combine(as_of, et.timetz()).astimezone(UTC)

    # compressed: seconds-of-day / 86400 through the true session length, so a
    # half-day session compresses correctly too.
    et = real.astimezone(ET)
    frac = (et.hour * 3600 + et.minute * 60 + et.second) / 86400.0
    return b.open_utc + dt.timedelta(seconds=b.length_s * frac)


def now_et() -> dt.datetime:
    return now().astimezone(ET)


def today_et() -> dt.date:
    return now_et().date()
