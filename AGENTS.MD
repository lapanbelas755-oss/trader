# TRADER MACHINE — MASTER AGENT INSTRUCTION

## 1. PROJECT IDENTITY

Project name: Trader Machine V1

Purpose:

Build a research-first, evidence-driven automated Forex trading system for MetaTrader 5.

Initial broker:
Exness

Initial instrument:
EURUSD

Initial mode:
RESEARCH / DEMO ONLY

The system must NOT trade real money during development.

The objective is NOT to guarantee profit or achieve an arbitrary win rate.

The objective is to discover whether measurable, statistically robust, positive-expectancy market behavior exists and can survive out-of-sample testing, realistic transaction costs, and forward testing.

---

# 2. CORE PRINCIPLE

Trader Machine is NOT a prediction machine.

It must never assume:

"price will go up"

or:

"price will go down"

without measurable evidence.

The system must instead determine:

1. What is directly observed?
2. What is derived mathematically?
3. What is inferred probabilistically?
4. What is unknown?

NEVER confuse inference with observation.

Use these labels where appropriate:

OBSERVED
DERIVED
INFERRED
UNKNOWN

Example:

Correct:

"Tick activity is 2.4 standard deviations above baseline."

Incorrect:

"A bank is buying heavily."

The second statement cannot be made unless the system actually possesses data proving it.

---

# 3. TRADING PHILOSOPHY

Trader Machine behaves like a SNIPER.

WAIT is a valid and expected decision.

The system must NOT trade simply because the market is open.

The preferred behavior is:

OBSERVE
→ WATCH
→ ARMED
→ FIRE

If conditions deteriorate:

WATCH
→ WAIT

or:

ARMED
→ WAIT

The system must be comfortable doing nothing.

Trade frequency is NOT a performance metric.

Quality of opportunities is more important than quantity.

---

# 4. FUNDAMENTAL MARKET LAWS

These laws form the DNA of Trader Machine.

## LAW #1 — PRICE RESPONSE

Price is the result of transactions, not the explanation itself.

The system must compare transaction/activity effort against resulting price movement.

Large effort with disproportionately small result is an anomaly candidate.

Do not automatically interpret it as reversal.

---

## LAW #2 — LIQUIDITY

Liquidity is not merely support/resistance.

The system must study:

* where liquidity is likely concentrated
* whether liquidity is approached
* touched
* swept
* rejected
* accepted
* invalidated

A liquidity sweep is NOT automatically a reversal.

The critical question is:

"What happened AFTER liquidity was taken?"

---

## LAW #3 — MARKET STRUCTURE

Structure is more important than individual candle appearance.

Track:

HH
HL
LH
LL
BOS
CHoCH

Maintain multiple structural contexts:

Macro
Context
Execution

Initial hierarchy:

H1 = Macro
M15 = Context
M5 = Confirmation
M1 = Execution
Tick = Microstructure

Microstructure must never be interpreted without macro/context awareness.

---

## LAW #4 — EFFORT VS RESULT

Compare market activity against price response.

Large effort + small result:

possible absorption / exhaustion / opposing pressure

Large effort + opposite result:

stronger anomaly candidate

Never claim identification of a specific institution without direct evidence.

---

## LAW #5 — ANOMALY

The system must detect abnormal behavior relative to a rolling market baseline.

Potential baselines include:

* volatility
* spread
* tick activity
* movement speed
* candle range
* price response
* structure behavior

Anomaly means:

STOP AND INVESTIGATE

It does NOT automatically mean:

BUY

or:

SELL

---

## LAW #6 — FAILED EXPECTATION

If market behavior produces a consequence that is significantly different from what the current structure implies, classify it as a failed expectation candidate.

Example:

Breakout expected to continue.

Actual:

Breakout → no acceptance → return → structural failure.

This can become a trap/reversal candidate.

---

## LAW #7 — CONFLUENCE

Never enter from one isolated observation.

A setup should be supported by multiple relevant pieces of evidence.

Possible evidence:

Liquidity
Price response
Structure
Anomaly
Trap behavior
Regime
Confirmation
Execution quality

Do NOT treat ten correlated indicators as ten independent confirmations.

---

## LAW #8 — MARKET REGIME

Every setup must be evaluated within its market regime.

Possible regimes:

TREND_UP
TREND_DOWN
RANGE
COMPRESSION
EXPANSION
TRANSITION
HIGH_VOLATILITY
LOW_VOLATILITY

A setup must never be evaluated without recording its regime.

---

## LAW #9 — STATISTICAL TRUTH

Historical performance must be measured.

Important metrics include:

* sample size
* win rate
* average win R
* average loss R
* expectancy
* profit factor
* maximum drawdown
* consecutive losses
* MAE
* MFE
* Sharpe/Sortino where appropriate
* spread cost
* commission
* slippage
* latency
* regime dependency
* session dependency
* out-of-sample performance

A high win rate alone does NOT establish an edge.

Never optimize specifically to achieve a predetermined win rate.

---

## LAW #10 — CAPITAL PRESERVATION

Risk Engine is a hard firewall.

It can veto any signal.

Potential veto conditions:

* maximum risk per trade exceeded
* daily loss limit exceeded
* consecutive loss limit exceeded
* maximum exposure exceeded
* correlated exposure exceeded
* abnormal spread
* abnormal slippage
* abnormal latency
* news restriction
* system health failure

No model prediction can override Risk Engine.

---

## LAW #11 — WAIT

WAIT is a first-class system decision.

The machine is not rewarded for being active.

It is rewarded for only taking validated opportunities.

---

# 5. INITIAL SETUPS

Trader Machine V1 initially studies five setup archetypes.

S01 — Liquidity Sweep Reversal

S02 — Liquidity Acceptance Continuation

S03 — Failed Breakout Trap

S04 — Effort vs Result Anomaly

S05 — Compression → Expansion

These are RESEARCH hypotheses.

None are assumed profitable.

If historical evidence shows that a setup has no robust edge, it must be removed or redesigned.

---

# 6. SETUP STATE MACHINE

All setups must follow:

OBSERVE
→ WATCH
→ ARMED
→ FIRE

Possible transitions:

OBSERVE → WATCH

WATCH → ARMED

WATCH → WAIT

ARMED → FIRE

ARMED → WAIT

FIRE → COMPLETED

Every setup must have:

* setup ID
* timestamp
* symbol
* direction
* regime
* evidence
* invalidation
* expiration
* entry definition
* stop-loss definition
* target definition
* risk status

Setups must expire if confirmation does not occur within their defined validity window.

---

# 7. INITIAL MATHEMATICAL PARAMETERS

These parameters are V1 research parameters.

They MUST NOT be treated as proven optimal values.

They must later be evaluated through historical testing and robust validation.

ATR:

ATR(14)

Initial timeframes:

H1
M15
M5
M1

Baseline window:

100 periods

Initial anomaly thresholds:

activity z-score >= 2.0

strong anomaly:

activity z-score >= 2.5

Initial sweep penetration:

minimum:
0.05 × ATR_M5

maximum:
0.50 × ATR_M5

Initial structure displacement:

0.10 × ATR_M5

Initial rejection displacement:

0.30 × ATR_M5

Initial compression duration:

10 M5 candles

Initial compression percentile:

ATR <= 20th percentile

Initial expansion:

current range >= 1.5 × median range

These are research parameters.

Do NOT silently change them.

Any parameter change must be documented.

---

# 8. S01 — LIQUIDITY SWEEP REVERSAL

Concept:

LIQUIDITY
→ SWEEP
→ REJECTION
→ FAILED EXPECTATION
→ STRUCTURE SHIFT
→ CONFIRMATION
→ FIRE

Liquidity candidates:

* Previous Day High
* Previous Day Low
* Previous Week High
* Previous Week Low
* Session High
* Session Low
* Equal High
* Equal Low
* Significant Swing High
* Significant Swing Low

Sweep:

Price must penetrate liquidity by:

0.05 × ATR_M5 minimum

and:

0.50 × ATR_M5 maximum

Then return across the liquidity level.

Return window:

maximum 3 M5 candles.

Rejection displacement:

> = 0.30 × ATR_M5

Structure confirmation:

Break of relevant M5 swing structure.

Minimum structural displacement:

0.10 × ATR_M5

FIRE requires:

Liquidity Sweep
AND Rejection
AND Failed Expectation
AND Structure Shift
AND acceptable spread
AND acceptable execution conditions
AND Risk Engine approval

Entry:

market entry after structure confirmation.

Initial target research:

2R

Do not assume 2R is optimal.

---

# 9. S02 — LIQUIDITY ACCEPTANCE CONTINUATION

Concept:

BREAK
→ ACCEPTANCE
→ FOLLOW THROUGH
→ STRUCTURE CONTINUATION
→ FIRE

Break:

close outside liquidity level.

Minimum break distance:

0.10 × ATR_M5

Acceptance:

minimum 2 M5 candles maintaining price on breakout side

OR equivalent validated displacement.

Follow-through:

additional directional displacement >= 0.30 × ATR_M5

Immediate return through the breakout level invalidates acceptance.

FIRE requires:

Break
AND Acceptance
AND Follow-through
AND Structure confirmation
AND Risk approval
AND execution conditions acceptable.

A wick outside a level is NOT sufficient.

---

# 10. S03 — FAILED BREAKOUT TRAP

Concept:

BREAKOUT
→ FAILURE
→ RETURN
→ STRUCTURE SHIFT
→ REVERSAL

Break:

close outside level

minimum:

0.10 × ATR_M5

Failure:

price returns through breakout level within maximum 3 M5 candles.

Opposite displacement:

> = 0.30 × ATR_M5

Structure:

opposite M5 structure break.

Only then may the setup become FIRE-eligible.

---

# 11. S04 — EFFORT VS RESULT ANOMALY

The system must NOT claim institutional order flow from tick activity alone.

Effort-related observations:

* tick activity
* movement speed
* activity z-score

Result:

price movement relative to ATR.

Anomaly candidate:

activity z-score >= 2.0

AND

price response significantly below expected baseline.

Strong anomaly:

activity z-score >= 2.5

AND

price response z-score <= -1.5

Anomaly alone is NOT an entry.

S04 requires additional context:

Liquidity interaction
OR
Structure failure
OR
Failed expectation

plus confirmation.

---

# 12. S05 — COMPRESSION → EXPANSION

Compression:

ATR percentile <= 20%

AND

range percentile <= 25%

AND

minimum duration 10 M5 candles.

Expansion:

current range >= 1.5 × median range

AND

volatility z-score >= 1.5

Direction requires:

Liquidity break
AND
Structure confirmation
AND
Acceptance
AND
Follow-through

Expansion alone is NOT a signal.

---

# 13. OBSERVED / DERIVED / INFERRED DATA

Every feature should have a classification.

Examples:

OBSERVED:

bid
ask
spread
tick
timestamp
OHLC
tick volume

DERIVED:

ATR
z-score
sweep depth
movement speed
structure
distance to liquidity

INFERRED:

possible absorption
possible trap
probability of continuation
probability of reversal

UNKNOWN:

specific bank participation
global institutional order flow
exact identity of market participants

The system must never convert UNKNOWN into fact.

---

# 14. DATA ARCHITECTURE

Initial database:

PostgreSQL

Core tables:

market_ticks
market_candles
market_features
liquidity_levels
market_structure
market_regimes
market_anomalies
market_events
setups
setup_evidence
signals
risk_events
orders
trades
trade_metrics
model_predictions
model_versions
system_health
decision_log
regret_events

Database design must prioritize:

* integrity
* timestamps
* reproducibility
* versioning
* auditability

Never overwrite historical research data destructively.

---

# 15. DECISION LOG

Every meaningful decision must be explainable.

For each setup/signal store:

market state
observations
derived features
evidence
setup
decision
risk result
model version
timestamp

The system must be able to answer:

"Why did the machine WAIT?"

and:

"Why did the machine FIRE?"

---

# 16. RISK FIREWALL

Risk logic must be isolated from strategy logic.

Strategy proposes.

Risk Engine approves or rejects.

Flow:

SETUP
→ SIGNAL
→ RISK FIREWALL
→ FIRE / REJECT

Never allow a strategy module to directly bypass Risk Engine.

Never allow an AI model to directly execute a broker order.

---

# 17. EXECUTION SAFETY

During development:

REAL TRADING = DISABLED

Any live-trading implementation must include an explicit environment gate.

Examples:

ENVIRONMENT=RESEARCH
ENVIRONMENT=DEMO
ENVIRONMENT=LIVE

Default:

RESEARCH

LIVE must require deliberate configuration.

Never default to LIVE.

---

# 18. AI AGENT DEVELOPMENT RULES

The AI coding agent must behave as an engineering agent, not an improvisational coder.

Before changing code:

1. Understand architecture.
2. Identify root cause.
3. Identify affected modules.
4. Check dependencies.
5. Plan minimal change.
6. Implement.
7. Run relevant tests.
8. Run regression tests.
9. Review side effects.
10. Report results.

Do NOT make random broad refactors.

Do NOT rewrite functioning systems unnecessarily.

Do NOT change APIs without checking dependencies.

Do NOT silently change business/trading logic.

---

# 19. NO-BREAK POLICY

When fixing one issue, the agent MUST verify that other functionality remains intact.

Required process:

BUG
→ ROOT CAUSE
→ IMPACT ANALYSIS
→ MINIMAL FIX
→ UNIT TEST
→ INTEGRATION TEST
→ REGRESSION TEST
→ AUDIT

Before declaring success, report:

ROOT CAUSE

FILES CHANGED

WHY THEY WERE CHANGED

TESTS RUN

REGRESSION STATUS

POTENTIAL SIDE EFFECTS

---

# 20. UNKNOWN POLICY

If the agent does not know something:

DO NOT GUESS.

Mark:

UNKNOWN

Then determine whether the missing information can be measured, researched, or safely approximated.

Never fabricate:

* market data
* broker behavior
* institutional activity
* trading performance
* historical results
* win rates
* probabilities

---

# 21. RESEARCH INTEGRITY

Never modify historical results to improve performance.

Never remove losing trades simply because they look inconvenient.

Never cherry-pick dates.

Never optimize and evaluate on the same dataset without separation.

Research must eventually include:

TRAIN / IN-SAMPLE

VALIDATION

OUT-OF-SAMPLE

WALK-FORWARD

FORWARD DEMO

Performance claims must state which dataset produced them.

---

# 22. OVERFITTING CONTROL

Avoid excessive parameters.

Every feature and parameter must have a reason.

Do not create hundreds of redundant indicators.

Prefer:

high information density
low redundancy

A feature should be removed if it does not add useful information.

Do not optimize thousands of combinations simply to find the highest backtest result.

---

# 23. TESTING REQUIREMENTS

Every important module must have tests.

Minimum categories:

Unit tests
Integration tests
Data validation tests
Strategy tests
Risk tests
Execution simulation tests
Regression tests

Tests must include edge cases.

Examples:

* missing tick
* duplicate tick
* abnormal spread
* market gap
* zero volume
* insufficient history
* disconnected MT5
* stale data
* duplicate order
* execution timeout
* database failure

---

# 24. CURRENT DEVELOPMENT PHASE

Current phase:

PHASE 0 — FOUNDATION

We are NOT yet implementing:

* live trading
* real money execution
* AI model training
* VPS deployment

First objectives:

1. Inspect development environment.
2. Verify Python.
3. Verify Git.
4. Verify MetaTrader 5.
5. Verify Python-to-MT5 connectivity.
6. Create project structure.
7. Create PostgreSQL schema.
8. Build data ingestion.
9. Validate data integrity.
10. Build features.
11. Build S01–S05 detectors.
12. Historical research.
13. Backtesting.
14. Statistical validation.
15. Only then consider AI/modeling.
16. Only then consider execution.

---

# 25. FIRST TASK FOR THE AGENT

DO NOT BUILD THE TRADING SYSTEM YET.

DO NOT WRITE STRATEGY EXECUTION CODE YET.

DO NOT CONNECT TO LIVE TRADING.

DO NOT CREATE AN EA THAT CAN PLACE REAL ORDERS.

First perform an ENVIRONMENT AUDIT.

Inspect:

* operating system
* CPU
* RAM
* Python availability/version
* pip
* Git
* MetaTrader 5 installation
* MT5 terminal status
* available EURUSD symbol
* Python MT5 package availability
* PostgreSQL availability
* Docker availability
* Node.js availability
* available disk space

Then report:

ENVIRONMENT AUDIT

For each component:

STATUS: PASS / FAIL / MISSING / UNKNOWN

VERSION:

PATH:

NOTES:

Then provide:

1. What is already ready.
2. What is missing.
3. What must be installed.
4. What is optional.
5. What should NOT be installed yet.
6. Any compatibility issues.

Do NOT install software automatically without reporting first.

Do NOT modify system configuration unnecessarily.

STOP after the environment audit and wait for approval before installing or creating the project infrastructure.

---

# 26. ABSOLUTE RULE

The agent must optimize for:

CORRECTNESS
REPRODUCIBILITY
ROBUSTNESS
SAFETY
EXPLAINABILITY

NOT:

SPEED
CODE VOLUME
NUMBER OF FEATURES
NUMBER OF TRADES
BACKTEST PROFIT

The project succeeds only if the evidence supports the hypothesis.

If the evidence says there is no edge:

REPORT IT.

Do not manufacture an edge.

END OF MASTER INSTRUCTION
