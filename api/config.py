"""All tunable constants for the system. Env-driven where deployment needs it.

Nothing here is stored in the database (no `scoring_config` table). Constants
that change scoring behaviour live in code so a scoring change is a deploy, is
reviewable, and is reproducible by `scripts/calibrate.py`.
"""
from __future__ import annotations

import os
from typing import Final

# --------------------------------------------------------------------------
# Baseline estimator
# --------------------------------------------------------------------------
LAMBDA_VOL: Final = 0.94       # 11-day half-life (RiskMetrics); vol regimes shift fast
LAMBDA_BETA: Final = 0.98      # 34-day half-life; beta is structural

SEED_BARS: Final = 1260        # ~5 trading years; 1 TD credit regardless of count
SEED_SAMPLE_BARS: Final = 250  # plain-sample seed removes EWMA init bias

SIGMA_FLOOR: Final = 0.004     # 0.4%/day; below this a 1% move fabricates a 4-sigma
SIGMA_PRIOR: Final = 0.016     # 1.6%/day shrinkage target for young baselines
WINSOR_MAD_MULT: Final = 5.0
BETA_CLIP: Final = (0.0, 3.0)
BETA_SHRINK_K: Final = 60
SIGMA_SHRINK_K: Final = 40
EARNINGS_VOL_MULT: Final = 2.0
MAD_WINDOW: Final = 120        # trailing window for sigma_mad

# --------------------------------------------------------------------------
# Composite scoring
# --------------------------------------------------------------------------
W_MOVE: Final = 1.00
W_PATH: Final = 0.45
W_VOL: Final = 0.35
W_BREACH: Final = 0.40

TIER_CRITICAL: Final = 3.00
TIER_NOTABLE: Final = 1.75
TIER_MINOR: Final = 0.90

MATERIAL_MOVE: Final = 0.005   # economic-significance floor beneath the statistical one
MAX_WINDOW_DAYS: Final = 30
MIN_N_EFF: Final = 0.05
Z_CLAMP: Final = 6.0
REGIME_SIGMA: Final = 1.5      # SPY |z| above this shows the market banner
QUIET_SUMMARY_N: Final = 3

# --------------------------------------------------------------------------
# Live layer
# --------------------------------------------------------------------------
WS_SYMBOL_CAP: Final = 50
QUOTE_CACHE_TTL_S: Final = 60
BENCHMARK_POLL_S: Final = 60
FINNHUB_BUDGET_PER_MIN: Final = 45
WS_FLUSH_S: Final = 5
WS_HEARTBEAT_S: Final = 10
WS_RECONNECT_MIN_S: Final = 1.0
WS_RECONNECT_MAX_S: Final = 30.0
SANITY_JUMP: Final = 0.20      # |delta| vs both last-good and prev-close
SANITY_HOLD_CYCLES: Final = 3
SINGLE_FLIGHT_LOCK_S: Final = 10
SINGLE_FLIGHT_WAIT_S: Final = 2.0

# --------------------------------------------------------------------------
# Quota partitions (Twelve Data free tier: 800 credits/day, 8/min)
# The reserve is unreachable from any user-triggered code path.
# --------------------------------------------------------------------------
TD_RESERVED: Final = 640       # nightly baselines
TD_SEEDING: Final = 120        # new tickers, global queue
TD_CATALOG: Final = 40         # symbol catalog + market state + slack
TD_PER_MIN: Final = 8
SEED_CREDITS_PER_USER_PER_DAY: Final = 20
MAX_TICKERS_PER_USER: Final = 100

# --------------------------------------------------------------------------
# Client polling / tokens
# --------------------------------------------------------------------------
POLL_MS_OPEN: Final = 20_000
POLL_MS_CLOSED: Final = 900_000
DIGEST_TOKEN_TTL_S: Final = 1800

# --------------------------------------------------------------------------
# Freshness / staleness
# --------------------------------------------------------------------------
STALE_AFTER_S = {"ws": 60, "rest": 180, "eod": 86400, "mock": 86400}
BASELINE_STALE_SESSIONS: Final = 2
RESPONSE_CACHE_TTL_H: Final = 48
SPY_MIN_BARS: Final = 260

# --------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------
MARKET_TZ: Final = "America/New_York"
EXCHANGE_CALENDAR: Final = "XNYS"

SECTOR_BENCHMARKS: Final = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
}
DEFAULT_BENCHMARK: Final = "SPY"
SECTOR_ETFS: Final = frozenset(SECTOR_BENCHMARKS.values())
BROAD_ETFS: Final = frozenset({"SPY", "QQQ", "IWM", "DIA", "VTI", "VOO"})
BENCHMARK_UNIVERSE: Final = tuple(sorted(SECTOR_ETFS)) + (DEFAULT_BENCHMARK,)

# The sector an ETF *is*, as opposed to the sector it benchmarks against.
# Inverts SECTOR_BENCHMARKS so a sector ETF can report its own sector rather
# than a blank cell or a raw instrument_class.
ETF_SECTORS: Final = {etf: sector for sector, etf in SECTOR_BENCHMARKS.items()}

# Finnhub's /stock/profile2 returns nothing for ETFs, so the whole benchmark
# universe would otherwise carry a NULL name forever. These are fixed
# instruments chosen by this system, not user input, so naming them here is
# the honest fix: the alternative is a per-ETF provider call for data that
# never changes.
#
# `db/002_etf_names.sql` backfills existing rows from this same list, and
# `tests/test_integrity.py` asserts the two never drift apart.
ETF_NAMES: Final = {
    # Broad market
    "SPY": "SPDR S&P 500 ETF Trust",
    "QQQ": "Invesco QQQ Trust",
    "IWM": "iShares Russell 2000 ETF",
    "DIA": "SPDR Dow Jones Industrial Average ETF Trust",
    "VTI": "Vanguard Total Stock Market ETF",
    "VOO": "Vanguard S&P 500 ETF",
    # Sector SPDRs
    "XLK": "Technology Select Sector SPDR",
    "XLF": "Financial Select Sector SPDR",
    "XLE": "Energy Select Sector SPDR",
    "XLV": "Health Care Select Sector SPDR",
    "XLI": "Industrial Select Sector SPDR",
    "XLY": "Consumer Discretionary Select Sector SPDR",
    "XLP": "Consumer Staples Select Sector SPDR",
    "XLU": "Utilities Select Sector SPDR",
    "XLRE": "Real Estate Select Sector SPDR",
    "XLB": "Materials Select Sector SPDR",
    "XLC": "Communication Services Select Sector SPDR",
}

# Finnhub's /stock/profile2 uses its own sector vocabulary; map to ours.
FINNHUB_SECTOR_ALIASES: Final = {
    "Technology": "Technology",
    "Semiconductors": "Technology",
    "Electronic Technology": "Technology",
    "Technology Services": "Technology",
    "Financial": "Financial Services",
    "Finance": "Financial Services",
    "Banking": "Financial Services",
    "Energy": "Energy",
    "Energy Minerals": "Energy",
    "Health Care": "Healthcare",
    "Healthcare": "Healthcare",
    "Health Technology": "Healthcare",
    "Industrials": "Industrials",
    "Industrial Services": "Industrials",
    "Producer Manufacturing": "Industrials",
    "Consumer Cyclical": "Consumer Cyclical",
    "Retail Trade": "Consumer Cyclical",
    "Consumer Durables": "Consumer Cyclical",
    "Consumer Defensive": "Consumer Defensive",
    "Consumer Non-Durables": "Consumer Defensive",
    "Distribution Services": "Consumer Defensive",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Basic Materials": "Basic Materials",
    "Non-Energy Minerals": "Basic Materials",
    "Process Industries": "Basic Materials",
    "Communication Services": "Communication Services",
    "Communications": "Communication Services",
    "Media": "Communication Services",
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Settings:
    """Runtime configuration. Read once at import; mutable in tests."""

    database_url: str = _env(
        "DATABASE_URL", "postgresql+asyncpg://smw:smw@postgres:5432/smw"
    )
    database_url_direct: str = _env("DATABASE_URL_DIRECT", "") or database_url
    redis_url: str = _env("REDIS_URL", "redis://redis:6379/0")
    # Locks live in a separate logical DB configured `noeviction`; under
    # allkeys-lru the lock keys are evictable and stampede protection silently
    # stops working under memory pressure.
    redis_lock_url: str = _env("REDIS_LOCK_URL", "") or _env(
        "REDIS_URL", "redis://redis:6379/0"
    ).rsplit("/", 1)[0] + "/1"

    supabase_jwks_url: str = _env("SUPABASE_JWKS_URL")
    supabase_jwt_audience: str = _env("SUPABASE_JWT_AUDIENCE", "authenticated")
    # Local/dev fallback when no Supabase project is configured. `docker compose
    # up` with no keys must boot fully working, and JWKS verification cannot.
    dev_auth_secret: str = _env("DEV_AUTH_SECRET", "dev-insecure-local-only")

    digest_token_secret: str = _env("DIGEST_TOKEN_SECRET", "dev-insecure-local-only")

    twelvedata_api_key: str = _env("TWELVEDATA_API_KEY")
    finnhub_api_key: str = _env("FINNHUB_API_KEY")
    provider_mode: str = _env("PROVIDER_MODE", "replay").lower()

    fixtures_dir: str = _env("FIXTURES_DIR", "fixtures")
    # Replay clock: pin "now" to a fixture date so the demo is reproducible.
    replay_now: str = _env("REPLAY_NOW", "")
    replay_scenario: str = _env("REPLAY_SCENARIO", "baseline")

    log_level: str = _env("LOG_LEVEL", "INFO")
    cors_origins: str = _env("CORS_ORIGINS", "*")

    @property
    def live(self) -> bool:
        return self.provider_mode == "live"


settings = Settings()
