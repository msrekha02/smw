"""Trading-calendar wrapper. Every date decision in the system goes through here.

All date arithmetic happens in America/New_York. Storage is UTC. Slicing a
window in UTC means a user acking at 02:00 IST on Sep 5 is on Sep 4 in ET and
silently misses a full trading day.

Session lengths come from `exchange_calendars`, never from a hardcoded 23400
seconds: half-days close at 13:00, and pretending otherwise inflates z by ~35%
on those days.
"""
from __future__ import annotations

import datetime as dt
import functools
from dataclasses import dataclass

import exchange_calendars as xcals
import pandas as pd

from api.config import EXCHANGE_CALENDAR, MARKET_TZ

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

ET = ZoneInfo(MARKET_TZ)
UTC = dt.timezone.utc


def to_et(t: dt.datetime) -> dt.datetime:
    """Normalise any datetime to America/New_York. Naive input is assumed UTC."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(ET)


def et_date(t: dt.datetime) -> dt.date:
    return to_et(t).date()


def _ts(t: dt.datetime) -> pd.Timestamp:
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return pd.Timestamp(t).tz_convert("UTC")


@dataclass(frozen=True)
class SessionBounds:
    session: dt.date
    open_utc: dt.datetime
    close_utc: dt.datetime

    @property
    def length_s(self) -> float:
        return (self.close_utc - self.open_utc).total_seconds()


class TradingCalendar:
    """Thin, cached wrapper over `exchange_calendars`."""

    def __init__(self, name: str = EXCHANGE_CALENDAR) -> None:
        self.name = name
        self._cal = xcals.get_calendar(name)

    # -- session lookup ----------------------------------------------------

    def is_session(self, d: dt.date) -> bool:
        return bool(self._cal.is_session(pd.Timestamp(d)))

    @functools.lru_cache(maxsize=4096)
    def _bounds(self, d: dt.date) -> SessionBounds | None:
        ts = pd.Timestamp(d)
        if not self._cal.is_session(ts):
            return None
        return SessionBounds(
            session=d,
            open_utc=self._cal.session_open(ts).to_pydatetime(),
            close_utc=self._cal.session_close(ts).to_pydatetime(),
        )

    def bounds(self, d: dt.date) -> SessionBounds | None:
        return self._bounds(d)

    def session_length_s(self, d: dt.date) -> float:
        b = self._bounds(d)
        return b.length_s if b else 0.0

    # `exchange_calendars.previous_session` raises NotSessionError unless its
    # argument is itself a session, which is never a safe assumption here: the
    # inputs are user timestamps, and Labor Day is a perfectly ordinary thing
    # for one to land on. `date_to_session` accepts any date.

    def session_on_or_before(self, d: dt.date) -> dt.date:
        return self._cal.date_to_session(pd.Timestamp(d), direction="previous").date()

    def session_on_or_after(self, d: dt.date) -> dt.date:
        return self._cal.date_to_session(pd.Timestamp(d), direction="next").date()

    def previous_session(self, d: dt.date) -> dt.date:
        """The last session strictly before `d`, whether or not `d` is one."""
        return self.session_on_or_before(d - dt.timedelta(days=1))

    def next_session(self, d: dt.date) -> dt.date:
        """The first session strictly after `d`."""
        return self.session_on_or_after(d + dt.timedelta(days=1))

    def sessions_in_range(self, start: dt.date, end: dt.date) -> list[dt.date]:
        if end < start:
            return []
        idx = self._cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
        return [t.date() for t in idx]

    # -- the three functions the scorer depends on -------------------------

    def sessions_between(self, a: dt.datetime, b: dt.datetime) -> int:
        """Count session closes c with a < c <= b.

        `sessions_between(Fri 18:00 ET, Sat 09:00 ET) == 0`: Friday's close is
        already behind `a`, and no other close falls in the interval.
        """
        if b <= a:
            return 0
        a_u, b_u = _ts(a), _ts(b)
        lo = (a_u.tz_convert(ET) - pd.Timedelta(days=6)).date()
        hi = (b_u.tz_convert(ET) + pd.Timedelta(days=2)).date()
        n = 0
        for s in self.sessions_in_range(lo, hi):
            bd = self._bounds(s)
            if bd is None:
                continue
            close = pd.Timestamp(bd.close_utc)
            if a_u < close <= b_u:
                n += 1
        return n

    def session_n_ago(self, n: int, ref: dt.date | None = None) -> dt.date:
        """The session `n` trading days before `ref` (default: today in ET)."""
        ref = ref or dt.datetime.now(ET).date()
        cur = self.session_on_or_before(ref)
        for _ in range(max(n, 0)):
            cur = self.previous_session(cur)
        return cur

    def session_fraction_elapsed(self, now: dt.datetime) -> float:
        """Fraction of the current session already elapsed, in [0, 1].

        Uses the session's TRUE length. On a 13:00 half-day close this returns
        1.0 at 13:00, not 0.54.
        """
        d = et_date(now)
        b = self._bounds(d)
        if b is None:
            return 0.0
        n = _ts(now)
        if n <= pd.Timestamp(b.open_utc):
            return 0.0
        if n >= pd.Timestamp(b.close_utc):
            return 1.0
        return (n - pd.Timestamp(b.open_utc)).total_seconds() / b.length_s

    def session_fraction_between(self, t0: dt.datetime, t1: dt.datetime) -> float:
        """Fraction of a single session between two instants inside it.

        The same-session branch anchors on a mid-session price, not on a close,
        so the dispersion that belongs in the denominator is the fraction of the
        session actually traversed. Measuring from the open instead would say a
        15:50 -> 15:55 recheck spanned a whole day.
        """
        if t1 <= t0:
            return 0.0
        d = et_date(t1)
        b = self._bounds(d)
        if b is None:
            return 0.0
        lo = max(_ts(t0), pd.Timestamp(b.open_utc))
        hi = min(_ts(t1), pd.Timestamp(b.close_utc))
        if hi <= lo:
            return 0.0
        return (hi - lo).total_seconds() / b.length_s

    # -- convenience -------------------------------------------------------

    def is_open(self, now: dt.datetime) -> bool:
        d = et_date(now)
        b = self._bounds(d)
        if b is None:
            return False
        n = _ts(now)
        return pd.Timestamp(b.open_utc) <= n < pd.Timestamp(b.close_utc)

    def is_extended_hours(self, now: dt.datetime) -> bool:
        """A weekday outside the regular session on a day that is a session."""
        d = et_date(now)
        b = self._bounds(d)
        if b is None:
            return False
        return not self.is_open(now)

    def current_or_last_session(self, now: dt.datetime) -> dt.date:
        return self.session_on_or_before(et_date(now))

    def completed_sessions_after(self, ref_date: dt.date, now: dt.datetime) -> int:
        """Sessions strictly after `ref_date` whose close is at or before `now`."""
        n_u = _ts(now)
        cnt = 0
        end = et_date(now) + dt.timedelta(days=1)
        for s in self.sessions_in_range(ref_date + dt.timedelta(days=1), end):
            b = self._bounds(s)
            if b and pd.Timestamp(b.close_utc) <= n_u:
                cnt += 1
        return cnt

    def session_span(self, t0: dt.datetime, t1: dt.datetime) -> float:
        """Trading time between two instants, in units of one full session.

        This is the dispersion the denominator needs, and it is the same
        quantity whether the window is five minutes or five weeks: sum the
        overlap of [t0, t1] with each session, each divided by that session's
        TRUE length. Weekends and holidays contribute nothing. A half-day
        contributes a full 1.0 when fully spanned, because a half-day is a whole
        session's worth of information -- just a shorter one.
        """
        if t1 <= t0:
            return 0.0
        a, b = _ts(t0), _ts(t1)
        lo = (a.tz_convert(ET) - pd.Timedelta(days=1)).date()
        hi = (b.tz_convert(ET) + pd.Timedelta(days=1)).date()
        total = 0.0
        for s in self.sessions_in_range(lo, hi):
            sb = self._bounds(s)
            if sb is None:
                continue
            o, c = pd.Timestamp(sb.open_utc), pd.Timestamp(sb.close_utc)
            start, end = max(a, o), min(b, c)
            if end > start:
                total += (end - start).total_seconds() / sb.length_s
        return total


@functools.lru_cache(maxsize=4)
def get_calendar(name: str = EXCHANGE_CALENDAR) -> TradingCalendar:
    return TradingCalendar(name)
