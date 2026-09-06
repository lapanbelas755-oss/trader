"""
Trader Machine — XAUUSD Backtest & Score-Bracket Analytics Engine V1.
Strict mathematical backtesting and edge discovery engine for Gold Breakouts.

Adheres strictly to Master Instruction (AGENTS.MD Law #9, #21) & User Specification (Section N):
1. Analyzes whether higher breakout scores produce higher expectancy.
2. Segregates performance across score brackets:
   - Score 60-69
   - Score 70-79
   - Score 80-89
   - Score 90-100
3. Measures false breakout rate, continuation rate, session dependency, and ATR regime dependency.
"""

from dataclasses import dataclass, field
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional

from core.candles.contract import AggregatedCandle
from core.strategies.xauusd_breakout import (
    XAUUSDBreakoutEngine,
    XAUUSDBreakoutResult,
    XAUUSDConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class TradeOutcome:
    """Historical trade simulation outcome."""
    index: int
    timestamp: str
    symbol: str
    direction: str
    score: int
    score_bracket: str
    session: str
    atr_regime: str
    breakout_category: str
    retest_state: str
    entry: float
    sl: float
    tp: float
    rr_target: float
    exit_price: float
    r_multiple: float
    outcome: str               # WIN | LOSS | TIMEOUT
    holding_candles: int


@dataclass
class PerformanceMetrics:
    """Consolidated performance statistics for a cohort of setups."""
    total_samples: int = 0
    trades_taken: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    win_rate: float = 0.0
    average_r: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_r: float = 0.0
    average_winner_r: float = 0.0
    average_loser_r: float = 0.0
    gross_win_r: float = 0.0
    gross_loss_r: float = 0.0


@dataclass
class XAUUSDBacktestReport:
    """Complete analytical report of XAU/USD Breakout Backtesting."""
    total_candles_evaluated: int = 0
    total_setups_observed: int = 0
    total_no_trades: int = 0
    total_trades_taken: int = 0
    
    false_breakouts_detected: int = 0
    breakout_attempts: int = 0
    false_breakout_rate: float = 0.0
    breakout_continuation_rate: float = 0.0
    
    overall_metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    by_score_range: Dict[str, PerformanceMetrics] = field(default_factory=dict)
    by_session: Dict[str, PerformanceMetrics] = field(default_factory=dict)
    by_atr_regime: Dict[str, PerformanceMetrics] = field(default_factory=dict)
    by_category: Dict[str, PerformanceMetrics] = field(default_factory=dict)
    
    trades: List[TradeOutcome] = field(default_factory=list)


class XAUUSDBacktestEngine:
    """
    Simulates XAUUSD Breakout Engine forward in time candle-by-candle.
    Ensures zero forward-looking bias.
    """

    def __init__(
        self,
        config: Optional[XAUUSDConfig] = None,
        max_holding_candles: int = 24,  # Up to 2 hours on M5 candles
    ):
        self.cfg = config or XAUUSDConfig()
        self.engine = XAUUSDBreakoutEngine(config=self.cfg)
        self.max_holding_candles = max_holding_candles

    def run(
        self,
        candles: List[AggregatedCandle],
        min_score_to_trade: int = 60,  # Evaluate all WATCH, VALID, and HIGH QUALITY setups
    ) -> XAUUSDBacktestReport:
        """
        Executes backtest over historical candles.
        Calculates performance segregated by score brackets: 60-69, 70-79, 80-89, 90-100.
        """
        report = XAUUSDBacktestReport()
        # Ensure all candles are validated AggregatedCandle models
        converted = [self.engine._ensure_candle(c) for c in (candles or [])]
        candles = [c for c in converted if c is not None]
        report.total_candles_evaluated = len(candles)

        if len(candles) < 30:
            return report

        breakout_attempts = 0
        false_breakouts = 0
        all_trades: List[TradeOutcome] = []

        # Iterate candle by candle with strict lookback
        for i in range(25, len(candles) - 1):
            eval_slice = candles[: i + 1]
            res: XAUUSDBreakoutResult = self.engine.evaluate(
                eval_slice,
                current_spread=0.20,
                is_market_open=True,
            )
            report.total_setups_observed += 1

            if res.signal == "NO_TRADE":
                report.total_no_trades += 1

            # Track breakout attempts and false breakouts
            if res.breakout_category in ("WICK_BREAKOUT", "WEAK_BREAKOUT", "VALID_BREAKOUT", "STRONG_BREAKOUT"):
                breakout_attempts += 1
                if res.breakout_category in ("WICK_BREAKOUT", "WEAK_BREAKOUT") or res.retest_state == "FAILED":
                    false_breakouts += 1

            # Simulate trades for any setup with score >= min_score_to_trade and valid direction
            direction = res.breakout_type.replace("_BREAKOUT", "")
            if res.total_score >= min_score_to_trade and direction in ("BULLISH", "BEARISH"):
                # Forward simulate from candle i+1 to outcome
                outcome = self._simulate_forward(
                    candles=candles,
                    start_index=i,
                    direction=direction,
                    entry=res.entry,
                    sl=res.stop_loss,
                    tp=res.take_profit,
                    score=res.total_score,
                    session=res.session,
                    atr_regime=res.atr_state,
                    breakout_category=res.breakout_category,
                    retest_state=res.retest_state,
                )
                if outcome:
                    all_trades.append(outcome)

        report.breakout_attempts = breakout_attempts
        report.false_breakouts_detected = false_breakouts
        if breakout_attempts > 0:
            report.false_breakout_rate = round(false_breakouts / breakout_attempts, 3)
            report.breakout_continuation_rate = round(1.0 - report.false_breakout_rate, 3)

        report.trades = all_trades
        report.total_trades_taken = len(all_trades)

        # Compute metrics across cohorts
        report.overall_metrics = self._compute_metrics(all_trades)

        # Score brackets requested:
        # Score 60-69, Score 70-79, Score 80-89, Score 90-100
        score_cohorts = {
            "Score 60-69": [t for t in all_trades if 60 <= t.score < 70],
            "Score 70-79": [t for t in all_trades if 70 <= t.score < 80],
            "Score 80-89": [t for t in all_trades if 80 <= t.score < 90],
            "Score 90-100": [t for t in all_trades if 90 <= t.score <= 100],
        }
        for name, cohort in score_cohorts.items():
            report.by_score_range[name] = self._compute_metrics(cohort)

        # Session cohorts
        sessions = set(t.session for t in all_trades)
        for s in sessions:
            cohort = [t for t in all_trades if t.session == s]
            report.by_session[s] = self._compute_metrics(cohort)

        # ATR regime cohorts
        regimes = set(t.atr_regime for t in all_trades)
        for r in regimes:
            cohort = [t for t in all_trades if t.atr_regime == r]
            report.by_atr_regime[r] = self._compute_metrics(cohort)

        # Breakout category cohorts
        categories = set(t.breakout_category for t in all_trades)
        for c in categories:
            cohort = [t for t in all_trades if t.breakout_category == c]
            report.by_category[c] = self._compute_metrics(cohort)

        return report

    def _simulate_forward(
        self,
        candles: List[AggregatedCandle],
        start_index: int,
        direction: str,
        entry: float,
        sl: float,
        tp: float,
        score: int,
        session: str,
        atr_regime: str,
        breakout_category: str,
        retest_state: str,
    ) -> Optional[TradeOutcome]:
        """Simulates path of trade until TP, SL, or timeout."""
        risk_dist = abs(entry - sl)
        if risk_dist <= 0:
            return None

        reward_dist = abs(tp - entry)
        rr_target = round(reward_dist / risk_dist, 2)

        score_bracket = (
            "Score 90-100" if score >= 90 else
            "Score 80-89" if score >= 80 else
            "Score 70-79" if score >= 70 else "Score 60-69"
        )

        end_idx = min(len(candles), start_index + 1 + self.max_holding_candles)
        holding = 0

        for idx in range(start_index + 1, end_idx):
            holding += 1
            c = candles[idx]
            c_high = float(c.high)
            c_low = float(c.low)
            c_close = float(c.close)

            if direction == "BULLISH":
                # Check SL hit
                if c_low <= sl:
                    return TradeOutcome(
                        index=start_index,
                        timestamp=candles[start_index].timestamp.isoformat(),
                        symbol=self.cfg.symbol,
                        direction="BUY",
                        score=score,
                        score_bracket=score_bracket,
                        session=session,
                        atr_regime=atr_regime,
                        breakout_category=breakout_category,
                        retest_state=retest_state,
                        entry=entry,
                        sl=sl,
                        tp=tp,
                        rr_target=rr_target,
                        exit_price=sl,
                        r_multiple=-1.0,
                        outcome="LOSS",
                        holding_candles=holding,
                    )
                # Check TP hit
                if c_high >= tp:
                    return TradeOutcome(
                        index=start_index,
                        timestamp=candles[start_index].timestamp.isoformat(),
                        symbol=self.cfg.symbol,
                        direction="BUY",
                        score=score,
                        score_bracket=score_bracket,
                        session=session,
                        atr_regime=atr_regime,
                        breakout_category=breakout_category,
                        retest_state=retest_state,
                        entry=entry,
                        sl=sl,
                        tp=tp,
                        rr_target=rr_target,
                        exit_price=tp,
                        r_multiple=rr_target,
                        outcome="WIN",
                        holding_candles=holding,
                    )
            else:  # BEARISH
                # Check SL hit
                if c_high >= sl:
                    return TradeOutcome(
                        index=start_index,
                        timestamp=candles[start_index].timestamp.isoformat(),
                        symbol=self.cfg.symbol,
                        direction="SELL",
                        score=score,
                        score_bracket=score_bracket,
                        session=session,
                        atr_regime=atr_regime,
                        breakout_category=breakout_category,
                        retest_state=retest_state,
                        entry=entry,
                        sl=sl,
                        tp=tp,
                        rr_target=rr_target,
                        exit_price=sl,
                        r_multiple=-1.0,
                        outcome="LOSS",
                        holding_candles=holding,
                    )
                # Check TP hit
                if c_low <= tp:
                    return TradeOutcome(
                        index=start_index,
                        timestamp=candles[start_index].timestamp.isoformat(),
                        symbol=self.cfg.symbol,
                        direction="SELL",
                        score=score,
                        score_bracket=score_bracket,
                        session=session,
                        atr_regime=atr_regime,
                        breakout_category=breakout_category,
                        retest_state=retest_state,
                        entry=entry,
                        sl=sl,
                        tp=tp,
                        rr_target=rr_target,
                        exit_price=tp,
                        r_multiple=rr_target,
                        outcome="WIN",
                        holding_candles=holding,
                    )

        # If holding period exceeded without hitting TP or SL
        final_close = float(candles[end_idx - 1].close) if end_idx > start_index + 1 else entry
        if direction == "BULLISH":
            r_mult = round((final_close - entry) / risk_dist, 2)
        else:
            r_mult = round((entry - final_close) / risk_dist, 2)

        return TradeOutcome(
            index=start_index,
            timestamp=candles[start_index].timestamp.isoformat(),
            symbol=self.cfg.symbol,
            direction="BUY" if direction == "BULLISH" else "SELL",
            score=score,
            score_bracket=score_bracket,
            session=session,
            atr_regime=atr_regime,
            breakout_category=breakout_category,
            retest_state=retest_state,
            entry=entry,
            sl=sl,
            tp=tp,
            rr_target=rr_target,
            exit_price=final_close,
            r_multiple=r_mult,
            outcome="WIN" if r_mult > 0 else "LOSS",
            holding_candles=holding,
        )

    def _compute_metrics(self, trades: List[TradeOutcome]) -> PerformanceMetrics:
        """Computes statistical metrics (Win Rate, Expectancy, Profit Factor, DD)."""
        m = PerformanceMetrics()
        m.total_samples = len(trades)
        m.trades_taken = len(trades)
        if not trades:
            return m

        wins = [t for t in trades if t.r_multiple > 0]
        losses = [t for t in trades if t.r_multiple <= 0]
        m.wins = len(wins)
        m.losses = len(losses)

        m.win_rate = round(len(wins) / len(trades), 3)

        total_r = sum(t.r_multiple for t in trades)
        m.average_r = round(total_r / len(trades), 2)

        m.gross_win_r = round(sum(t.r_multiple for t in wins), 2)
        m.gross_loss_r = round(abs(sum(t.r_multiple for t in losses)), 2)

        m.average_winner_r = round(m.gross_win_r / len(wins), 2) if wins else 0.0
        m.average_loser_r = round(m.gross_loss_r / len(losses), 2) if losses else 0.0

        # Mathematical Expectancy: E = (WR * AvgWinR) - (LR * AvgLossR)
        loss_rate = 1.0 - m.win_rate
        m.expectancy = round((m.win_rate * m.average_winner_r) - (loss_rate * m.average_loser_r), 2)

        # Profit Factor: Gross Win R / Gross Loss R
        m.profit_factor = round(m.gross_win_r / m.gross_loss_r, 2) if m.gross_loss_r > 0 else 99.0

        # Max Drawdown in R multiples
        peak = 0.0
        cum = 0.0
        max_dd = 0.0
        for t in trades:
            cum += t.r_multiple
            if cum > peak:
                peak = cum
            dd = peak - cum
            if dd > max_dd:
                max_dd = dd
        m.max_drawdown_r = round(max_dd, 2)

        return m
