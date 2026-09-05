# Statistical Edge Engine V1 — Technical Specification & Contract

## 1. Overview & Purpose

The **Statistical Edge Engine V1** evaluates completed backtest results to determine whether observed performance contains statistically meaningful, stable evidence of an edge.

**Core Principles:**
- **Truth in Advertising:** High win rate alone does not define an edge. The engine separates observed descriptive results from inferential statistical significance.
- **Zero Parameter Optimization:** Strictly analyzes completed baseline backtests without changing entries, stops, targets, or detection thresholds.
- **Deterministic Resampling:** All bootstrap sampling and Monte Carlo sequence reshuffling use cryptographic pseudo-random seeds derived from `dataset_hash + backtest_config_hash + setup_code`.
- **Multiple Testing Awareness:** Explicitly tallies and logs the number of sub-segments examined to guard against false discovery from data dredging.

---

## 2. Statistical Metrics & Mathematical Formats

### 1. Win Rate & Wilson Score Confidence Interval
Win rate is defined as:
$$\text{WR} = \frac{\text{wins}}{\text{wins} + \text{losses}}$$
*(Timeouts and ambiguous trades are excluded from the denominator but tracked separately).*

Because the normal approximation fails for small samples or boundary probabilities, the engine calculates the **Wilson Score Interval**:
$$\tilde{p} = \frac{\hat{p} + \frac{z^2}{2n}}{1 + \frac{z^2}{n}}, \quad m = \frac{z}{1 + \frac{z^2}{n}} \sqrt{\frac{\hat{p}(1 - \hat{p})}{n} + \frac{z^2}{4n^2}}$$
$$\text{CI}_{95\%} = [\max(0, \tilde{p} - m), \min(1, \tilde{p} + m)]$$
Where $z = 1.95996$ for a two-sided 95% confidence level.

### 2. Expectancy & Distribution Moments
- **Expectancy:** Primary performance metric:
  $$E[R] = \frac{1}{N} \sum_{i=1}^N R_i$$
- **Median & Standard Deviation:** Evaluated across realized R-multiples to assess skew and dispersion.

### 3. Profit Factor
$$\text{PF} = \frac{\sum_{R_i > 0} R_i}{\left| \sum_{R_i < 0} R_i \right|}$$
If gross negative $R = 0$, $\text{PF}$ is explicitly classified as `INF / UNDEFINED` without fabricating a finite number.

### 4. Maximum Drawdown & Consecutive Losses
- Evaluated strictly in chronological trade execution order:
  $$E_t = \sum_{i=1}^t R_i, \quad \text{DD}_t = \max_{s \le t} E_s - E_t, \quad \text{Max DD} = \max_t \text{DD}_t$$
- Maximum consecutive losses count consecutive trades with $R < 0$ or result == SL.

---

## 3. Resampling Methodologies

### Deterministic Bootstrap
- Resamples $N$ observations with replacement over 10,000 iterations.
- Generates empirical distributions for Expectancy ($E[R]$), Win Rate, and Total R.
- Reports:
  - 2.5th percentile (Lower Bound)
  - 50.0th percentile (Median)
  - 97.5th percentile (Upper Bound)
  - **Positive Fraction:** Proportion of bootstrap iterations yielding $E[R] > 0$.

### Monte Carlo Sequence Permutation
- Reshuffles the sequence of realized trade outcomes without replacement over 1,000 iterations.
- Analyzes equity path variability, median maximum drawdown, 95th percentile drawdown, 99th percentile worst-case drawdown, and probability of negative terminal equity.

---

## 4. Multi-Dimensional Segmentation & Multiple Testing

Trades are segmented across:
1. `REGIME` (e.g. HIGH_VOLATILITY, RANGE, TREND)
2. `SESSION` (ASIA: 00:00–08:00, LONDON: 08:00–13:00, NEW_YORK: 13:00–21:00 UTC)
3. `DIRECTION` (BUY vs SELL asymmetry)
4. `LIQUIDITY_TYPE` (PREVIOUS_DAY_HIGH, SWING_LOW, etc.)
5. `SPREAD_BUCKET` (LOW, NORMAL, HIGH, EXTREME)
6. `DAY_OF_WEEK` (MONDAY through FRIDAY)

**Multiple Testing Warning:**
The report explicitly outputs `Total Sub-Segments Examined`. Segmented findings are labeled exploratory unless independently validated on fresh data.

---

## 5. Out-Of-Sample (OOS) Degradation

Measures transferability across chronological partitions:
$$\text{Degradation Ratio} = \frac{\text{OOS Expectancy}}{\text{In-Sample Expectancy}}$$
- `STABLE`: Ratio $\ge 0.60$ and OOS Expectancy $> 0$.
- `DEGRADED`: $0.00 < \text{Ratio} < 0.60$.
- `COLLAPSED`: Ratio $\le 0.00$ (OOS Expectancy $\le 0$).
- `NOT_APPLICABLE`: If In-Sample Expectancy $\le 0$.

---

## 6. Edge Classification Taxonomy

1. **`INVALID_DATA`:** Data quality gate failure (zero-risk trades, impossible prices, corrupted timestamps).
2. **`INSUFFICIENT_DATA`:** Sample size $N < 30$.
3. **`NEGATIVE_EDGE`:** $N \ge 30$ and overall expectancy $\le 0$.
4. **`NO_CLEAR_EDGE`:** Expectancy $> 0$, but bootstrap lower bound negative, OOS collapsed, or severe drawdown.
5. **`PRELIMINARY_EDGE`:** $30 \le N < 100$, expectancy $> 0$, bootstrap positive fraction $\ge 70\%$, acceptable drawdown.
6. **`POTENTIAL_EDGE`:** $N \ge 100$, expectancy $> 0$, bootstrap positive fraction $\ge 75\%$, OOS expectancy $> 0$.
7. **`ROBUST_EDGE`:** $N \ge 100$, positive expectancy in IS, Validation, and OOS, OOS degradation `STABLE`, bootstrap positive fraction $\ge 85\%$, max DD $\le 15R$, data quality PASS.

---

## 7. Database Schemas

- **`statistical_runs`:** Tracks run ID, backtest run ID, engine version, config hash, overall classification, and timestamps.
- **`edge_metrics`:** Stores setup-level metrics, Wilson CIs, bootstrap expectancy bounds, and classification.
- **`edge_segments`:** Stores exploratory segment slices (Regime, Session, Direction, Liquidity, Spread, Day of Week).
- **`bootstrap_results`:** Detailed distribution metrics (lower, median, upper, positive fraction).
