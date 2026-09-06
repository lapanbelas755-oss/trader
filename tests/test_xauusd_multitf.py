"""Unit tests for XAU/USD Multi-Timeframe Confluence Engine (H4 -> H1 -> M15 -> M5 -> M1).

Validates strict top-down confluence gates:
1. H4 barrier clearance (prevents buying into massive H4 resistance)
2. H4 macro trend alignment
3. M15 structure confirmation (BOS / CHoCH alignment)
4. M5 valid breakout trigger
5. M1 microstructure / retest rejection
6. Full 5-timeframe confluence approval
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from core.candles.contract import AggregatedCandle, Timeframe
from core.strategies.xauusd_breakout import XAUUSDBreakoutEngine
from core.strategies.xauusd_multitf import (
    CandleRecord,
    TrendBias,
    XAUUSDMultiTFConfluenceEngine,
)


def _c(t: datetime, o: float, h: float, l: float, c: float, vol: int = 100) -> CandleRecord:
    return CandleRecord(timestamp=t, open=o, high=h, low=l, close=c, volume=vol)


def _agg(t: datetime, o: float, h: float, l: float, c: float, ticks: int = 250) -> AggregatedCandle:
    return AggregatedCandle(
        symbol="XAUUSD",
        timeframe=Timeframe.M5,
        timestamp=t,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(l)),
        close=Decimal(str(c)),
        tick_volume=ticks,
        real_volume=ticks * 4,
        spread=Decimal("0.20"),
        is_closed=True,
    )


def test_h4_barrier_clearance_veto():
    """H4 Resistance directly above current price must veto the trade (NO_TRADE)."""
    mtf = XAUUSDMultiTFConfluenceEngine(min_barrier_clearance_atr_mult=1.5)
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)
    curr_price = 3000.0

    # Build H4 candles where a major resistance sits at 3001.50 (only $1.50 away)
    h4_candles = []
    for i in range(25):
        t = now - timedelta(hours=(25 - i) * 4)
        h4_candles.append(_c(t, 2980.0, 3001.50, 2975.0, 2990.0))

    # M5 candles
    m5_candles = [_c(now - timedelta(minutes=5), 2990.0, 2998.0, 2989.0, 2995.0),
                  _c(now, 2995.0, 3000.5, 2995.0, 3000.0)]

    res = mtf.evaluate(
        current_price=curr_price,
        breakout_direction="BULLISH",
        m1_candles=None,
        m5_candles=m5_candles,
        m15_candles=None,
        h1_candles=None,
        h4_candles=h4_candles,
    )

    assert res.confluence_passed is False
    assert res.h4_barrier_clear is False
    assert any("H4 Resistance" in v and "terlalu dekat" in v for v in res.veto_reasons)


def test_h4_macro_trend_misalignment_veto():
    """Bullish breakout against strong H4 downtrend must be vetoed."""
    mtf = XAUUSDMultiTFConfluenceEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)
    curr_price = 2950.0

    # Downtrend H4: lower highs, lower lows
    h4_candles = []
    for i in range(30):
        t = now - timedelta(hours=(30 - i) * 4)
        base = 3100.0 - (i * 5.0)
        h4_candles.append(_c(t, base, base + 2.0, base - 6.0, base - 5.0))

    m5_candles = [_c(now, 2945.0, 2952.0, 2944.0, 2950.0)]

    res = mtf.evaluate(
        current_price=curr_price,
        breakout_direction="BULLISH",
        m1_candles=None,
        m5_candles=m5_candles,
        m15_candles=None,
        h1_candles=None,
        h4_candles=h4_candles,
    )

    assert res.confluence_passed is False
    assert res.h4.trend == TrendBias.BEARISH
    assert any("melawan Macro Trend H4 (Bearish)" in v for v in res.veto_reasons)


def test_m15_structure_misalignment_veto():
    """Bullish breakout while M15 is forming Lower Lows must be vetoed."""
    mtf = XAUUSDMultiTFConfluenceEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)
    curr_price = 3000.0

    # M15 in Lower Lows
    m15_candles = []
    for i in range(20):
        t = now - timedelta(minutes=(20 - i) * 15)
        p = 3050.0 - (i * 3.0)
        m15_candles.append(_c(t, p, p + 1.0, p - 3.0, p - 2.5))

    m5_candles = [_c(now, 2995.0, 3002.0, 2994.0, 3000.0)]

    res = mtf.evaluate(
        current_price=curr_price,
        breakout_direction="BULLISH",
        m1_candles=None,
        m5_candles=m5_candles,
        m15_candles=m15_candles,
        h1_candles=None,
        h4_candles=None,
    )

    assert res.confluence_passed is False
    assert res.m15_structure_confirmed is False
    assert any("Struktur M15 masih membentuk Lower Lows" in v for v in res.veto_reasons)


def test_m1_micro_rejection_veto():
    """Bullish breakout where M1 shows strong bearish collapse must wait for retest."""
    mtf = XAUUSDMultiTFConfluenceEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)
    curr_price = 3000.0

    # M1 candles showing bearish collapse instead of rejection
    m1_candles = [
        _c(now - timedelta(minutes=2), 3004.0, 3004.0, 3001.0, 3001.5),
        _c(now - timedelta(minutes=1), 3001.5, 3001.5, 2998.0, 2998.5),  # Bearish drop
    ]
    m5_candles = [_c(now, 2995.0, 3002.0, 2994.0, 3000.0)]

    res = mtf.evaluate(
        current_price=curr_price,
        breakout_direction="BULLISH",
        m1_candles=m1_candles,
        m5_candles=m5_candles,
        m15_candles=None,
        h1_candles=None,
        h4_candles=None,
    )

    assert res.confluence_passed is False
    assert res.m1_retest_confirmed is False
    assert any("Micro M1 belum memberikan konfirmasi" in v for v in res.veto_reasons)


def test_full_5tf_confluence_pass():
    """All 5 timeframes (H4, H1, M15, M5, M1) align and pass all barriers."""
    engine = XAUUSDBreakoutEngine()
    now = datetime(2026, 9, 7, 14, 30, tzinfo=timezone.utc)

    # 1. H4 candles (Uptrend, clear resistance far above at 3050)
    h4_candles = []
    for i in range(25):
        t = now - timedelta(hours=(25 - i) * 4)
        base = 2920.0 + (i * 3.0)
        h4_candles.append(_c(t, base, base + 4.0, base - 1.0, base + 3.0))

    # 2. H1 candles (Uptrend)
    h1_candles = []
    for i in range(25):
        t = now - timedelta(hours=(25 - i))
        base = 2950.0 + (i * 2.0)
        h1_candles.append(_c(t, base, base + 3.0, base - 0.5, base + 2.0))

    # 3. M15 candles (Uptrend / Expansion)
    m15_candles = []
    for i in range(20):
        t = now - timedelta(minutes=(20 - i) * 15)
        base = 2975.0 + (i * 1.2)
        m15_candles.append(_c(t, base, base + 2.0, base - 0.5, base + 1.2))

    # 4. M5 candles (Range + Institutional Breakout)
    m5_candles = []
    for i in range(25):
        t = now - timedelta(minutes=(25 - i) * 5)
        m5_candles.append(_agg(t, 2990.0, 2995.0, 2988.0, 2993.0))
    breakout_c = _agg(now, 2994.0, 3008.0, 2994.0, 3007.0, ticks=600)
    m5_candles.append(breakout_c)

    # 5. M1 candles (Clean bullish rejection bounce)
    m1_candles = [
        _c(now - timedelta(minutes=2), 3002.0, 3003.0, 3001.5, 3002.5),
        _c(now - timedelta(minutes=1), 3002.5, 3007.5, 3002.0, 3007.0),
    ]

    res = engine.evaluate(
        m5_candles,
        current_spread=0.18,
        is_market_open=True,
        m1_candles=m1_candles,
        m15_candles=m15_candles,
        h1_candles=h1_candles,
        h4_candles=h4_candles,
    )

    assert res.breakout_valid is True
    assert res.breakout_type == "BULLISH_BREAKOUT"
    assert res.multitf_passed is True
    assert res.multitf_confluence is not None
    assert res.multitf_confluence["h4_barrier_clear"] is True
    assert res.signal == "BUY"
    assert res.total_score >= 85
