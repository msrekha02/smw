"""Calendar and window resolution.

All date arithmetic happens in America/New_York. Storage is UTC. Slicing a
window in UTC means a user acking at 02:00 IST on Sep 5 is on Sep 4 in ET and
silently misses a full trading day.
"""
from __future__ import annotations

import datetime as dt

import pytest

from api.calendar_ny import ET, UTC, et_date
from api.config import MAX_WINDOW_DAYS, MIN_N_EFF
from api.scoring.window import Snapshot, resolve_window

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

IST = ZoneInfo("Asia/Kolkata")

# 2025-07-03 is a 13:00 half-day (July 4th falls on a Friday).
HALF_DAY = dt.date(2025, 7, 3)
HOLIDAY = dt.date(2025, 9, 1)          # Labor Day
ORDINARY = dt.date(2025, 8, 27)        # a plain Wednesday


def at(cal, d: dt.date, hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)


# ---------------------------------------------------------------------------
# sessions_between
# ---------------------------------------------------------------------------


def test_friday_evening_to_saturday_morning_is_zero_sessions(cal):
    fri = dt.date(2025, 8, 29)
    sat = dt.date(2025, 8, 30)
    assert cal.sessions_between(at(cal, fri, 18), at(cal, sat, 9)) == 0


def test_weekend_crossing_counts_one_close(cal):
    fri, mon = dt.date(2025, 8, 29), dt.date(2025, 9, 2)
    assert cal.sessions_between(at(cal, fri, 10), at(cal, mon, 10)) == 1


def test_labor_day_is_not_a_session(cal):
    assert not cal.is_session(HOLIDAY)
    assert cal.previous_session(HOLIDAY) == dt.date(2025, 8, 29)


def test_session_fraction_on_a_half_day(cal):
    """`session_fraction_elapsed` on a 13:00 close returns 1.0 at 13:00, not
    0.54. A hardcoded 23400 would inflate z by ~35% on those days."""
    assert cal.is_session(HALF_DAY)
    assert cal.session_length_s(HALF_DAY) == pytest.approx(3.5 * 3600, abs=60)
    assert cal.session_fraction_elapsed(at(cal, HALF_DAY, 13, 0)) == pytest.approx(1.0)
    assert cal.session_fraction_elapsed(at(cal, HALF_DAY, 11, 15)) == pytest.approx(
        0.5, abs=0.02
    )
    assert cal.session_length_s(ORDINARY) == pytest.approx(6.5 * 3600, abs=60)


def test_session_span_ignores_weekends(cal):
    fri, mon = dt.date(2025, 8, 29), dt.date(2025, 9, 2)
    span = cal.session_span(at(cal, fri, 16), at(cal, mon, 16))
    assert span == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------


def test_two_am_ist_maps_to_the_previous_et_session():
    """02:00 IST on Sep 5 is 16:30 ET on Sep 4. Slicing in UTC would place the
    ack on Sep 5 and silently drop a full trading day."""
    ist_moment = dt.datetime(2025, 9, 5, 2, 0, tzinfo=IST)
    assert et_date(ist_moment) == dt.date(2025, 9, 4)
    assert ist_moment.astimezone(UTC).date() == dt.date(2025, 9, 4)

    later = dt.datetime(2025, 9, 5, 11, 0, tzinfo=IST)  # 01:30 ET on Sep 5
    assert et_date(later) == dt.date(2025, 9, 5)


# ---------------------------------------------------------------------------
# resolve_window
# ---------------------------------------------------------------------------


def _snap(ticker="AAPL", **kw):
    base = dict(
        ticker=ticker,
        last_seen_price=100.0,
        last_seen_bench=50.0,
        last_seen_bench_ticker="XLK",
        last_seen_at=dt.datetime(2025, 8, 27, 14, 3, tzinfo=ET),
    )
    base.update(kw)
    return Snapshot(**base)


def closes(mapping):
    def f(t, d):
        return mapping.get((t.upper(), d))

    return f


def test_same_session_recheck_is_finite_and_never_nan(cal):
    now = at(cal, ORDINARY, 11, 0)
    w = resolve_window(_snap(last_seen_at=at(cal, ORDINARY, 10, 3)), now, cal, "XLK", closes({}))
    assert w.n_days == 0
    assert w.anchor == "intraday"
    assert w.n_eff >= MIN_N_EFF
    assert w.n_eff == w.n_eff  # not NaN
    assert 0 < w.n_eff < 1.0
    assert w.ref_price == 100.0


def test_two_plus_day_window_anchors_to_a_close(cal):
    """Sigma is estimated from close-to-close returns, so an intraday anchor
    carries noise the denominator does not know about, biasing z upward."""
    seen = at(cal, dt.date(2025, 8, 26), 10, 3)
    now = at(cal, dt.date(2025, 8, 29), 15, 0)
    lookup = closes({("AAPL", dt.date(2025, 8, 26)): 111.0,
                     ("XLK", dt.date(2025, 8, 26)): 55.0})
    w = resolve_window(_snap(last_seen_at=seen), now, cal, "XLK", lookup)
    assert w.anchor == "close"
    assert w.ref_date == dt.date(2025, 8, 26)
    assert w.ref_price == 111.0          # the close, not last_seen_price 100.0
    assert w.ref_bench == 55.0
    assert "Tuesday's close" in w.since_label


def test_ninety_day_absence_caps_price_and_days_together(cal):
    """Capping n_days without moving the reference price inflates z by
    sqrt(actual/30). Both must move together."""
    now = at(cal, dt.date(2025, 8, 29), 16, 0)
    ref_day = cal.session_n_ago(MAX_WINDOW_DAYS, et_date(now))
    lookup = closes({("AAPL", ref_day): 222.0, ("XLK", ref_day): 77.0})
    seen = now - dt.timedelta(days=130)

    w = resolve_window(_snap(last_seen_at=seen), now, cal, "XLK", lookup)
    assert w.capped is True
    assert w.n_days == MAX_WINDOW_DAYS
    assert w.ref_date == ref_day
    assert w.ref_price == 222.0
    assert w.n_eff <= MAX_WINDOW_DAYS + 1.0


def test_benchmark_reassignment_mid_window_is_detected(cal):
    """Dividing two unrelated ETFs fabricates an excess return."""
    now = at(cal, ORDINARY, 15, 0)
    seen = at(cal, ORDINARY, 10, 0)
    w = resolve_window(
        _snap(last_seen_at=seen, last_seen_bench_ticker="XLY"), now, cal, "XLK", closes({})
    )
    assert w.bench_ticker == "XLK"
    assert any("benchmark" in n for n in w.notes)


def test_missing_reference_close_degrades_rather_than_lying(cal):
    seen = at(cal, dt.date(2025, 8, 26), 10, 0)
    now = at(cal, dt.date(2025, 8, 29), 15, 0)
    w = resolve_window(_snap(last_seen_at=seen), now, cal, "XLK", closes({}))
    assert w.anchor == "intraday"
    assert any("no stored close" in n for n in w.notes)
