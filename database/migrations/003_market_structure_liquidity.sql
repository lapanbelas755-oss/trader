-- Migration: 003_market_structure_liquidity
-- Purpose: Create tables for market structure events (swings, BOS, CHoCH) and liquidity levels lifecycle
-- Date: 2026-09-05

-- 1. Market Structure Table
CREATE TABLE IF NOT EXISTS market_structure (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    confirmed_at TIMESTAMPTZ NOT NULL,
    structure_type VARCHAR(32) NOT NULL,
    price NUMERIC(14, 6) NOT NULL,
    swing_id VARCHAR(64),
    reference_swing_id VARCHAR(64),
    direction VARCHAR(16) NOT NULL,
    displacement NUMERIC(14, 6),
    strength NUMERIC(8, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_structure_timeframe CHECK (timeframe IN ('M5', 'M15', 'H1')),
    CONSTRAINT chk_structure_direction CHECK (direction IN ('BULLISH', 'BEARISH', 'MIXED', 'TRANSITION', 'UNDEFINED')),
    CONSTRAINT uq_market_structure_event UNIQUE (symbol, timeframe, timestamp, structure_type)
);

CREATE INDEX IF NOT EXISTS idx_market_structure_lookup 
    ON market_structure (symbol, timeframe, confirmed_at);

CREATE INDEX IF NOT EXISTS idx_market_structure_ts 
    ON market_structure (symbol, timeframe, timestamp);

-- 2. Liquidity Levels Table
CREATE TABLE IF NOT EXISTS liquidity_levels (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    level_type VARCHAR(32) NOT NULL,
    price NUMERIC(14, 6) NOT NULL,
    tolerance NUMERIC(14, 6) NOT NULL DEFAULT 0.000100,
    status VARCHAR(32) NOT NULL DEFAULT 'UNTOUCHED',
    session VARCHAR(16),
    source_swing_id VARCHAR(64),
    start_timestamp TIMESTAMPTZ NOT NULL,
    end_timestamp TIMESTAMPTZ,
    strength NUMERIC(8, 4),
    sweep_depth NUMERIC(14, 6),
    swept_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_liq_status CHECK (status IN ('UNTOUCHED', 'APPROACHED', 'TOUCHED', 'SWEPT', 'REJECTED', 'ACCEPTED', 'INVALIDATED')),
    CONSTRAINT uq_liquidity_level UNIQUE (symbol, timeframe, level_type, price, start_timestamp)
);

CREATE INDEX IF NOT EXISTS idx_liquidity_levels_lookup 
    ON liquidity_levels (symbol, timeframe, status);

CREATE INDEX IF NOT EXISTS idx_liquidity_levels_type_ts 
    ON liquidity_levels (symbol, level_type, start_timestamp);
