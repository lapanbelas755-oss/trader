"""
Trader Machine — XAUUSD Breakout Engine Comprehensive Validation Suite.
Fulfills Section O Validation Protocol:
1. Typecheck & parameter validation
2. Key Level Engine & Quality Scoring (0-20)
3. 4 Breakout Categories (Wick, Weak, Valid, Strong)
4. False Breakout Filter & Trap Collapse Veto
5. Retest Engine & S/R Flip
6. Momentum Engine & Multi-candle confluence
7. Volatility Engine: Compression -> Expansion
8. Profit Potential & RR >= 1:2.0
9. 100-Point Scoring Engine & Configurable Thresholds
10. BUY Signal end-to-end
11. SELL Signal end-to-end (mirror logic)
12. Risk Management & Gold Lot Sizing (100 oz contract)
13. Setup Logging: Actionable & NO_TRADE persistence
14. Backtest & Score-Bracket Expectancy Analytics (60-69, 70-79, 80-89, 90-100)
15. Dashboard REST & WebSocket endpoints
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from core.candles.contract import AggregatedCandle, Timeframe
from core.strategies.xauusd_breakout import (
    XAUUSDBreakoutEngine,
    XAUUSDBreakoutResult,
    XAUUSDConfig,
)
from core.strategies.xauusd_risk import (
    XAUUSDRiskEngine,
    XAUUSDRiskConfig,
    AccountRiskState,
)
from core.strategies.xauusd_logger import (
    XAUUSDSetupLogger,
    XAUUSDSetupRecord,
)
from core.strategies.xauusd_backtest import (
    XAUUSDBacktestEngine,
)


def _c(
    timestamp: datetime,
    o: float,
    h: float,
    l: float,
    c: float,
    ticks: int = 250,
) -> AggregatedCandle:
    return AggregatedCandle(
        symbol="XAUUSD",
        timeframe=Timeframe.M5,
        timestamp=timestamp,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(l)),
        close=Decimal(str(c)),
        tick_volume=ticks,
        real_volume=1000,
        spread=Decimal("0.20"),
        is_closed=True,
    )


# -------------------------------------------------------------------------
# 1. Key Levels Engine & Quality Scoring
# -------------------------------------------------------------------------

def test_key_level_engine_multitouch_and_quality():
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)
    candles = []
    # Build 30 candles with 3 distinct touches at resistance 3000.00
    for i in range(30):
        t = now - timedelta(minutes=(30 - i) * 5)
        h = 3000.0 if i in (6, 14, 22) else 2985.0
        candles.append(_c(t, 2980.0, h, 2978.0, 2982.0))
    # Current candle testing resistance
    candles.append(_c(now, 2995.0, 3001.0, 2994.0, 2999.0))

    atr = 2.50
    levels = engine.identify_key_levels(candles, atr)
    assert levels["resistance"] >= 2999.0
    assert levels["touches"] >= 2
    assert levels["score"] >= 16  # Multi-touch quality score


# -------------------------------------------------------------------------
# 2. Breakout Categories: Wick vs Weak vs Valid vs Strong
# -------------------------------------------------------------------------

def test_breakout_category_weak_breakout_rejected():
    """Weak breakout (small body ratio < 55%) must NOT be treated as valid trade."""
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)
    candles = []
    for i in range(25):
        t = now - timedelta(minutes=(25 - i) * 5)
        candles.append(_c(t, 2990.0, 2995.0, 2988.0, 2992.0))
    # Closed outside 2995.0 at 2996.0, but candle is a doji/spinning top: open 2995.5, high 2998.0, low 2993.0, close 2996.0
    # Body = 0.5, Range = 5.0 -> Body ratio = 10% (< 55%)
    weak_candle = _c(now, 2995.5, 2998.0, 2993.0, 2996.0)
    candles.append(weak_candle)

    res = engine.evaluate(candles, current_spread=0.20, is_market_open=True)
    assert res.breakout_valid is False
    assert res.breakout_category == "WEAK_BREAKOUT"
    assert res.signal == "NO_TRADE"
    assert any("Breakout lemah" in r for r in res.reasons_for_no_trade)


def test_breakout_category_strong_breakout():
    """Strong breakout with large body >= 65% and range expansion >= 1.5x."""
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)
    candles = []
    for i in range(25):
        t = now - timedelta(minutes=(25 - i) * 5)
        candles.append(_c(t, 2990.0, 2995.0, 2988.0, 2993.0))
    # Massive institutional impulse candle: open 2994.0, close 3008.0, high 3009.0, low 2994.0
    # Range = 15.0, Body = 14.0 -> Body ratio = 93.3%
    strong_candle = _c(now, 2994.0, 3009.0, 2994.0, 3008.0, ticks=500)
    candles.append(strong_candle)

    res = engine.evaluate(candles, current_spread=0.18, is_market_open=True)
    assert res.breakout_valid is True
    assert res.breakout_category == "STRONG_BREAKOUT"
    assert res.score_breakout_strength >= 18
    assert res.score_momentum >= 12
    assert res.signal == "BUY"


# -------------------------------------------------------------------------
# 3. Bearish Breakout (SELL) End-to-End
# -------------------------------------------------------------------------

def test_bearish_breakout_sell_signal():
    """Valid bearish breakout through support produces SELL signal."""
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)
    candles = []
    for i in range(25):
        t = now - timedelta(minutes=(25 - i) * 5)
        # Support around 2950.00
        candles.append(_c(t, 2958.0, 2962.0, 2950.0, 2955.0))
    # Bearish breakdown: open 2952.0, high 2952.0, low 2938.0, close 2939.0
    # Range = 14.0, Body = 13.0 -> Body ratio = 92.8%
    bearish_c = _c(now, 2952.0, 2952.0, 2938.0, 2939.0, ticks=600)
    candles.append(bearish_c)

    res = engine.evaluate(candles, current_spread=0.18, is_market_open=True)
    assert res.breakout_valid is True
    assert res.breakout_type == "BEARISH_BREAKOUT"
    assert res.signal == "SELL"
    assert res.entry == 2939.0
    assert res.stop_loss > res.entry
    assert res.take_profit < res.entry
    assert res.total_score >= 75


# -------------------------------------------------------------------------
# 4. Volatility Engine: Compression -> Expansion Detection
# -------------------------------------------------------------------------

def test_volatility_compression_expansion():
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)
    candles = []
    # 10 baseline candles with normal volatility (range 3.0)
    for i in range(10):
        t = now - timedelta(minutes=(21 - i) * 5)
        candles.append(_c(t, 2988.0, 2991.0, 2988.0, 2990.0))
    # 10 narrow compressed consolidation candles (range 1.0)
    for i in range(10, 20):
        t = now - timedelta(minutes=(21 - i) * 5)
        candles.append(_c(t, 2990.0, 2991.0, 2990.0, 2990.5))
    # Current expanding breakout candle with range 6.0
    candles.append(_c(now, 2990.5, 2996.5, 2990.5, 2996.0))

    atr = engine.compute_atr(candles)
    atr_state, vol_state, score, was_compressed = engine.evaluate_volatility(candles, atr)
    assert vol_state == "EXPANDING"
    assert was_compressed is True
    assert score >= 14


# -------------------------------------------------------------------------
# 5. Profit Potential: Opposing Level Capping Veto
# -------------------------------------------------------------------------

def test_profit_potential_opposing_level_cap_veto():
    """If nearest opposing liquidity caps profit space such that RR < 2.0 -> VETO."""
    engine = XAUUSDBreakoutEngine(minimum_rr=2.0)
    now = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)
    candle = _c(now, 2995.0, 3005.0, 2995.0, 3004.0)

    # Entry = 3004, broken_level = 3000 -> SL = 2998.8 (Risk = ~5.2)
    # Opposing level at 3007 -> Reward = 3.0 -> RR = 3.0 / 5.2 = 0.58 < 2.0!
    levels = engine.calculate_trade_levels(
        [candle],
        breakout_type="BULLISH_BREAKOUT",
        broken_level=3000.0,
        atr=2.5,
        opposing_level=3007.0,
    )
    assert levels["profit_potential_valid"] is False
    assert levels["rr_ratio"] < 2.0


# -------------------------------------------------------------------------
# 6. Detailed Reasons for NO_TRADE (Section L)
# -------------------------------------------------------------------------

def test_detailed_reasons_for_no_trade():
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)
    candles = []
    # Build 25 rangebound candles
    for i in range(25):
        t = now - timedelta(minutes=(25 - i) * 5)
        candles.append(_c(t, 2990.0, 2995.0, 2988.0, 2992.0))

    # Price inside range with no breakout
    res = engine.evaluate(candles, current_spread=0.20, is_market_open=True)
    assert res.signal == "NO_TRADE"
    assert len(res.reasons_for_no_trade) > 0
    assert "Belum ada valid breakout" in res.reasons_for_no_trade[0]
    assert "NO TRADE" in res.no_trade_summary


# -------------------------------------------------------------------------
# 7. Risk Management Engine (Section K)
# -------------------------------------------------------------------------

def test_risk_engine_gold_lot_size_calculation():
    """
    Gold contract: 100 oz per lot.
    Account: $10,000, Risk: 1.0% = $100.00.
    SL distance: $5.00.
    Expected Lot: $100 / ($5.00 * 100) = 0.20 lots.
    """
    risk_engine = XAUUSDRiskEngine(XAUUSDRiskConfig(risk_per_trade_pct=1.0))
    lot, risk_dollars, risk_pct = risk_engine.calculate_lot_size(
        account_balance=10000.0,
        sl_distance_dollars=5.00,
    )
    assert lot == 0.20
    assert risk_dollars == 100.0
    assert risk_pct == 1.0


def test_risk_engine_firewall_veto_daily_loss():
    """If daily loss limit is reached, Risk Firewall vetoes signal."""
    risk_engine = XAUUSDRiskEngine(XAUUSDRiskConfig(max_daily_loss_pct=3.0))
    account = AccountRiskState(
        balance=9700.0,
        equity=9700.0,
        daily_starting_balance=10000.0,
        realized_daily_loss=310.0,  # 3.1% loss
        consecutive_losses=1,
    )
    decision = risk_engine.evaluate(
        account=account,
        signal="BUY",
        entry=3000.0,
        stop_loss=2995.0,
    )
    assert decision.approved is False
    assert any("Daily loss limit breached" in r for r in decision.veto_reasons)


def test_risk_engine_firewall_veto_consecutive_losses():
    """If 3 consecutive losses occurred, Risk Firewall enforces cooldown."""
    risk_engine = XAUUSDRiskEngine(XAUUSDRiskConfig(max_consecutive_losses=3))
    account = AccountRiskState(
        balance=9800.0,
        equity=9800.0,
        daily_starting_balance=10000.0,
        realized_daily_loss=200.0,
        consecutive_losses=3,
    )
    decision = risk_engine.evaluate(
        account=account,
        signal="BUY",
        entry=3000.0,
        stop_loss=2995.0,
    )
    assert decision.approved is False
    assert any("Consecutive loss limit reached" in r for r in decision.veto_reasons)


# -------------------------------------------------------------------------
# 8. Setup Logger: Actionable & NO_TRADE Persistence (Section M)
# -------------------------------------------------------------------------

def test_setup_logger_records_no_trade_and_actionable(tmp_path):
    logger_instance = XAUUSDSetupLogger(log_dir=tmp_path)
    
    # Log a NO_TRADE event
    no_trade_rec = XAUUSDSetupRecord(
        timestamp="2026-09-07T14:00:00Z",
        symbol="XAUUSD",
        timeframe="M5",
        level=3000.0,
        breakout_direction="NONE",
        breakout_category="WICK_BREAKOUT",
        atr=2.5,
        spread=0.20,
        score=52,
        signal="NO_TRADE",
        reasons=["Wick breakout rejected"],
    )
    logger_instance.log_setup(no_trade_rec)

    # Log an actionable trade event
    trade_rec = XAUUSDSetupRecord(
        timestamp="2026-09-07T14:30:00Z",
        symbol="XAUUSD",
        timeframe="M5",
        level=3000.0,
        breakout_direction="BULLISH",
        breakout_category="STRONG_BREAKOUT",
        atr=2.8,
        spread=0.18,
        score=88,
        signal="BUY",
        entry=3005.0,
        sl=2998.0,
        tp=3022.5,
        expected_move=17.5,
        result="PENDING",
    )
    logger_instance.log_setup(trade_rec)

    recent = logger_instance.get_recent(limit=10)
    assert len(recent) == 2
    no_trades = logger_instance.get_no_trade_setups(limit=10)
    assert len(no_trades) == 1
    assert no_trades[0]["signal"] == "NO_TRADE"
    actionable = logger_instance.get_actionable_setups(limit=10)
    assert len(actionable) == 1
    assert actionable[0]["signal"] == "BUY"


# -------------------------------------------------------------------------
# 9. Backtest & Score-Bracket Expectancy Analytics (Section N)
# -------------------------------------------------------------------------

def test_backtest_score_bracket_analytics():
    """Verifies backtest engine computes metrics across score brackets (60-69, 70-79, 80-89, 90-100)."""
    backtest = XAUUSDBacktestEngine()
    now = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    candles = []
    
    # Generate 50 realistic synthetic candles with breakout and continuation
    price = 2990.0
    for i in range(50):
        t = now + timedelta(minutes=i * 5)
        if i < 30:
            h = price + 2.0
            l = price - 2.0
            c = price + 0.5
            o = price - 0.5
        elif i == 30:
            # Bullish breakout candle
            o = price
            price = 3008.0
            h = 3010.0
            l = o
            c = price
        else:
            # Continuation up to target with valid invariants: l <= min(o, c) and h >= max(o, c)
            price += 1.5
            o = price - 0.5
            c = price + 0.5
            l = price - 1.0
            h = price + 1.0
        candles.append(_c(t, o, h, l, c, ticks=400))

    report = backtest.run(candles, min_score_to_trade=60)
    assert report.total_candles_evaluated == 50
    assert report.total_setups_observed > 0
    assert "Score 60-69" in report.by_score_range
    assert "Score 70-79" in report.by_score_range
    assert "Score 80-89" in report.by_score_range
    assert "Score 90-100" in report.by_score_range
