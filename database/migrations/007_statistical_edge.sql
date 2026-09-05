-- Migration: 007_statistical_edge
-- Purpose: Create tables for statistical runs, edge metrics, segment analysis, and bootstrap results
-- Date: 2026-09-05

-- 1. Statistical Runs Table
CREATE TABLE IF NOT EXISTS statistical_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    backtest_run_id BIGINT REFERENCES backtest_runs(id) ON DELETE CASCADE,
    dataset_split VARCHAR(32) NOT NULL DEFAULT 'ALL',
    engine_version VARCHAR(32) NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
    overall_classification VARCHAR(32) NOT NULL DEFAULT 'INSUFFICIENT_DATA',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_stat_run_status CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    CONSTRAINT uq_statistical_run UNIQUE (run_id)
);

CREATE INDEX IF NOT EXISTS idx_stat_runs_backtest 
    ON statistical_runs (backtest_run_id);

CREATE INDEX IF NOT EXISTS idx_stat_runs_config 
    ON statistical_runs (config_hash);

-- 2. Edge Metrics Table
CREATE TABLE IF NOT EXISTS edge_metrics (
    id BIGSERIAL PRIMARY KEY,
    statistical_run_id BIGINT REFERENCES statistical_runs(id) ON DELETE CASCADE,
    setup_code VARCHAR(16) NOT NULL,
    split_type VARCHAR(16) NOT NULL DEFAULT 'ALL',
    sample_size INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    timeouts INTEGER NOT NULL DEFAULT 0,
    ambiguous INTEGER NOT NULL DEFAULT 0,
    win_rate NUMERIC(10, 4),
    win_rate_ci_lower NUMERIC(10, 4),
    win_rate_ci_upper NUMERIC(10, 4),
    average_win_r NUMERIC(12, 4),
    average_loss_r NUMERIC(12, 4),
    expectancy_r NUMERIC(12, 4),
    profit_factor NUMERIC(12, 4),
    total_r NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    max_drawdown_r NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    max_consecutive_losses INTEGER NOT NULL DEFAULT 0,
    mean_r NUMERIC(12, 4),
    median_r NUMERIC(12, 4),
    std_r NUMERIC(12, 4),
    classification VARCHAR(32) NOT NULL DEFAULT 'INSUFFICIENT_DATA',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_edge_setup_code CHECK (setup_code IN ('S01', 'S02', 'S03', 'S04', 'S05', 'OVERALL')),
    CONSTRAINT chk_edge_split CHECK (split_type IN ('ALL', 'IN_SAMPLE', 'VALIDATION', 'OUT_OF_SAMPLE'))
);

CREATE INDEX IF NOT EXISTS idx_edge_metrics_run_setup 
    ON edge_metrics (statistical_run_id, setup_code);

CREATE INDEX IF NOT EXISTS idx_edge_metrics_split 
    ON edge_metrics (split_type);

-- 3. Edge Segments Table
CREATE TABLE IF NOT EXISTS edge_segments (
    id BIGSERIAL PRIMARY KEY,
    statistical_run_id BIGINT REFERENCES statistical_runs(id) ON DELETE CASCADE,
    setup_code VARCHAR(16) NOT NULL,
    segment_type VARCHAR(32) NOT NULL,
    segment_value VARCHAR(64) NOT NULL,
    sample_size INTEGER NOT NULL DEFAULT 0,
    win_rate NUMERIC(10, 4),
    expectancy_r NUMERIC(12, 4),
    profit_factor NUMERIC(12, 4),
    total_r NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    max_drawdown_r NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_segment_type CHECK (segment_type IN (
        'REGIME', 'SESSION', 'DIRECTION', 'LIQUIDITY_TYPE',
        'SPREAD_BUCKET', 'DAY_OF_WEEK', 'MTF_ALIGNMENT', 'VOLATILITY_STATE'
    ))
);

CREATE INDEX IF NOT EXISTS idx_edge_segments_run_type 
    ON edge_segments (statistical_run_id, segment_type);

-- 4. Bootstrap Results Table
CREATE TABLE IF NOT EXISTS bootstrap_results (
    id BIGSERIAL PRIMARY KEY,
    statistical_run_id BIGINT REFERENCES statistical_runs(id) ON DELETE CASCADE,
    setup_code VARCHAR(16) NOT NULL,
    metric VARCHAR(32) NOT NULL,
    iterations INTEGER NOT NULL DEFAULT 10000,
    lower_bound NUMERIC(12, 4) NOT NULL,
    median NUMERIC(12, 4) NOT NULL,
    upper_bound NUMERIC(12, 4) NOT NULL,
    positive_fraction NUMERIC(10, 4) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bootstrap_run_setup 
    ON bootstrap_results (statistical_run_id, setup_code, metric);
