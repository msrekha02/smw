"""Wire types. Pydantic v2."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Tier = Literal["critical", "notable", "minor", "quiet"]
CardState = Literal[
    "ok", "new", "seeding", "verifying", "no_data", "halted", "unknown", "action_frozen"
]


class LoginRequest(BaseModel):
    """Any email signs in. The only rule is that it has to be an address."""

    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def _shaped_like_an_email(cls, v: str) -> str:
        v = v.strip()
        local, _, domain = v.partition("@")
        if not local or not domain or "@" in domain or " " in v:
            raise ValueError("that does not look like an email address")
        return v


class TokenOut(BaseModel):
    user_id: uuid.UUID
    email: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(BaseModel):
    user_id: uuid.UUID
    email: str | None = None
    mode: str


class AuthMode(BaseModel):
    mode: Literal["dev", "supabase"]
    local_login: bool
    notice: str | None = None


class SymbolOut(BaseModel):
    ticker: str
    name: str | None = None
    exchange: str | None = None
    type: str | None = None
    already_watched: bool = False
    seeded: bool = False


class WatchlistAdd(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class WatchlistItemOut(BaseModel):
    ticker: str
    name: str | None = None
    sector: str | None = None
    benchmark_ticker: str | None = None
    instrument_class: str = "stock"
    status: str = "seeding"
    added_at: dt.datetime
    pinned_unread: bool = False


class AddResult(BaseModel):
    ticker: str
    status: str                      # active | seeding
    message: str
    seed_credits_left: int
    item: WatchlistItemOut | None = None


class Contribution(BaseModel):
    move: float
    path: float
    volume: float
    breach: float


class Decomposition(BaseModel):
    """Everything the panel needs to show its work."""

    cum_return: float
    bench_return: float
    bench_ticker: str | None
    beta_used: float
    beta_raw: float | None = None
    r2: float | None = None
    excess: float
    sigma_idio: float
    sigma_expected: float
    n_days: int
    n_eff: float
    z_move: float
    z_path: float
    z_path_on: str | None = None
    vol_score: float
    vol_ratio: float
    breach_score: float
    breach_direction: str | None = None
    contributions: Contribution
    weights: dict[str, float]
    # Cumulative excess return per elapsed session, for the expected-range cone.
    # Sliced by the scorer, not by the client.
    window_path: list[dict[str, Any]] = []
    earnings_days: list[dt.date] = []
    earnings_note: str | None = None


class Sparkline(BaseModel):
    points: list[float]
    dates: list[str]
    window_from_index: int | None = None


class Freshness(BaseModel):
    source: str
    age_s: float
    label: str
    stale: bool


class DigestCard(BaseModel):
    ticker: str
    name: str | None = None
    state: CardState = "ok"
    tier: Tier = "quiet"
    attention: float = 0.0
    direction: Literal["up", "down"] = "up"
    price: float | None = None
    reference_price: float | None = None
    change_pct: float | None = None
    excess_pct: float | None = None
    reason: str = ""
    since_label: str = ""
    confidence: Literal["ok", "reduced"] = "ok"
    confidence_reasons: list[str] = []
    freshness: Freshness | None = None
    extended_hours: dict[str, Any] | None = None
    sparkline: Sparkline | None = None
    decomposition: Decomposition | None = None
    action: dict[str, Any] | None = None
    observed_at: dt.datetime | None = None


class MarketState(BaseModel):
    ticker: str = "SPY"
    return_pct: float = 0.0
    z: float = 0.0
    elevated: bool = False
    banner: str | None = None
    session: Literal["open", "closed", "extended", "unknown"] = "unknown"


class DigestOut(BaseModel):
    as_of: dt.datetime
    since: dt.datetime | None
    since_label: str
    market: MarketState
    cards: list[DigestCard]
    quiet: list[DigestCard]
    quiet_summary: str | None = None
    counts: dict[str, int]
    token: str
    next_poll_after_ms: int
    bootstrap: dict[str, Any] | None = None
    notes: list[str] = []


class AckRequest(BaseModel):
    token: str
    tickers: list[str] | None = None       # None means every ticker in the token

    @field_validator("tickers")
    @classmethod
    def _upper(cls, v: list[str] | None) -> list[str] | None:
        return [t.strip().upper() for t in v] if v else v


class AckResponse(BaseModel):
    results: dict[str, Literal["applied", "superseded", "not_found"]]


class FeedbackIn(BaseModel):
    ticker: str
    tier: Tier
    attention: float
    shown_at: dt.datetime | None = None
    clicked_through: bool = False
    dismissed_fast: bool = False
    thumb: int | None = None

    @field_validator("thumb")
    @classmethod
    def _thumb(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v not in (-1, 1):
            raise ValueError("thumb must be -1 or 1")
        return v


class FeedbackBatch(BaseModel):
    events: list[FeedbackIn]


class ResidualHistogram(BaseModel):
    bins: int
    lo: float
    hi: float
    counts: list[int]
    under: int = 0
    over: int = 0
    n: int = 0
    sd: float = 0.0
    kurtosis: float = 0.0
    tail_3s: float = 0.0


class TickerDetail(BaseModel):
    ticker: str
    name: str | None
    sector: str | None
    instrument_class: str
    benchmark_ticker: str | None
    status: str
    beta_raw: float | None
    beta_used: float | None
    r2: float | None
    sigma_idio: float | None
    sample_days: int
    adv20: float | None
    wk52_high: float | None
    wk52_low: float | None
    last_bar_date: dt.date | None
    frozen_reason: str | None
    residual_hist: ResidualHistogram | None
    recent_daily: list[dict[str, Any]]
    earnings: list[dt.date]
    # The empirical distribution is DISPLAYED, never scored. Replacing the
    # Gaussian z with its ECDF is designed and deliberately not built.
    scoring_note: str = (
        "Residuals are shown for honesty about non-normality. Scoring uses the "
        "Gaussian z; ECDF scoring is designed and not built."
    )


class CalibrationOut(BaseModel):
    generated_at: dt.datetime
    universe: int
    sessions: int
    checks: int
    window_days: int
    watchlist_size: int
    thresholds: dict[str, float]
    predicted: dict[str, float]
    observed: dict[str, float]
    per_check_rates: dict[str, float]
    attention_histogram: dict[str, Any]
    residual_summary: dict[str, Any]
    # Absent on artifacts generated before the histogram existed; the page
    # drops the chart rather than failing to load.
    residual_histogram: dict[str, Any] | None = None
    precision_at_critical: dict[str, Any]
    notes: list[str] = []
