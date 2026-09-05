# Backtest Engine V1 — Technical Specification & Contract

## 1. Overview & Purpose

The **Backtest Engine V1** evaluates the historical consequences of deterministic setup occurrences (S01–S05) identified by the upstream research and setup detection engines.

**Core Principles:**
- **Zero Profitability Assumption:** The engine measures simulated historical outcomes under explicitly defined, reproducible baseline rules. It does **not** claim market edge, tune parameters, or search for arbitrary win rates.
- **Strict Causality (No Lookahead):** Decisions at trade entry timestamp $T$ use only market information known at or before $T$. Subsequent candles simulate price progression and exit triggers only.
- **Intrabar Ambiguity Protocol:** If both Stop Loss and Take Profit are breached within the same candle, the outcome is marked as `AMBIGUOUS` with zero bias (excluded from win-rate denominator).
- **Collision Management:** By default, concurrent trades in the same symbol are capped at 1 (`MAX_ONE_ACTIVE_TRADE_PER_SYMBOL`), recording overlapping signals as `SKIPPED_ACTIVE_TRADE` without silent omission.

---

## 2. Pipeline Flow

```
RESEARCH DATASET
       ↓
SETUP OCCURRENCE (FIRE at T)
       ↓
BACKTEST RULE (Entry, SL, TP <= T)
       ↓
ENTRY EXECUTION (Ask/Bid or Fallback)
       ↓
STRUCTURAL SL & BASELINE 2R TP
       ↓
PRICE PATH SIMULATION (T+1, T+2, ...)
       ↓
TRADE OUTCOME (TP / SL / TIMEOUT / AMBIGUOUS)
       ↓
REALIZED R-MULTIPLE & MAE/MFE
       ↓
PERFORMANCE METRICS & REPORT
```

---

## 3. Trade Entry & Sizing Rules

### Entry Price
- **BUY:** `entry_price = ask` (if Real Bid/Ask available) or `close` (fallback).
- **SELL:** `entry_price = bid` (if Real Bid/Ask available) or `close` (fallback).
- **Slippage:** Configurable price unit addition/subtraction.

### Structural Stop Loss (SL)
Derived strictly from candles available at or before entry timestamp $T$:
- **S01 (Sweep Reversal):** Beyond sweep extreme $\pm$ buffer pips.
- **S02 (Acceptance Continuation):** Beyond breakout invalidation level / recent swing $\pm$ buffer pips.
- **S03 (Failed Breakout Trap):** Beyond false-breakout extreme $\pm$ buffer pips.
- **S04 (Effort vs Result Anomaly):** Beyond anomaly candle extreme $\pm$ buffer pips.
- **S05 (Compression $\to$ Expansion):** Beyond opposite compression boundary $\pm$ buffer pips.
- **Risk Invalidation:** If risk distance $R = |entry - SL| \le 0$, trade is marked `INVALID`.

### Baseline Take Profit (TP)
- Initial research baseline is strictly **2.0R**:
  $$\text{BUY: } TP = \text{entry} + (2.0 \times R)$$
  $$\text{SELL: } TP = \text{entry} - (2.0 \times R)$$

---

## 4. Price Path Simulation & Exit Logic

For subsequent candles $T+1, T+2, \dots$:
1. **Intrabar Ambiguity:**
   If `low <= SL` AND `high >= TP` (for BUY) or `high >= SL` AND `low <= TP` (for SELL) within the exact same candle:
   - Classified as `AMBIGUOUS`.
   - Realized $R$ is `None`. Excluded from win-rate calculation.
2. **Take Profit (TP):**
   If only TP is hit:
   - Result: `TP`.
   - Realized $R = +2.0 - \text{commission\_in\_R}$.
3. **Stop Loss (SL):**
   If only SL is hit:
   - Result: `SL`.
   - Realized $R = -1.0 - \text{commission\_in\_R}$.
4. **Timeout:**
   If neither is hit after 3 closed M5 candles (`timeout_bars = 3`):
   - Result: `TIMEOUT`.
   - Realized $R = \frac{\text{exit} - \text{entry}}{R_{\text{unit}}} - \text{commission\_in\_R}$ (for BUY).
5. **MAE / MFE:**
   - **MAE (Maximum Adverse Excursion):** Maximum excursion in R against the position prior to exit.
   - **MFE (Maximum Favorable Excursion):** Maximum excursion in R in favor of the position prior to exit.

---

## 5. Collision Policy

- Policy: `MAX_ONE_ACTIVE_TRADE_PER_SYMBOL`.
- If a setup reaches `FIRE` while an active trade is open in the symbol:
  - Result: `SKIPPED_ACTIVE_TRADE`.
  - Status: `SKIPPED`.
  - Auditable reason recorded with the blocking trade ID and active window.

---

## 6. Performance Metrics

- **Sample Size:** Total trade candidates evaluated.
- **Win Rate:** $\frac{\text{wins}}{\text{wins} + \text{losses}}$ (Timeouts and Ambiguous trades are excluded from the denominator).
- **Average Win R / Average Loss R:** Mean realized R for positive / negative outcomes.
- **Expectancy R:** Mean realized R across all completed trades: $\text{mean}(R)$.
- **Profit Factor:** $\frac{\text{Gross Positive R}}{|\text{Gross Negative R}|}$.
- **Max Drawdown R:** Peak-to-trough decline of cumulative realized R equity curve.
- **Max Consecutive Losses:** Maximum consecutive losing/SL outcomes.
- **Split Segregation:** Metrics calculated independently across `IN_SAMPLE` (60%), `VALIDATION` (20%), and `OUT_OF_SAMPLE` (20%) partitions.

---

## 7. Database Schemas

### `backtest_runs`
- `id` (BIGSERIAL PK)
- `run_id` (VARCHAR UNIQUE)
- `research_run_id` (BIGINT FK to `research_runs.id`)
- `backtest_version` (VARCHAR)
- `config_hash` (VARCHAR)
- `trade_count`, `wins`, `losses`, `timeouts`, `ambiguous`, `skipped` (INTEGER)
- `total_r` (NUMERIC)
- `metrics` (JSONB)
- `started_at`, `completed_at`, `status`

### `backtest_trades`
- `id` (BIGSERIAL PK)
- `backtest_run_id` (BIGINT FK to `backtest_runs.id`)
- `setup_id`, `setup_code`, `symbol`, `timeframe`, `direction`
- `entry_time`, `entry_price`, `stop_loss`, `take_profit`
- `exit_time`, `exit_price`, `result`, `r_multiple`
- `mae_r`, `mfe_r`, `commission`, `slippage`, `spread`
- `status`, `split_type`, `ambiguity_reason`
