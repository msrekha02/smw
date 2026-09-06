export type Tier = "critical" | "notable" | "minor" | "quiet";

export type CardState =
  | "ok"
  | "new"
  | "seeding"
  | "verifying"
  | "no_data"
  | "halted"
  | "unknown"
  | "action_frozen";

export interface Contribution {
  move: number;
  path: number;
  volume: number;
  breach: number;
}

export interface WindowPoint {
  /** Elapsed trading sessions since the window anchor. */
  t: number;
  /** Cumulative excess return at that point, as a fraction. */
  cum: number;
  /** Session date, or "" for the live endpoint. */
  d: string;
}

export interface Decomposition {
  cum_return: number;
  bench_return: number;
  bench_ticker: string | null;
  beta_used: number;
  beta_raw: number | null;
  r2: number | null;
  excess: number;
  sigma_idio: number;
  sigma_expected: number;
  n_days: number;
  n_eff: number;
  z_move: number;
  z_path: number;
  z_path_on: string | null;
  vol_score: number;
  vol_ratio: number;
  breach_score: number;
  breach_direction: string | null;
  contributions: Contribution;
  weights: Record<string, number>;
  /** Cumulative excess return per elapsed session. Sliced by the scorer. */
  window_path: WindowPoint[];
  earnings_days: string[];
  earnings_note: string | null;
}

export interface Sparkline {
  points: number[];
  dates: string[];
  window_from_index: number | null;
}

export interface Freshness {
  source: string;
  age_s: number;
  label: string;
  stale: boolean;
}

export interface DigestCard {
  ticker: string;
  name: string | null;
  state: CardState;
  tier: Tier;
  attention: number;
  direction: "up" | "down";
  price: number | null;
  reference_price: number | null;
  change_pct: number | null;
  excess_pct: number | null;
  reason: string;
  since_label: string;
  confidence: "ok" | "reduced";
  confidence_reasons: string[];
  freshness: Freshness | null;
  extended_hours: { price: number; change_pct: number; label: string } | null;
  sparkline: Sparkline | null;
  decomposition: Decomposition | null;
  action: { kind: string; message: string; cta: string } | null;
  observed_at: string | null;
}

export interface MarketState {
  ticker: string;
  return_pct: number;
  z: number;
  elevated: boolean;
  banner: string | null;
  session: "open" | "closed" | "extended" | "unknown";
}

export interface Digest {
  as_of: string;
  since: string | null;
  since_label: string;
  market: MarketState;
  cards: DigestCard[];
  quiet: DigestCard[];
  quiet_summary: string | null;
  counts: Record<string, number>;
  token: string;
  next_poll_after_ms: number;
  bootstrap: { ready: boolean; message: string } | null;
  notes: string[];
}

export interface WatchlistItem {
  ticker: string;
  name: string | null;
  sector: string | null;
  benchmark_ticker: string | null;
  instrument_class: string;
  status: string;
  added_at: string;
  pinned_unread: boolean;
}

export interface SymbolRow {
  ticker: string;
  name: string | null;
  exchange: string | null;
  type: string | null;
  already_watched: boolean;
  seeded: boolean;
}

export interface TickerDetail {
  ticker: string;
  name: string | null;
  sector: string | null;
  instrument_class: string;
  benchmark_ticker: string | null;
  status: string;
  beta_raw: number | null;
  beta_used: number | null;
  r2: number | null;
  sigma_idio: number | null;
  sample_days: number;
  adv20: number | null;
  wk52_high: number | null;
  wk52_low: number | null;
  last_bar_date: string | null;
  frozen_reason: string | null;
  residual_hist: {
    bins: number;
    lo: number;
    hi: number;
    counts: number[];
    under: number;
    over: number;
    n: number;
    sd: number;
    kurtosis: number;
    tail_3s: number;
  } | null;
  recent_daily: Array<Record<string, number | string>>;
  earnings: string[];
  scoring_note: string;
}

export interface ResidualHistogram {
  bins: number;
  lo: number;
  hi: number;
  counts: number[];
  under: number;
  over: number;
  n: number;
}

export interface Calibration {
  generated_at: string;
  universe: number;
  sessions: number;
  checks: number;
  window_days: number;
  watchlist_size: number;
  thresholds: Record<string, number>;
  predicted: Record<string, number>;
  observed: Record<string, number>;
  per_check_rates: Record<string, number>;
  attention_histogram: { edges: number[]; counts: number[] };
  residual_summary: Record<string, number>;
  residual_histogram: ResidualHistogram | null;
  precision_at_critical: {
    window_days: number;
    critical_shown: number;
    explicit_judgements: number;
    precision: number | null;
    click_through_rate: number | null;
    fast_dismiss_rate: number | null;
    note: string;
  };
  notes: string[];
}

export interface TokenResponse {
  user_id: string;
  email: string;
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface Me {
  user_id: string;
  email: string | null;
  mode: string;
}

export interface AuthMode {
  mode: "dev" | "supabase";
  local_login: boolean;
  notice: string | null;
}
