-- Migration: 009_derived_market_candles
-- Purpose: Schema for derived multi-timeframe candles aggregated from real tick data
-- Date: 2026-09-05

CREATE TABLE IF NOT EXISTS derived_market_candles (
    id BIGSERIAL PRIMARY KEY,
    source_dataset_id VARCHAR(128) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    -- Mid OHLC (Primary Research)
    mid_open NUMERIC(14, 6) NOT NULL,
    mid_high NUMERIC(14, 6) NOT NULL,
    mid_low NUMERIC(14, 6) NOT NULL,
    mid_close NUMERIC(14, 6) NOT NULL,
    -- Bid OHLC
    bid_open NUMERIC(14, 6) NOT NULL,
    bid_high NUMERIC(14, 6) NOT NULL,
    bid_low NUMERIC(14, 6) NOT NULL,
    bid_close NUMERIC(14, 6) NOT NULL,
    -- Ask OHLC
    ask_open NUMERIC(14, 6) NOT NULL,
    ask_high NUMERIC(14, 6) NOT NULL,
    ask_low NUMERIC(14, 6) NOT NULL,
    ask_close NUMERIC(14, 6) NOT NULL,
    -- Spread statistics (in price units or pips)
    spread_open NUMERIC(10, 6) NOT NULL,
    spread_high NUMERIC(10, 6) NOT NULL,
    spread_low NUMERIC(10, 6) NOT NULL,
    spread_close NUMERIC(10, 6) NOT NULL,
    spread_mean NUMERIC(10, 6) NOT NULL,
    spread_median NUMERIC(10, 6) NOT NULL,
    spread_min NUMERIC(10, 6) NOT NULL,
    spread_max NUMERIC(10, 6) NOT NULL,
    -- Activity
    tick_count BIGINT NOT NULL DEFAULT 0,
    derivation_version VARCHAR(32) NOT NULL DEFAULT 'V1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_derived_timeframe CHECK (timeframe IN ('M1', 'M5', 'M15', 'H1')),
    CONSTRAINT uq_derived_candles_prov_sym_tf_ts UNIQUE (provider, symbol, timeframe, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_derived_candles_sym_tf_ts ON derived_market_candles (symbol, timeframe, timestamp);
CREATE INDEX IF NOT EXISTS idx_derived_candles_source_ds ON derived_market_candles (source_dataset_id);
