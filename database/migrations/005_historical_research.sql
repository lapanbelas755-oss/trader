-- Migration: 005_historical_research
-- Purpose: Create tables for versioned research datasets, research runs, and setup occurrences
-- Date: 2026-09-05

-- 1. Research Datasets Table
CREATE TABLE IF NOT EXISTS research_datasets (
    id BIGSERIAL PRIMARY KEY,
    dataset_name VARCHAR(64) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    source VARCHAR(32) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    row_count BIGINT NOT NULL,
    dataset_version VARCHAR(32) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(32) NOT NULL DEFAULT 'BUILDING',

    CONSTRAINT chk_dataset_status CHECK (status IN ('BUILDING', 'VALIDATED', 'READY', 'REJECTED')),
    CONSTRAINT uq_research_dataset UNIQUE (dataset_name, dataset_version, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_research_datasets_lookup 
    ON research_datasets (symbol, timeframe, status);

CREATE INDEX IF NOT EXISTS idx_research_datasets_hash 
    ON research_datasets (content_hash);

-- 2. Research Runs Table
CREATE TABLE IF NOT EXISTS research_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    dataset_id BIGINT REFERENCES research_datasets(id) ON DELETE CASCADE,
    run_version VARCHAR(32) NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
    input_row_count BIGINT NOT NULL DEFAULT 0,
    output_row_count BIGINT NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_run_status CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    CONSTRAINT uq_research_run UNIQUE (run_id)
);

CREATE INDEX IF NOT EXISTS idx_research_runs_dataset 
    ON research_runs (dataset_id);

CREATE INDEX IF NOT EXISTS idx_research_runs_config 
    ON research_runs (config_hash);

CREATE INDEX IF NOT EXISTS idx_research_runs_status 
    ON research_runs (status);

-- 3. Research Setup Occurrences Table
CREATE TABLE IF NOT EXISTS research_setup_occurrences (
    id BIGSERIAL PRIMARY KEY,
    research_run_id BIGINT REFERENCES research_runs(id) ON DELETE CASCADE,
    setup_id VARCHAR(64) NOT NULL,
    setup_code VARCHAR(16) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    direction VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    regime VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    liquidity_type VARCHAR(32),
    structure_type VARCHAR(32),
    split_type VARCHAR(16) NOT NULL DEFAULT 'IN_SAMPLE',
    evidence_snapshot JSONB NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_occ_split CHECK (split_type IN ('IN_SAMPLE', 'VALIDATION', 'OUT_OF_SAMPLE')),
    CONSTRAINT chk_occ_status CHECK (status IN ('OBSERVE', 'WATCH', 'ARMED', 'FIRE', 'EXPIRED', 'REJECTED')),
    CONSTRAINT chk_occ_code CHECK (setup_code IN ('S01', 'S02', 'S03', 'S04', 'S05')),
    CONSTRAINT chk_occ_direction CHECK (direction IN ('BULLISH', 'BEARISH', 'UNDEFINED')),
    CONSTRAINT uq_research_occurrence UNIQUE (research_run_id, setup_code, timestamp, status, direction)
);

CREATE INDEX IF NOT EXISTS idx_research_occ_run_code 
    ON research_setup_occurrences (research_run_id, setup_code);

CREATE INDEX IF NOT EXISTS idx_research_occ_ts 
    ON research_setup_occurrences (symbol, timestamp);

CREATE INDEX IF NOT EXISTS idx_research_occ_split 
    ON research_setup_occurrences (split_type);
