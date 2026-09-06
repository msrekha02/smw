-- Smart Market Watchlist -- base schema.
-- Idempotent: safe to run on every boot.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS app_users (
  id UUID PRIMARY KEY,
  email TEXT,
  seed_credits_used_today INT NOT NULL DEFAULT 0,
  seed_credits_reset_on DATE NOT NULL DEFAULT CURRENT_DATE,
  timezone TEXT NOT NULL DEFAULT 'America/New_York',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sector_benchmarks (
  sector TEXT PRIMARY KEY,
  benchmark_ticker TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickers (
  ticker TEXT PRIMARY KEY,
  name TEXT,
  instrument_class TEXT NOT NULL DEFAULT 'stock',   -- stock|sector_etf|broad_etf
  sector TEXT REFERENCES sector_benchmarks(sector),
  benchmark_ticker TEXT,                             -- resolved at seed
  status TEXT NOT NULL DEFAULT 'seeding',            -- seeding|active|halted|unknown
  last_watched_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS symbol_catalog (
  ticker TEXT PRIMARY KEY,
  name TEXT,
  exchange TEXT,
  type TEXT,
  is_active BOOLEAN NOT NULL DEFAULT true,
  refcount INT NOT NULL DEFAULT 0,
  refreshed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS symbol_catalog_trgm
  ON symbol_catalog USING gin ((ticker || ' ' || coalesce(name,'')) gin_trgm_ops);

-- ONE watchlist per user. Adding multi-list later = add a watchlist_id column.
CREATE TABLE IF NOT EXISTS watchlist_items (
  user_id UUID NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  ticker TEXT NOT NULL REFERENCES tickers(ticker),
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  pinned_unread BOOLEAN NOT NULL DEFAULT false,
  PRIMARY KEY (user_id, ticker)
);
CREATE INDEX IF NOT EXISTS watchlist_items_ticker_idx ON watchlist_items (ticker);

CREATE TABLE IF NOT EXISTS ticker_daily_bar (
  ticker TEXT NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
  bar_date DATE NOT NULL,
  open DOUBLE PRECISION NOT NULL,
  high DOUBLE PRECISION NOT NULL,
  low  DOUBLE PRECISION NOT NULL,
  close DOUBLE PRECISION NOT NULL,
  volume BIGINT,
  PRIMARY KEY (ticker, bar_date)
);

CREATE TABLE IF NOT EXISTS ticker_baseline (
  ticker TEXT PRIMARY KEY REFERENCES tickers(ticker) ON DELETE CASCADE,
  sample_days INT NOT NULL DEFAULT 0,
  mean_ret DOUBLE PRECISION,
  var_stock DOUBLE PRECISION,
  mean_bench DOUBLE PRECISION,
  var_bench DOUBLE PRECISION,
  cov DOUBLE PRECISION,
  beta_raw DOUBLE PRECISION,
  beta_used DOUBLE PRECISION,
  r2 DOUBLE PRECISION,
  mean_excess DOUBLE PRECISION,
  var_excess DOUBLE PRECISION,
  sigma_idio DOUBLE PRECISION,
  sigma_mad DOUBLE PRECISION,
  adv20 DOUBLE PRECISION,
  wk52_high DOUBLE PRECISION,
  wk52_low DOUBLE PRECISION,
  recent_daily JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{d,exc,volr,close}] x30
  residual_hist JSONB,                                -- 40-bin histogram of u_d
  last_bar_date DATE,
  frozen_reason TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS earnings_dates (
  ticker TEXT NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
  event_date DATE NOT NULL,
  source TEXT NOT NULL,
  PRIMARY KEY (ticker, event_date)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL REFERENCES tickers(ticker) ON DELETE CASCADE,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  effective_date DATE NOT NULL,
  observed_ratio DOUBLE PRECISION NOT NULL,
  acknowledged BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS ticker_latest (
  ticker TEXT PRIMARY KEY REFERENCES tickers(ticker) ON DELETE CASCADE,
  price DOUBLE PRECISION,
  prev_close DOUBLE PRECISION,
  day_volume BIGINT,
  is_extended_hours BOOLEAN NOT NULL DEFAULT false,
  source TEXT NOT NULL,                              -- ws|rest|eod|mock
  fetched_at TIMESTAMPTZ NOT NULL,
  bar_date DATE,                                     -- set when source='eod'
  extended_price DOUBLE PRECISION,                   -- displayed, never scored
  status TEXT NOT NULL DEFAULT 'ok',                 -- ok|verifying|no_data|halted
  pending_price DOUBLE PRECISION,
  pending_since TIMESTAMPTZ,
  pending_cycles INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watchlist_snapshots (
  user_id UUID NOT NULL,
  ticker TEXT NOT NULL,
  last_seen_price DOUBLE PRECISION NOT NULL,
  last_seen_bench DOUBLE PRECISION NOT NULL,
  last_seen_bench_ticker TEXT NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  is_initial BOOLEAN NOT NULL DEFAULT true,
  PRIMARY KEY (user_id, ticker),
  FOREIGN KEY (user_id, ticker)
    REFERENCES watchlist_items(user_id, ticker) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS digest_feedback (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL,
  ticker TEXT NOT NULL,
  tier TEXT NOT NULL,
  attention DOUBLE PRECISION NOT NULL,
  shown_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  clicked_through BOOLEAN NOT NULL DEFAULT false,
  dismissed_fast BOOLEAN NOT NULL DEFAULT false,
  thumb SMALLINT                                     -- -1 | NULL | 1
);
CREATE INDEX IF NOT EXISTS digest_feedback_shown_idx ON digest_feedback (shown_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS digest_feedback_impression_idx
  ON digest_feedback (user_id, ticker, shown_at);

CREATE TABLE IF NOT EXISTS job_run (
  run_date DATE PRIMARY KEY,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL,
  credits_spent INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS job_item (
  run_date DATE,
  ticker TEXT,
  refcount INT NOT NULL DEFAULT 0,
  status TEXT NOT NULL,                              -- pending|in_flight|done|failed
  attempts INT NOT NULL DEFAULT 0,
  error TEXT,
  PRIMARY KEY (run_date, ticker)
);

CREATE TABLE IF NOT EXISTS provider_response_cache (
  ticker TEXT,
  run_date DATE,
  payload JSONB NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, run_date)
);

-- Daily quota ledger, one row per (partition, day). The reserve partition is
-- never addressable from a user-triggered path; enforcement is in quota.py.
CREATE TABLE IF NOT EXISTS quota_ledger (
  partition TEXT NOT NULL,
  usage_date DATE NOT NULL,
  spent INT NOT NULL DEFAULT 0,
  PRIMARY KEY (partition, usage_date)
);

-- Staleness is computed at READ time. A GENERATED ALWAYS AS ... STORED column
-- using now() is rejected by Postgres (non-immutable) and would freeze the
-- value at insert time even if it were allowed.
CREATE OR REPLACE VIEW ticker_latest_v AS
SELECT tl.*,
       EXTRACT(EPOCH FROM (now() - tl.fetched_at)) AS age_s,
       EXTRACT(EPOCH FROM (now() - tl.fetched_at)) >
         CASE tl.source WHEN 'ws' THEN 60 WHEN 'rest' THEN 180 ELSE 86400 END
       AS is_stale
FROM ticker_latest tl;

INSERT INTO sector_benchmarks (sector, benchmark_ticker) VALUES
  ('Technology','XLK'), ('Financial Services','XLF'), ('Energy','XLE'),
  ('Healthcare','XLV'), ('Industrials','XLI'), ('Consumer Cyclical','XLY'),
  ('Consumer Defensive','XLP'), ('Utilities','XLU'), ('Real Estate','XLRE'),
  ('Basic Materials','XLB'), ('Communication Services','XLC')
ON CONFLICT (sector) DO UPDATE SET benchmark_ticker = EXCLUDED.benchmark_ticker;

