"""What counts as meaningful: the gates, the ranking, and the earnings sign."""
from __future__ import annotations

import datetime as dt
import math

import pytest

from api.calendar_ny import ET, get_calendar
from api.config import (
    EARNINGS_VOL_MULT,
    MATERIAL_MOVE,
    SIGMA_FLOOR,
    TIER_CRITICAL,
    TIER_NOTABLE,
)
from api.scoring import reasons, signals
from api.scoring.score import Baseline, PricePoint, score, tier_of
from api.scoring.window import Snapshot, resolve_window

ORDINARY = dt.date(2025, 8, 27)
PRIOR = dt.date(2025, 8, 26)


def at(d: dt.date, hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)


def build(
    *,
    price: float,
    ref: float,
    sigma: float = 0.016,
    beta: float = 1.0,
    bench_now: float = 100.0,
    bench_ref: float = 100.0,
    seen_at: dt.datetime | None = None,
    now: dt.datetime | None = None,
    recent: list | None = None,
    earnings: list | None = None,
    instrument_class: str = "stock",
    wk52_high: float | None = None,
    wk52_low: float | None = None,
):
    cal = get_calendar()
    now = now or at(ORDINARY, 16, 0)
    seen_at = seen_at or at(PRIOR, 16, 0)
    bench = None if instrument_class == "broad_etf" else "XLK"

    lookup = {
        ("T", PRIOR): ref,
        ("XLK", PRIOR): bench_ref,
        ("T", ORDINARY): price,
        ("XLK", ORDINARY): bench_now,
    }
    close_on = lambda t, d: lookup.get((t.upper(), d))  # noqa: E731

    base = Baseline(
        ticker="T",
        instrument_class=instrument_class,
        benchmark_ticker=bench,
        beta_used=beta,
        sigma_idio=sigma,
        recent_daily=recent if recent is not None else [],
        sample_days=1259,
        wk52_high=wk52_high,
        wk52_low=wk52_low,
    )
    snap = Snapshot("T", ref, bench_ref, bench or "XLK", seen_at)
    win = resolve_window(snap, now, cal, bench, close_on)
    latest = PricePoint(price=price, source="eod", bar_date=ORDINARY, at=now)
    bpp = (
        PricePoint(price=bench_now, source="eod", bar_date=ORDINARY, at=now)
        if bench
        else None
    )
    return score(
        base, latest, bpp, win, earnings or [], now, cal, bench_close_on=close_on
    )


def row(d: dt.date, exc: float, volr: float = 1.0, close: float = 100.0, **kw):
    r = {
        "d": d.isoformat(), "exc": exc, "volr": volr, "close": close,
        "high": close * 1.005, "low": close * 0.995,
        "hh": kw.get("hh"), "ll": kw.get("ll"),
    }
    return r


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def test_material_move_gate_blocks_a_tiny_early_session_move():
    """A 0.4% move twelve minutes into a session divides by a tiny sqrt(n_eff)
    and produces a spurious 4 sigma. Economic significance is a floor beneath
    statistical significance."""
    open_at = at(ORDINARY, 9, 30)
    ten_min = at(ORDINARY, 9, 40)
    # A genuinely low-vol name, which is where the spurious z actually appears:
    # MIN_N_EFF already caps the divisor at sigma * sqrt(0.05), so 0.4% only
    # reaches 4 sigma when sigma itself is near the floor.
    r = build(
        price=100.4, ref=100.0, sigma=0.005, beta=1.0,
        bench_now=100.0, bench_ref=100.0, seen_at=open_at, now=ten_min,
    )
    assert abs(r.excess) < MATERIAL_MOVE
    assert abs(r.z_move) > 3.0, "the raw z really is large; that is the point"
    assert r.gated is True
    assert r.tier == "minor"
    assert "too small to call" in reasons.build(r)


def test_min_n_eff_is_the_first_line_of_defence():
    """The dispersion floor alone already stops most early-session nonsense;
    the material-move gate is the second line, not the only one."""
    r = build(
        price=100.4, ref=100.0, sigma=0.016, beta=1.0,
        seen_at=at(ORDINARY, 9, 30), now=at(ORDINARY, 9, 40),
    )
    assert r.n_eff == pytest.approx(0.05)
    assert abs(r.z_move) < 1.5


def test_sigma_floor_keeps_a_quiet_utility_quiet():
    """A utility with a genuine 0.25%/day idiosyncratic sigma would score
    4 sigma on a 1% move and dominate every digest."""
    r = build(price=101.0, ref=100.0, sigma=0.0025, beta=0.0)
    assert r.sigma_expected >= SIGMA_FLOOR
    assert abs(r.z_move) < 3.0
    assert r.tier != "critical"


def test_a_real_single_name_move_is_critical():
    r = build(price=94.0, ref=100.0, sigma=0.016, beta=1.0)
    assert r.excess == pytest.approx(-0.06, abs=0.001)
    assert r.attention >= TIER_CRITICAL
    assert r.tier == "critical"
    assert r.direction == "down"


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_a_crash_outranks_a_small_gain():
    """Ranking a signed composite means a -5 sigma crash sorts below a +0.5
    sigma drift and never reaches the digest."""
    crash = build(price=92.0, ref=100.0, sigma=0.016, beta=0.0)
    drift = build(price=100.8, ref=100.0, sigma=0.016, beta=0.0)
    assert crash.z_move < -4.0
    assert 0 < drift.z_move < 1.0
    ranked = sorted([drift, crash], key=lambda r: -r.attention)
    assert ranked[0] is crash


# ---------------------------------------------------------------------------
# Earnings
# ---------------------------------------------------------------------------


def test_earnings_widens_sigma_and_lowers_the_score():
    """A 3 sigma move on a scheduled earnings day is LESS surprising than one on
    a random Tuesday, because everyone knew a catalyst was landing."""
    ordinary = build(price=96.0, ref=100.0, sigma=0.016, beta=0.0)
    on_earnings = build(
        price=96.0, ref=100.0, sigma=0.016, beta=0.0, earnings=[ORDINARY]
    )

    assert on_earnings.earnings_days == [ORDINARY]
    assert on_earnings.sigma_expected > ordinary.sigma_expected
    assert on_earnings.sigma_expected == pytest.approx(
        ordinary.sigma_expected * EARNINGS_VOL_MULT, rel=0.01
    )
    assert abs(on_earnings.z_move) < abs(ordinary.z_move)
    assert on_earnings.attention < ordinary.attention


def test_earnings_adds_no_score_of_its_own():
    """Variance is additive across days, so the correct treatment is in the
    denominator. An earlier version added a flat bonus, which double-counts."""
    flat = build(price=100.0, ref=100.0, sigma=0.016, beta=0.0, earnings=[ORDINARY])
    assert flat.attention == pytest.approx(0.0, abs=0.01)
    assert flat.tier == "quiet"


def test_expected_sigma_is_additive_in_variance():
    s = 0.02
    two_plain = signals.expected_sigma(s, 2.0, 0.0)
    assert two_plain == pytest.approx(s * math.sqrt(2.0))
    one_each = signals.expected_sigma(s, 2.0, 1.0)
    assert one_each == pytest.approx(s * math.sqrt(1.0 + EARNINGS_VOL_MULT**2))


# ---------------------------------------------------------------------------
# Instrument classes
# ---------------------------------------------------------------------------


def test_broad_etf_scores_against_itself():
    """SPY against SPY gives excess identically zero and can never alert."""
    r = build(price=95.0, ref=100.0, sigma=0.011, instrument_class="broad_etf")
    assert r.beta_used == 0.0
    assert r.excess == pytest.approx(-0.05, abs=1e-6)
    assert r.tier == "critical"


def test_sector_move_is_removed_from_a_stock():
    """The whole promise: net of what its sector did."""
    with_sector = build(
        price=94.0, ref=100.0, sigma=0.016, beta=1.0,
        bench_ref=100.0, bench_now=94.0,
    )
    assert with_sector.excess == pytest.approx(0.0, abs=0.002)
    assert with_sector.tier == "quiet"
    assert "inside its normal range" in reasons.build(with_sector)


def test_missing_benchmark_reduces_confidence_rather_than_guessing():
    """A silent beta substitution is the likeliest source of a confident false
    critical."""
    cal = get_calendar()
    now = at(ORDINARY, 16, 0)
    base = Baseline(ticker="T", benchmark_ticker="XLK", beta_used=2.1,
                    sigma_idio=0.016, sample_days=1259)
    snap = Snapshot("T", 100.0, 0.0, "XLK", at(PRIOR, 16, 0))
    win = resolve_window(snap, now, cal, "XLK", lambda t, d: 100.0 if t == "T" else None)
    r = score(base, PricePoint(97.0, "ws", at=now), None, win, [], now, cal)
    assert r.beta_used == 0.0
    assert r.confidence == "reduced"
    assert any("benchmark" in x for x in r.confidence_reasons)


# ---------------------------------------------------------------------------
# Path, volume, breach
# ---------------------------------------------------------------------------


def test_z_path_catches_a_round_trip_that_z_move_misses():
    """A stock that spiked 12% and round-tripped to flat scores zero on
    z_move. For someone away a week that is a total miss of a real event."""
    days = [dt.date(2025, 8, 21), dt.date(2025, 8, 22), dt.date(2025, 8, 25),
            dt.date(2025, 8, 26), ORDINARY]
    recent = [row(days[0], 0.121, 3.4), row(days[1], -0.035),
              row(days[2], -0.028), row(days[3], -0.030), row(days[4], -0.022)]
    r = build(
        price=100.0, ref=100.0, sigma=0.023, beta=0.0,
        seen_at=at(dt.date(2025, 8, 20), 16, 0), recent=recent,
    )
    assert abs(r.z_move) < 0.5
    assert r.z_path > 5.0
    # The endpoint move is ~zero, so an endpoint-only material gate would
    # silence exactly the card z_path exists to produce.
    assert r.gated is False
    assert r.tier in ("critical", "notable")
    assert r.contributions["path"] > r.contributions["move"]
    assert "gave it back" in reasons.build(r)


def test_volume_score_is_log2_of_the_peak_ratio():
    s, ratio = signals.vol_score([row(ORDINARY, 0.0, volr=8.0)])
    assert ratio == 8.0
    assert s == pytest.approx(3.0)
    s2, _ = signals.vol_score([row(ORDINARY, 0.0, volr=1.0)])
    assert s2 == 0.0


def test_breach_uses_the_record_the_window_inherited():
    """A window that opens on day D must be measured against the record D
    inherited, not one D itself set."""
    win = [row(ORDINARY, 0.0, close=110.0, hh=100.0, ll=80.0)]
    b = signals.breach_score(win, None, None, 0.02)
    assert b.direction == "high"
    assert b.score > 1.0
    assert b.distance > 0.10

    inside = signals.breach_score(
        [row(ORDINARY, 0.0, close=95.0, hh=120.0, ll=80.0)], None, None, 0.02
    )
    assert inside.score == 0.0
    assert inside.direction is None


def test_window_days_excludes_sessions_the_user_already_saw():
    """Passing the whole 30-row history unfiltered makes z_path report the
    largest move of the last six weeks as if it happened while they were away."""
    cal = get_calendar()
    recent = [row(dt.date(2025, 8, 20), 0.12), row(ORDINARY, 0.001)]
    inside = signals.window_days(recent, at(PRIOR, 16, 0), at(ORDINARY, 16, 0), cal)
    assert [d["d"] for d in inside] == [ORDINARY.isoformat()]


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------


def test_tier_boundaries():
    assert tier_of(TIER_CRITICAL) == "critical"
    assert tier_of(TIER_CRITICAL - 0.001) == "notable"
    assert tier_of(TIER_NOTABLE) == "notable"
    assert tier_of(0.0) == "quiet"


def test_contributions_sum_to_attention():
    r = build(price=94.0, ref=100.0, sigma=0.016, beta=0.0)
    assert sum(r.contributions.values()) == pytest.approx(r.attention)
