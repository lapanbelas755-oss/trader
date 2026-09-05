-- Migration: 002_market_features
-- Purpose: Create storage table for derived market measurements, volatility baselines, and anomalies
-- Date: 2026-09-05

CREATE TABLE IF NOT EXISTS market_features (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,

    -- Geometry & ATR
    atr NUMERIC(14, 6),
    range NUMERIC(14, 6) NOT NULL,
    body NUMERIC(14, 6) NOT NULL,
    price_change NUMERIC(14, 6) NOT NULL,
    movement_efficiency NUMERIC(8, 4),

    -- Effort vs Result (Law #4)
    effort NUMERIC(16, 4) NOT NULL,
    result NUMERIC(14, 6),
    effort_result_ratio NUMERIC(16, 4),

    -- Volatility & Baselines
    volatility NUMERIC(14, 6),
    volatility_zscore NUMERIC(8, 4),
    activity_zscore NUMERIC(8, 4),
    price_response_zscore NUMERIC(8, 4),

    -- Anomaly Flags (Law #5, research parameters)
    is_anomaly_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    is_strong_anomaly BOOLEAN NOT NULL DEFAULT FALSE,

    -- Market Speed
    movement_speed NUMERIC(14, 8),
    range_per_second NUMERIC(14, 8),
    price_change_per_second NUMERIC(14, 8),

    -- Quality & Lifecycle
    feature_status VARCHAR(32) NOT NULL DEFAULT 'WARMUP',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_feature_timeframe CHECK (timeframe IN ('M1', 'M5', 'M15', 'H1')),
    CONSTRAINT chk_feature_status CHECK (feature_status IN ('VALID', 'WARMUP', 'INSUFFICIENT_DATA', 'INVALID')),
    CONSTRAINT uq_market_features_symbol_tf_ts UNIQUE (symbol, timeframe, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_market_features_symbol_tf_ts 
    ON market_features (symbol, timeframe, timestamp);
