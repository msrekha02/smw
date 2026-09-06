"""The three demo fixtures, scored through the production scorer.

These are the claims the product is making, so they are asserted rather than
described: a market-wide selloff must produce a banner and no criticals, a
single-name move must produce exactly one, and a round trip must be caught by
z_path at roughly zero net return.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from collections import Counter

import pytest

from api.calendar_ny import get_calendar
from api.config import FINNHUB_BUDGET_PER_MIN, REGIME_SIGMA, TD_RESERVED, TD_SEEDING
from api.scoring import reasons
from scripts import offline

FIX = pathlib.Path(__file__).resolve().parent.parent / "fixtures"

WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "AMD", "AVGO", "INTC", "META", "GOOGL", "NFLX", "DIS",
    "JPM", "BAC", "XOM", "CVX", "JNJ", "LLY", "CAT", "BA", "PG", "KO",
    "WMT", "DUK", "AMZN", "TSLA", "HD",
]


def scenario(name: str) -> dict:
    return json.loads((FIX / "scenarios" / f"{name}.json").read_text(encoding="utf-8"))


def run(name: str, tickers=None):
    tickers = tickers or WATCHLIST
    j = scenario(name)
    as_of = dt.date.fromisoformat(j["as_of"])
    last_seen = dt.datetime.fromisoformat(j["as_if_last_seen"])
    cal = get_calendar()
    book = offline.build_book(list(tickers), as_of, name)
    now = cal.bounds(as_of).close_utc
    rows = [r for r in (offline.score_at(book, t, last_seen, now) for t in tickers) if r]
    rows.sort(key=lambda r: -r.attention)
    return rows, book, as_of


def tiers(rows) -> Counter:
    return Counter(r.tier for r in rows)


# ---------------------------------------------------------------------------


def test_market_wide_selloff_produces_a_banner_and_no_stock_criticals():
    """The naive watchlist shows twenty red rows. The digest shows one banner."""
    rows, book, as_of = run("market_crash", WATCHLIST + ["SPY"])

    every_row_is_red = sum(1 for r in rows if r.cum_return < -0.02)
    assert every_row_is_red >= 20, "the selloff really did hit everything"

    stocks = [r for r in rows if r.ticker not in ("SPY", "QQQ", "IWM")]
    assert tiers(stocks)["critical"] == 0, (
        "no individual stock is unusual FOR ITSELF on a market-wide day: "
        f"{[(r.ticker, round(r.attention, 2)) for r in stocks[:5]]}"
    )

    # The regime banner is what carries the day, and it can only fire because
    # SPY is a broad_etf benchmarked against nothing. SPY against SPY would give
    # excess identically zero and the banner would be dead code.
    spy = offline.score_at(
        book, "SPY", dt.datetime.fromisoformat(scenario("market_crash")["as_if_last_seen"]),
        get_calendar().bounds(as_of).close_utc,
    )
    assert spy.beta_used == 0.0
    assert abs(spy.z_move) >= REGIME_SIGMA
    assert spy.cum_return < -0.04


def test_single_name_selloff_on_a_flat_sector_is_critical():
    rows, _, _ = run("single_name")
    crit = [r for r in rows if r.tier == "critical"]
    assert [r.ticker for r in crit] == ["NVDA"]

    nvda = crit[0]
    assert nvda.cum_return < -0.055
    assert abs(nvda.bench_return) < 0.01
    assert nvda.z_move < -3.0
    assert nvda.direction == "down"
    text = reasons.build(nvda)
    assert "tech was flat" in text
    assert "sigma" in text


def test_spike_and_revert_is_caught_by_path_at_zero_net_return():
    """z_move compares two endpoints, so a stock that spiked and round-tripped
    scores zero. For someone away a week that is a total miss of a real event."""
    rows, _, _ = run("spike_revert")
    amd = next(r for r in rows if r.ticker == "AMD")

    assert abs(amd.cum_return) < 0.02, "net return really is ~flat"
    assert abs(amd.z_move) < 1.0, "the endpoint diff sees nothing"
    assert amd.z_path > 5.0, "the path sees the week"
    assert amd.tier == "critical"
    assert amd.gated is False
    assert amd.contributions["path"] > amd.contributions["move"]
    assert rows[0].ticker == "AMD", "and it ranks first"
    assert "gave it back" in reasons.build(amd)


def test_the_ordinary_day_is_mostly_quiet():
    """A watchlist that gets quieter as it gets smarter.

    The bar is deliberately "most of the list says nothing", not "the list is
    silent": this fixture is a genuine one-sigma session with two events
    injected into it, and the measured alert rate lives on /calibration rather
    than in a threshold chosen to flatter a demo.
    """
    rows, _, _ = run("baseline")
    t = tiers(rows)
    calm = t["minor"] + t["quiet"]
    assert calm > len(rows) / 2, f"too noisy on an ordinary day: {dict(t)}"
    assert t["critical"] <= 4, f"too many criticals: {dict(t)}"
    assert t["critical"] >= 1, "and not so quiet that nothing ever surfaces"
    # The two deliberately injected events are the two loudest cards.
    assert {rows[0].ticker, rows[1].ticker} == {"BA", "META"}


def test_no_scenario_ever_produces_nan_or_infinity():
    for name in ("market_crash", "single_name", "spike_revert", "baseline"):
        rows, _, _ = run(name, WATCHLIST[:12])
        for r in rows:
            for v in (r.attention, r.z_move, r.z_path, r.excess, r.sigma_expected):
                assert v == v, f"{name}/{r.ticker}: NaN"
                assert abs(v) != float("inf"), f"{name}/{r.ticker}: infinite"
            assert r.sigma_expected > 0
            assert reasons.build(r).endswith(".")


def test_a_simulated_day_stays_inside_the_provider_budgets():
    """Cost is O(distinct tickers being viewed), never O(users x tickers)."""
    from api.config import BENCHMARK_UNIVERSE, QUOTE_CACHE_TTL_S, WS_SYMBOL_CAP

    distinct_viewed = len(WATCHLIST)
    hot = min(distinct_viewed, WS_SYMBOL_CAP)
    cold = max(distinct_viewed - hot, 0)

    # Benchmarks poll unconditionally; cold-tier symbols cost one call per TTL
    # no matter how many watchlists they appear on.
    per_min = len(BENCHMARK_UNIVERSE) * (60 / QUOTE_CACHE_TTL_S) + cold * (
        60 / QUOTE_CACHE_TTL_S
    )
    assert per_min <= FINNHUB_BUDGET_PER_MIN, f"{per_min}/min exceeds the budget"

    # One credit per ticker per night, and the seeding partition is separate.
    nightly_credits = distinct_viewed + len(BENCHMARK_UNIVERSE)
    assert nightly_credits <= TD_RESERVED
    assert TD_SEEDING > 0


@pytest.mark.parametrize("name", ["market_crash", "single_name", "spike_revert", "baseline"])
def test_scenarios_are_deterministic(name):
    a, _, _ = run(name, WATCHLIST[:8])
    b, _, _ = run(name, WATCHLIST[:8])
    assert [(r.ticker, round(r.attention, 9)) for r in a] == [
        (r.ticker, round(r.attention, 9)) for r in b
    ]
