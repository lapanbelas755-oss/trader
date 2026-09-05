-- Migration: 008_market_datasets
-- Purpose: Schema for real market data acquisition, dataset provenance, and quality validation audits
-- Date: 2026-09-05

-- 1. Market Datasets Table
CREATE TABLE IF NOT EXISTS market_datasets (
    id BIGSERIAL PRIMARY KEY,
    dataset_name VARCHAR(128) NOT NULL UNIQUE,
    source_name VARCHAR(64) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_file VARCHAR(512) NOT NULL,
    format VARCHAR(16) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(16) NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    first_timestamp TIMESTAMPTZ,
    last_timestamp TIMESTAMPTZ,
    row_count BIGINT NOT NULL DEFAULT 0,
    content_hash VARCHAR(64) NOT NULL UNIQUE,
    schema_version VARCHAR(32) NOT NULL DEFAULT 'V1',
    quality_status VARCHAR(32) NOT NULL DEFAULT 'PASS',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_dataset_quality_status CHECK (quality_status IN ('PASS', 'PASS_WITH_WARNINGS', 'REJECTED'))
);

-- Index for dataset queries by symbol, timeframe, and quality status
CREATE INDEX IF NOT EXISTS idx_market_datasets_symbol_tf ON market_datasets (symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_market_datasets_hash ON market_datasets (content_hash);

-- 2. Market Data Quality Reports Table
CREATE TABLE IF NOT EXISTS market_data_quality_reports (
    id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES market_datasets(id) ON DELETE CASCADE,
    check_name VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    affected_rows BIGINT NOT NULL DEFAULT 0,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_quality_check_status CHECK (status IN ('PASS', 'WARNING', 'FAIL'))
);

-- Index for quality report lookups by dataset
CREATE INDEX IF NOT EXISTS idx_quality_reports_dataset_id ON market_data_quality_reports (dataset_id);
