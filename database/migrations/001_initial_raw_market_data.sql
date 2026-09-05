-- Migration: 001_initial_raw_market_data
-- Purpose: Create raw market data storage tables (market_ticks and market_candles)
-- Date: 2026-09-05

-- 1. Raw Market Ticks Table
CREATE TABLE IF NOT EXISTS market_ticks (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    bid NUMERIC(14, 6) NOT NULL,
    ask NUMERIC(14, 6) NOT NULL,
    last NUMERIC(14, 6),
    volume NUMERIC(16, 4) NOT NULL DEFAULT 0,
    tick_direction VARCHAR(8),
    source VARCHAR(32) NOT NULL DEFAULT 'MT5_EXNESS',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for tick lookup and range scans by symbol and timestamp
CREATE INDEX IF NOT EXISTS idx_market_ticks_symbol_timestamp 
    ON market_ticks (symbol, timestamp);

-- 2. Market Candles Table
CREATE TABLE IF NOT EXISTS market_candles (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(14, 6) NOT NULL,
    high NUMERIC(14, 6) NOT NULL,
    low NUMERIC(14, 6) NOT NULL,
    close NUMERIC(14, 6) NOT NULL,
    tick_volume BIGINT NOT NULL DEFAULT 0,
    real_volume BIGINT NOT NULL DEFAULT 0,
    spread NUMERIC(8, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_valid_timeframe CHECK (timeframe IN ('M1', 'M5', 'M15', 'H1')),
    CONSTRAINT uq_market_candles_symbol_tf_ts UNIQUE (symbol, timeframe, timestamp)
);

-- Index for candle time-series queries
CREATE INDEX IF NOT EXISTS idx_market_candles_symbol_tf_ts 
    ON market_candles (symbol, timeframe, timestamp);
