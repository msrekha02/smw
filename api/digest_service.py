"""Building a digest.

One SQL join plus a vectorised pass over at most 100 rows. Expensive work is
keyed by ticker and already done by the worker; the read path does no writes and
no provider calls it can avoid, which is what keeps p50 in the tens of
milliseconds and makes the cost O(list size) rather than O(users x tickers).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import clock, digest_token
from api.calendar_ny import ET, TradingCalendar, et_date, get_calendar
from api.config import (
    BASELINE_STALE_SESSIONS,
    DEFAULT_BENCHMARK,
    MAX_WINDOW_DAYS,
    POLL_MS_CLOSED,
    POLL_MS_OPEN,
    QUIET_SUMMARY_N,
    REGIME_SIGMA,
    SIGMA_FLOOR,
    SPY_MIN_BARS,
    STALE_AFTER_S,
    W_BREACH,
    W_MOVE,
    W_PATH,
    W_VOL,
)
from api.scoring import reasons
from api.scoring.score import Baseline, PricePoint, ScoreResult, score
from api.scoring.window import Snapshot, resolve_window
from api.schemas import (
    Contribution,
    Decomposition,
    DigestCard,
    DigestOut,
    Freshness,
    MarketState,
    Sparkline,
)

log = logging.getLogger("smw.digest")

ROW_SQL = """
SELECT w.ticker,
       t.name, t.sector, t.instrument_class, t.benchmark_ticker, t.status,
       w.added_at, w.pinned_unread,
       b.beta_used, b.beta_raw, b.r2, b.sigma_idio, b.adv20,
       b.wk52_high, b.wk52_low, b.recent_daily, b.sample_days,
       b.last_bar_date, b.frozen_reason,
       l.price, l.prev_close, l.source, l.fetched_at, l.bar_date,
       l.extended_price, l.is_extended_hours, l.status AS live_status,
       s.last_seen_price, s.last_seen_bench, s.last_seen_bench_ticker,
       s.last_seen_at, s.is_initial
  FROM watchlist_items w
  JOIN tickers t              ON t.ticker = w.ticker
  LEFT JOIN ticker_baseline b ON b.ticker = w.ticker
  LEFT JOIN ticker_latest l   ON l.ticker = w.ticker
  LEFT JOIN watchlist_snapshots s
         ON s.user_id = w.user_id AND s.ticker = w.ticker
 WHERE w.user_id = :uid
"""


@dataclass
class Row:
    d: dict[str, Any]

    def __getattr__(self, k: str) -> Any:
        return self.d.get(k)


def _freshness(
    source: str | None, fetched_at: dt.datetime | None, now: dt.datetime
) -> Freshness | None:
    """Age is measured against the system clock, not against SQL `now()`.

    The replay providers move the whole system onto a fixture date; a database
    `now()` does not follow, and every price would read as years stale.
    """
    if source is None:
        return None
    age = (now - fetched_at).total_seconds() if fetched_at else 0.0
    age = max(age, 0.0)
    limit = STALE_AFTER_S.get(source, 86400)
    stale = age > limit
    if source == "eod":
        label = "at the close"
    elif age < 15:
        label = "live"
    elif age < 90:
        label = "~1 min"
    elif age < 3600:
        label = f"~{int(age // 60)} min"
    else:
        label = f"~{int(age // 3600)} h"
    return Freshness(source=source, age_s=round(age, 1), label=label, stale=stale)


async def _closes(
    session: AsyncSession, pairs: set[tuple[str, dt.date]]
) -> dict[tuple[str, dt.date], float]:
    if not pairs:
        return {}
    tickers = sorted({t for t, _ in pairs})
    dates = sorted({d for _, d in pairs})
    rows = (
        await session.execute(
            text(
                "SELECT ticker, bar_date, close FROM ticker_daily_bar"
                " WHERE ticker = ANY(:ts) AND bar_date = ANY(:ds)"
            ),
            {"ts": tickers, "ds": dates},
        )
    ).all()
    return {(r[0], r[1]): float(r[2]) for r in rows}


async def _earnings(
    session: AsyncSession, tickers: list[str], since: dt.date
) -> dict[str, list[dt.date]]:
    if not tickers:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT ticker, event_date FROM earnings_dates"
                " WHERE ticker = ANY(:ts) AND event_date >= :since"
            ),
            {"ts": tickers, "since": since},
        )
    ).all()
    out: dict[str, list[dt.date]] = {}
    for t, d in rows:
        out.setdefault(t, []).append(d)
    return out


async def bootstrap_state(session: AsyncSession) -> dict[str, Any] | None:
    """A fresh deploy has no SPY bars, so `trading_days_between` returns 0 for
    every window and the whole system silently reports same-session scoring on
    multi-day windows. Benchmarks seed first and scored digests are withheld
    until SPY has enough history to anchor them."""
    n = (
        await session.execute(
            text("SELECT count(*) FROM ticker_daily_bar WHERE ticker = :t"),
            {"t": DEFAULT_BENCHMARK},
        )
    ).scalar_one()
    if int(n) >= SPY_MIN_BARS:
        return None
    return {
        "ready": False,
        "spy_bars": int(n),
        "spy_bars_required": SPY_MIN_BARS,
        "message": (
            "Benchmarks are still seeding. Scores are withheld until SPY has a "
            "full year of history, because without it every window would "
            "silently measure as a single session."
        ),
    }


async def market_state(
    session: AsyncSession, cal: TradingCalendar, now: dt.datetime
) -> MarketState:
    row = (
        await session.execute(
            text(
                """
        SELECT l.price, l.prev_close, l.source, l.bar_date, b.sigma_idio
          FROM ticker_latest l
          LEFT JOIN ticker_baseline b ON b.ticker = l.ticker
         WHERE l.ticker = :t
        """
            ),
            {"t": DEFAULT_BENCHMARK},
        )
    ).first()
    session_label = "open" if cal.is_open(now) else "closed"
    if row is None or not row[0]:
        return MarketState(session=session_label)

    price, prev_close, source, bar_date, sigma = row
    if not prev_close:
        d = bar_date or cal.current_or_last_session(now)
        prev = (
            await session.execute(
                text(
                    "SELECT close FROM ticker_daily_bar WHERE ticker=:t"
                    " AND bar_date < :d ORDER BY bar_date DESC LIMIT 1"
                ),
                {"t": DEFAULT_BENCHMARK, "d": d},
            )
        ).scalar()
        prev_close = float(prev) if prev else None
    if not prev_close:
        return MarketState(session=session_label)

    ret = float(price) / float(prev_close) - 1.0
    s = max(float(sigma or SIGMA_FLOOR), SIGMA_FLOOR)
    if source == "eod":
        n_eff = 1.0
    else:
        n_eff = max(cal.session_fraction_elapsed(now), 0.05)
    z = ret / (s * (n_eff**0.5))
    elevated = abs(z) >= REGIME_SIGMA
    return MarketState(
        ticker=DEFAULT_BENCHMARK,
        return_pct=ret,
        z=z,
        elevated=elevated,
        banner=reasons.market_banner(z, ret) if elevated else None,
        session=session_label,
    )


def _sparkline(recent: list[dict], ref_date: dt.date | None) -> Sparkline | None:
    if not recent:
        return None
    pts = [float(d.get("close", 0.0)) for d in recent]
    dates = [str(d.get("d")) for d in recent]
    idx = None
    if ref_date:
        iso = ref_date.isoformat()
        for i, ds in enumerate(dates):
            if ds > iso:
                idx = i
                break
    return Sparkline(points=pts, dates=dates, window_from_index=idx)


def _decomposition(r: ScoreResult, row: Row) -> Decomposition:
    c = r.contributions
    note = None
    if r.earnings_days:
        note = (
            "Earnings in the window widened the expected range "
            f"({len(r.earnings_days)} session(s) at 2x sigma). It adds no score: "
            "a large move on a scheduled catalyst is less surprising, not more."
        )
    return Decomposition(
        cum_return=r.cum_return,
        bench_return=r.bench_return,
        bench_ticker=r.window.bench_ticker,
        beta_used=r.beta_used,
        beta_raw=row.beta_raw,
        r2=row.r2,
        excess=r.excess,
        sigma_idio=max(float(row.sigma_idio or SIGMA_FLOOR), SIGMA_FLOOR),
        sigma_expected=r.sigma_expected,
        n_days=r.n_days,
        n_eff=round(r.n_eff, 4),
        z_move=r.z_move,
        z_path=r.z_path,
        z_path_on=r.z_path_on,
        vol_score=r.vol_score,
        vol_ratio=r.vol_ratio,
        breach_score=r.breach.score,
        breach_direction=r.breach.direction,
        contributions=Contribution(**c),
        weights={"move": W_MOVE, "path": W_PATH, "volume": W_VOL, "breach": W_BREACH},
        window_path=r.window_path,
        earnings_days=r.earnings_days,
        earnings_note=note,
    )


def _card_state(row: Row, has_score: bool) -> str:
    if row.frozen_reason:
        return "action_frozen"
    if row.status == "halted":
        return "halted"
    if row.status == "unknown":
        return "unknown"
    if row.status == "seeding" or row.sigma_idio is None:
        return "seeding"
    if row.live_status == "verifying":
        return "verifying"
    if row.price is None or row.live_status == "no_data":
        return "no_data"
    if row.is_initial:
        return "new"
    return "ok" if has_score else "no_data"


async def build_digest(
    session: AsyncSession,
    user_id: uuid.UUID,
    as_if_last_seen: dt.datetime | None = None,
    include_decomposition: bool = True,
) -> DigestOut:
    cal = get_calendar()
    now = clock.now()
    today = et_date(now)

    rows = [
        Row(dict(m)) for m in (await session.execute(text(ROW_SQL), {"uid": user_id})).mappings()
    ]
    boot = await bootstrap_state(session)
    market = await market_state(session, cal, now)

    # --- reference closes, one round trip -------------------------------
    pairs: set[tuple[str, dt.date]] = set()
    for r in rows:
        bench = r.benchmark_ticker
        seen_at = as_if_last_seen or r.last_seen_at
        if seen_at is None:
            continue
        cand = {
            cal.session_on_or_before(et_date(seen_at)),
            cal.session_n_ago(MAX_WINDOW_DAYS, today),
        }
        if r.bar_date:
            cand.add(r.bar_date)
        for d in cand:
            pairs.add((r.ticker, d))
            if bench:
                pairs.add((bench, d))
    closes = await _closes(session, pairs)

    def close_on(ticker: str, d: dt.date) -> float | None:
        return closes.get((ticker.upper(), d))

    earliest = cal.session_n_ago(MAX_WINDOW_DAYS + 5, today)
    earn = await _earnings(session, [r.ticker for r in rows], earliest)

    # --- score ----------------------------------------------------------
    cards: list[DigestCard] = []
    observed: dict[str, digest_token.Observed] = {}
    scored: list[tuple[DigestCard, ScoreResult]] = []
    notes: list[str] = []

    for r in rows:
        card = DigestCard(ticker=r.ticker, name=r.name)
        state = _card_state(r, has_score=True)

        if boot is not None:
            card.state = "seeding"
            card.reason = boot["message"]
            cards.append(card)
            continue

        if state in ("seeding", "halted", "unknown", "no_data", "action_frozen"):
            card.state = state
            card.price = r.price
            card.freshness = _freshness(r.source, r.fetched_at, now)
            card.reason = _state_reason(state, r)
            if state == "action_frozen":
                card.action = {
                    "kind": "corporate_action",
                    "message": r.frozen_reason,
                    "cta": "Remove and re-add to reset your reference price.",
                }
            cards.append(card)
            continue

        seen_at = as_if_last_seen or r.last_seen_at
        if seen_at is None or r.price is None:
            card.state = "new" if r.price is not None else "no_data"
            card.price = r.price
            card.freshness = _freshness(r.source, r.fetched_at, now)
            card.reason = "Added to your watchlist. The next visit is measured from here."
            cards.append(card)
            if r.price is not None and r.benchmark_ticker:
                observed[r.ticker] = digest_token.Observed(
                    px=float(r.price),
                    bench=float(closes.get((r.benchmark_ticker, r.bar_date or today), 0.0) or 0.0),
                    bt=r.benchmark_ticker,
                    at=r.fetched_at or now,
                )
            continue

        base = Baseline(
            ticker=r.ticker,
            instrument_class=r.instrument_class or "stock",
            benchmark_ticker=r.benchmark_ticker,
            beta_used=float(r.beta_used if r.beta_used is not None else 1.0),
            beta_raw=float(r.beta_raw or 0.0),
            r2=float(r.r2 or 0.0),
            sigma_idio=float(r.sigma_idio or SIGMA_FLOOR),
            adv20=r.adv20,
            wk52_high=r.wk52_high,
            wk52_low=r.wk52_low,
            recent_daily=list(r.recent_daily or []),
            sample_days=int(r.sample_days or 0),
            last_bar_date=r.last_bar_date,
            frozen_reason=r.frozen_reason,
        )

        snap = Snapshot(
            ticker=r.ticker,
            last_seen_price=float(r.last_seen_price if r.last_seen_price else r.price),
            last_seen_bench=float(r.last_seen_bench or 0.0),
            last_seen_bench_ticker=r.last_seen_bench_ticker or (r.benchmark_ticker or DEFAULT_BENCHMARK),
            last_seen_at=seen_at,
            is_initial=bool(r.is_initial),
        )
        win = resolve_window(snap, now, cal, r.benchmark_ticker, close_on)

        fresh = _freshness(r.source, r.fetched_at, now)
        latest = PricePoint(
            price=float(r.price),
            source=r.source or "eod",
            bar_date=r.bar_date,
            at=r.fetched_at,
            stale=bool(fresh and fresh.stale),
        )
        bench_pp = None
        bench_px_now = None
        if r.benchmark_ticker:
            brow = next((x for x in rows if x.ticker == r.benchmark_ticker), None)
            if brow is not None and brow.price:
                bench_px_now = float(brow.price)
                bench_pp = PricePoint(
                    price=bench_px_now, source=brow.source or "eod",
                    bar_date=brow.bar_date, at=brow.fetched_at,
                )
            else:
                bench_px_now = await _bench_price(session, r.benchmark_ticker)
                if bench_px_now:
                    bench_pp = PricePoint(price=bench_px_now, source="rest", at=now)

        res = score(
            base, latest, bench_pp, win, earn.get(r.ticker, []), now, cal,
            bench_close_on=close_on,
        )

        # A baseline more than two sessions behind is reported, never silent:
        # silent staleness is the worst failure available to a product whose
        # promise is a trustworthy diff.
        if r.last_bar_date:
            behind = len(cal.sessions_in_range(r.last_bar_date, today)) - 1
            if behind > BASELINE_STALE_SESSIONS:
                res.confidence = "reduced"
                res.confidence_reasons.append(
                    f"baseline last updated {_md(r.last_bar_date)}"
                )

        card.state = "ok"
        card.tier = res.tier
        card.attention = round(res.attention, 4)
        card.direction = res.direction
        card.price = float(r.price)
        card.reference_price = win.ref_price
        card.change_pct = res.cum_return
        card.excess_pct = res.excess
        card.since_label = win.since_label
        card.reason = reasons.build(res)
        card.confidence = res.confidence
        card.confidence_reasons = res.confidence_reasons
        card.freshness = fresh
        card.observed_at = r.fetched_at or now
        if r.is_extended_hours and r.extended_price:
            ext_ret = float(r.extended_price) / float(r.price) - 1.0
            card.extended_hours = {
                "price": float(r.extended_price),
                "change_pct": ext_ret,
                "label": f"AH {ext_ret * 100:+.1f}% - not scored until the open",
            }
        # The shading marks where the WINDOW began, which exists even when the
        # anchor is an intraday price and `ref_date` is therefore null.
        card.sparkline = _sparkline(base.recent_daily, win.ref_date or et_date(win.ref_at))
        if include_decomposition:
            card.decomposition = _decomposition(res, r)

        cards.append(card)
        scored.append((card, res))
        observed[r.ticker] = digest_token.Observed(
            px=float(r.price),
            bench=float(bench_px_now or win.ref_bench or 0.0),
            bt=win.bench_ticker,
            at=r.fetched_at or now,
        )

    # Rank on attention, which is ABSOLUTE. Ranking a signed score means a
    # -5 sigma crash sorts below a +0.5 sigma drift and never appears.
    scored.sort(key=lambda p: -p[1].attention)
    ranked = [c for c, _ in scored]
    loud = [c for c in ranked if c.tier in ("critical", "notable")]
    minor = [c for c in ranked if c.tier == "minor"]
    quiet = [c for c in ranked if c.tier == "quiet"]
    other = [c for c in cards if c.state != "ok"]

    quiet_line = None
    if not loud and scored:
        # Absence of signal is reported as a finding, not a blank screen.
        top = [res for _, res in scored[:QUIET_SUMMARY_N]]
        quiet_line = reasons.quiet_summary(top)
        loud = ranked[:QUIET_SUMMARY_N]
        minor = [c for c in minor if c not in loud]
        quiet = [c for c in quiet if c not in loud]

    since = None if as_if_last_seen else _earliest_seen(rows)
    since_label = _since_label(cal, as_if_last_seen or since, now)

    token = digest_token.issue(user_id, observed, now)
    poll_ms = POLL_MS_OPEN if cal.is_open(now) else POLL_MS_CLOSED

    if boot is not None:
        notes.append(boot["message"])

    return DigestOut(
        as_of=now,
        since=as_if_last_seen or since,
        since_label=since_label,
        market=market,
        cards=loud + other,
        quiet=minor + quiet,
        quiet_summary=quiet_line,
        counts={
            "total": len(cards),
            "critical": sum(1 for c in ranked if c.tier == "critical"),
            "notable": sum(1 for c in ranked if c.tier == "notable"),
            "minor": sum(1 for c in ranked if c.tier == "minor"),
            "quiet": sum(1 for c in ranked if c.tier == "quiet"),
            "unscored": len(other),
        },
        token=token,
        next_poll_after_ms=poll_ms,
        bootstrap=boot,
        notes=notes,
    )


async def _bench_price(session: AsyncSession, ticker: str) -> float | None:
    v = (
        await session.execute(
            text("SELECT price FROM ticker_latest WHERE ticker = :t"), {"t": ticker}
        )
    ).scalar()
    return float(v) if v is not None else None


def _state_reason(state: str, r: Row) -> str:
    return {
        "seeding": "Building this ticker's baseline. Scoreable tomorrow.",
        "halted": "No recent trades. Trading appears halted.",
        "unknown": "This symbol no longer resolves with the data provider.",
        "no_data": "No usable price right now.",
        "action_frozen": r.frozen_reason or "Scores paused after a history restatement.",
        "verifying": "Holding an implausible print for one cycle.",
    }.get(state, "")


def _md(d) -> str:
    """`%-d` and `%-I` are glibc extensions and raise on Windows."""
    return f"{d:%b} {d.day}"


def _hm(t: dt.datetime) -> str:
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _earliest_seen(rows: list[Row]) -> dt.datetime | None:
    seen = [r.last_seen_at for r in rows if r.last_seen_at]
    return min(seen) if seen else None


def _since_label(cal: TradingCalendar, since: dt.datetime | None, now: dt.datetime) -> str:
    if since is None:
        return "Since you added these"
    local = since.astimezone(ET)
    n = cal.sessions_between(since, now)
    same_day = local.date() == et_date(now)

    # `sessions_between` counts closes crossed, which is zero both for a recheck
    # an hour later AND for a Friday-evening checkpoint viewed mid-session on
    # Monday. Only the calendar date can tell those apart, and calling the
    # second one "today" is simply wrong.
    if same_day:
        return f"Since {_hm(local)} today"
    if n <= 1:
        at_close = local.hour >= 16
        return f"Since {local:%A}" + ("'s close" if at_close else "")
    return f"Since {_md(local)} - {n} trading days"


def etag_for(payload: str) -> str:
    return '"' + hashlib.sha256(payload.encode()).hexdigest()[:32] + '"'


def stable_body(d: DigestOut) -> str:
    """The ETag must ignore fields that change on every request but mean
    nothing: the token is freshly signed each time and `as_of` ticks every
    second, so hashing the raw response would make 304 unreachable."""
    data = json.loads(d.model_dump_json())
    data.pop("token", None)
    data.pop("as_of", None)
    data.pop("next_poll_after_ms", None)
    for group in ("cards", "quiet"):
        for c in data.get(group) or []:
            c.pop("observed_at", None)
            if c.get("freshness"):
                c["freshness"].pop("age_s", None)
                c["freshness"].pop("label", None)
    return json.dumps(data, sort_keys=True, separators=(",", ":"))
