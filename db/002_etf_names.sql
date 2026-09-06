-- ETF display names and sectors.
--
-- Finnhub's /stock/profile2 returns nothing for ETFs, so every row in the
-- benchmark and broad-ETF universe was seeded with a NULL name and, for sector
-- ETFs, a NULL sector. This backfills rows that predate the static map in
-- `api/config.py`; new rows are filled at seed time by `ensure_ticker_row`.
--
-- SOURCE OF TRUTH: api/config.py ETF_NAMES and ETF_SECTORS. The two lists are
-- asserted equal by tests/test_integrity.py, so adding an instrument in one
-- place and not the other fails the suite rather than shipping a blank cell.
--
-- Idempotent: only NULLs are written, so a provider-supplied or hand-corrected
-- name is never overwritten, and re-running on every boot is a no-op.

UPDATE tickers AS t
   SET name = v.name
  FROM (VALUES
    -- Broad market
    ('SPY',  'SPDR S&P 500 ETF Trust'),
    ('QQQ',  'Invesco QQQ Trust'),
    ('IWM',  'iShares Russell 2000 ETF'),
    ('DIA',  'SPDR Dow Jones Industrial Average ETF Trust'),
    ('VTI',  'Vanguard Total Stock Market ETF'),
    ('VOO',  'Vanguard S&P 500 ETF'),
    -- Sector SPDRs
    ('XLK',  'Technology Select Sector SPDR'),
    ('XLF',  'Financial Select Sector SPDR'),
    ('XLE',  'Energy Select Sector SPDR'),
    ('XLV',  'Health Care Select Sector SPDR'),
    ('XLI',  'Industrial Select Sector SPDR'),
    ('XLY',  'Consumer Discretionary Select Sector SPDR'),
    ('XLP',  'Consumer Staples Select Sector SPDR'),
    ('XLU',  'Utilities Select Sector SPDR'),
    ('XLRE', 'Real Estate Select Sector SPDR'),
    ('XLB',  'Materials Select Sector SPDR'),
    ('XLC',  'Communication Services Select Sector SPDR')
  ) AS v(ticker, name)
 WHERE t.ticker = v.ticker
   AND t.name IS NULL;

-- The sector a sector ETF IS, not the one it benchmarks against. Without it
-- the watchlist has nothing to show but the raw instrument_class.
UPDATE tickers AS t
   SET sector = v.sector
  FROM (VALUES
    ('XLK',  'Technology'),
    ('XLF',  'Financial Services'),
    ('XLE',  'Energy'),
    ('XLV',  'Healthcare'),
    ('XLI',  'Industrials'),
    ('XLY',  'Consumer Cyclical'),
    ('XLP',  'Consumer Defensive'),
    ('XLU',  'Utilities'),
    ('XLRE', 'Real Estate'),
    ('XLB',  'Basic Materials'),
    ('XLC',  'Communication Services')
  ) AS v(ticker, sector)
 WHERE t.ticker = v.ticker
   AND t.sector IS NULL
   AND t.instrument_class = 'sector_etf';
