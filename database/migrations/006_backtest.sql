-- Migration: 006_backtest
-- Purpose: Create tables for backtest runs, trade simulations, and performance metrics
-- Date: 2026-09-05

-- 1. Backtest Runs Table
CREATE TABLE IF NOT EXISTS backtest_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    research_run_id BIGINT REFERENCES research_runs(id) ON DELETE CASCADE,
    backtest_version VARCHAR(32) NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
    trade_count INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    timeouts INTEGER NOT NULL DEFAULT 0,
    ambiguous INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    total_r NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_backtest_run_status CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    CONSTRAINT uq_backtest_run UNIQUE (run_id)
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_research 
    ON backtest_runs (research_run_id);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_config 
    ON backtest_runs (config_hash);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_status 
    ON backtest_runs (status);

-- 2. Backtest Trades Table
CREATE TABLE IF NOT EXISTS backtest_trades (
    id BIGSERIAL PRIMARY KEY,
    backtest_run_id BIGINT REFERENCES backtest_runs(id) ON DELETE CASCADE,
    setup_id VARCHAR(64) NOT NULL,
    setup_code VARCHAR(16) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC(12, 5) NOT NULL,
    stop_loss NUMERIC(12, 5) NOT NULL,
    take_profit NUMERIC(12, 5) NOT NULL,
    exit_time TIMESTAMPTZ,
    exit_price NUMERIC(12, 5),
    result VARCHAR(32) NOT NULL,
    r_multiple NUMERIC(12, 4),
    mae_r NUMERIC(12, 4),
    mfe_r NUMERIC(12, 4),
    commission NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    slippage NUMERIC(12, 5) NOT NULL DEFAULT 0.00000,
    spread NUMERIC(12, 5) NOT NULL DEFAULT 0.00000,
    status VARCHAR(16) NOT NULL DEFAULT 'CLOSED',
    split_type VARCHAR(16) NOT NULL DEFAULT 'IN_SAMPLE',
    ambiguity_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_trade_result CHECK (result IN ('TP', 'SL', 'TIMEOUT', 'INVALID', 'DATA_ERROR', 'AMBIGUOUS', 'SKIPPED_ACTIVE_TRADE')),
    CONSTRAINT chk_trade_status CHECK (status IN ('OPEN', 'CLOSED', 'SKIPPED', 'INVALID')),
    CONSTRAINT chk_trade_direction CHECK (direction IN ('BULLISH', 'BEARISH', 'UNDEFINED')),
    CONSTRAINT chk_trade_split CHECK (split_type IN ('IN_SAMPLE', 'VALIDATION', 'OUT_OF_SAMPLE')),
    CONSTRAINT chk_trade_setup_code CHECK (setup_code IN ('S01', 'S02', 'S03', 'S04', 'S05'))
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_code 
    ON backtest_trades (backtest_run_id, setup_code);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_entry 
    ON backtest_trades (symbol, entry_time);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_split 
    ON backtest_trades (split_type);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_result 
    ON backtest_trades (result);
