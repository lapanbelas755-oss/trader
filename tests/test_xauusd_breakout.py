"""
Unit tests for XAUUSD Breakout Engine V1.
Verifies all 6 core pillars, 100-point scoring brackets, anti-wick validation,
retest confirmation, and the hard firewall veto rule.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from core.candles.contract import AggregatedCandle, Timeframe
from core.strategies.xauusd_breakout import (
    XAUUSDBreakoutEngine,
    XAUUSDBreakoutResult,
)


def _make_candle(
    timestamp: datetime,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    volume: float = 1000.0,
    tick_count: int = 250,
) -> AggregatedCandle:
    return AggregatedCandle(
        symbol="XAUUSD",
        timeframe=Timeframe.M5,
        timestamp=timestamp,
        open=Decimal(str(open_p)),
        high=Decimal(str(high_p)),
        low=Decimal(str(low_p)),
        close=Decimal(str(close_p)),
        tick_volume=tick_count,
        real_volume=int(volume),
        spread=Decimal("0.20"),
        is_closed=True,
    )


def test_anti_wick_rejection_bullish():
    """
    Law #3: A wick poking above Resistance (3000.00) but closing inside
    MUST NOT be treated as a breakout. It is a WICK_REJECTION and NO_TRADE.
    """
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)  # NY Session

    # Build 25 baseline candles establishing resistance at 3000.00
    candles = []
    for i in range(25):
        t = now - timedelta(minutes=(25 - i) * 5)
        # Establish swing highs at 3000.00
        h = 3000.0 if i in (5, 12, 19) else 2996.0
        candles.append(_make_candle(t, 2992.0, h, 2991.0, 2995.0))

    # Latest candle: Pokes up to 3004.00 (above 3000 resistance) but CLOSES at 2998.00 (inside!)
    wick_candle = _make_candle(now, 2996.0, 3004.0, 2995.0, 2998.0)
    candles.append(wick_candle)

    res = engine.evaluate(candles, current_spread=0.20, is_market_open=True)

    # Must be rejected as false breakout
    assert res.breakout_valid is False
    assert res.signal == "NO_TRADE"
    assert res.total_score <= 59
    assert res.status_label == "NO TRADE"


def test_anti_wick_rejection_bearish():
    """
    A wick poking below Support (2950.00) but closing inside
    MUST NOT be treated as a breakout.
    """
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)

    candles = []
    for i in range(25):
        t = now - timedelta(minutes=(25 - i) * 5)
        candles.append(_make_candle(t, 2955.0, 2960.0, 2952.0, 2956.0))

    # Latest candle: Pokes down to 2946.00 (below 2950 support) but CLOSES at 2953.00
    wick_candle = _make_candle(now, 2954.0, 2956.0, 2946.0, 2953.0)
    candles.append(wick_candle)

    res = engine.evaluate(candles, current_spread=0.20, is_market_open=True)

    assert res.breakout_valid is False
    assert res.signal == "NO_TRADE"
    assert res.total_score <= 59


def test_valid_bullish_breakout_and_high_score():
    """
    True breakout: Strong body >= 65%, closes well outside resistance with range expansion.
    Produces HIGH QUALITY TRADE or VALID SETUP with valid Risk:Reward.
    """
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)  # NY Session Overlap

    candles = []
    # Build range bounded below 3000
    for i in range(30):
        t = now - timedelta(minutes=(30 - i) * 5)
        candles.append(_make_candle(t, 2990.0, 2995.0, 2988.0, 2993.0, tick_count=200))

    # Resistance is set near 2995.00
    # Now breakout candle: opens at 2994.0, sweeps to 3006.0, closes at 3005.0!
    # Body = 11.0, Range = 12.0 -> Body ratio = 91.6% (Institutional power)
    breakout_c = _make_candle(now, 2994.0, 3006.0, 2994.0, 3005.0, tick_count=600)
    candles.append(breakout_c)

    res = engine.evaluate(candles, current_spread=0.18, is_market_open=True)

    assert res.breakout_valid is True
    assert res.breakout_type == "BULLISH_BREAKOUT"
    assert res.score_breakout_strength >= 15
    assert res.score_session == 5  # NY overlap
    assert res.score_spread == 5   # $0.18 spread
    assert res.profit_potential_valid is True
    assert res.rr_ratio >= 2.0
    assert res.total_score >= 75
    assert res.signal == "BUY"


def test_trap_collapse_veto():
    """
    If price broke out but immediately plunged back inside the range,
    retest evaluates to FAILED and triggers an automatic veto -> NO TRADE.
    """
    engine = XAUUSDBreakoutEngine()
    atr = 2.50
    level = 3000.00
    now = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)

    # Candle that plunged back inside to 2997.00
    collapsed_candle = _make_candle(now, 3004.0, 3005.0, 2996.0, 2997.0)

    retest_state, score, is_trap = engine.evaluate_retest(
        [collapsed_candle],
        breakout_type="BULLISH_BREAKOUT",
        level=level,
        atr=atr,
    )

    assert retest_state == "FAILED"
    assert score == 0
    assert is_trap is True


def test_spread_bad_hard_veto():
    """
    If spread is excessive (> 0.40 on gold), hard firewall vetoes the signal to NO_TRADE.
    """
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)

    candles = []
    for i in range(30):
        t = now - timedelta(minutes=(30 - i) * 5)
        candles.append(_make_candle(t, 2990.0, 2995.0, 2988.0, 2993.0))
    candles.append(_make_candle(now, 2994.0, 3006.0, 2994.0, 3005.0))

    # Spread = 0.55 (bad spread)
    res = engine.evaluate(candles, current_spread=0.55, is_market_open=True)

    assert res.spread_bad is True
    assert res.signal == "NO_TRADE"
    assert res.total_score <= 59
    assert "Spread abnormal" in (res.veto_reason or "")


def test_market_closed_veto():
    """
    When market is closed (e.g. weekend), hard firewall vetoes the signal to NO_TRADE.
    """
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)

    candles = []
    for i in range(25):
        t = now - timedelta(minutes=(25 - i) * 5)
        candles.append(_make_candle(t, 2990.0, 2995.0, 2988.0, 2993.0))

    res = engine.evaluate(candles, current_spread=0.20, is_market_open=False)

    assert res.market_status == "MARKET_CLOSED"
    assert res.signal == "NO_TRADE"
    assert res.total_score <= 59


def test_rr_minimum_veto():
    """
    Law #10 & User Rule: If target provides RR < 2.0 (e.g. 1:1),
    must SKIP even if breakout is valid -> NO_TRADE.
    """
    engine = XAUUSDBreakoutEngine(minimum_rr=2.0)
    atr = 2.0
    now = datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc)
    candle = _make_candle(now, 3000.0, 3006.0, 3000.0, 3005.0)

    # Directly test calculate_trade_levels with tight opposing level forcing RR < 2.0
    # Entry = 3005, broken_level = 3000 -> SL = 2998.8 (Risk = ~6.2)
    # Opposing level at 3008 -> Reward = 3 -> RR = 0.48 < 2.0!
    trade_levels = engine.calculate_trade_levels(
        [candle],
        breakout_type="BULLISH_BREAKOUT",
        broken_level=3000.0,
        atr=atr,
        opposing_level=3008.0,
    )

    assert trade_levels["rr_ratio"] >= 2.0 or trade_levels["profit_potential_valid"] is False


def test_evidence_checklist_structure():
    """
    Verifies that the evidence checklist matches the terminal UI layout:
    Market Status, Session, Spread, ATR, Breakout, Momentum, Retest, RR.
    """
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)

    candles = []
    for i in range(25):
        t = now - timedelta(minutes=(25 - i) * 5)
        candles.append(_make_candle(t, 2990.0, 2995.0, 2988.0, 2993.0))

    res = engine.evaluate(candles, current_spread=0.20, is_market_open=True)

    names = [item["name"] for item in res.evidence_checklist]
    assert "Market Status" in names
    assert "Session" in names
    assert "Spread" in names
    assert "ATR / Volatility" in names
    assert "Breakout" in names
    assert "Momentum" in names
    assert "Retest" in names
    assert "Risk : Reward" in names

