-- Migration: 004_setups
-- Purpose: Create tables for deterministic setup candidates and auditable setup evidence
-- Date: 2026-09-05

-- 1. Setups Table
CREATE TABLE IF NOT EXISTS setups (
    id BIGSERIAL PRIMARY KEY,
    setup_id VARCHAR(64) NOT NULL,
    setup_code VARCHAR(16) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(8) NOT NULL DEFAULT 'M5',
    timestamp TIMESTAMPTZ NOT NULL,
    direction VARCHAR(16) NOT NULL,
    regime VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    liquidity_type VARCHAR(32),
    structure_type VARCHAR(32),
    anomaly_type VARCHAR(32),
    status VARCHAR(16) NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,

    CONSTRAINT chk_setup_status CHECK (status IN ('OBSERVE', 'WATCH', 'ARMED', 'FIRE', 'EXPIRED', 'REJECTED')),
    CONSTRAINT chk_setup_code CHECK (setup_code IN ('S01', 'S02', 'S03', 'S04', 'S05')),
    CONSTRAINT chk_setup_direction CHECK (direction IN ('BULLISH', 'BEARISH', 'UNDEFINED')),
    CONSTRAINT uq_setup_event UNIQUE (symbol, timeframe, setup_code, timestamp, status, direction)
);

CREATE INDEX IF NOT EXISTS idx_setups_lookup 
    ON setups (symbol, setup_code, status);

CREATE INDEX IF NOT EXISTS idx_setups_ts 
    ON setups (symbol, timestamp);

CREATE INDEX IF NOT EXISTS idx_setups_setup_id 
    ON setups (setup_id);

-- 2. Setup Evidence Table
CREATE TABLE IF NOT EXISTS setup_evidence (
    id BIGSERIAL PRIMARY KEY,
    setup_id VARCHAR(64) NOT NULL,
    evidence_key VARCHAR(64) NOT NULL,
    evidence_value VARCHAR(128) NOT NULL,
    numeric_value NUMERIC(16, 6),
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_setup_evidence UNIQUE (setup_id, evidence_key)
);

CREATE INDEX IF NOT EXISTS idx_setup_evidence_setup_id 
    ON setup_evidence (setup_id);
