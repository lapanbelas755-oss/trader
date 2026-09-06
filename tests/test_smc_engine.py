"""
Unit tests for Smart Money Concepts (SMC) Engine.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from core.structure.smc import SMCEngine


class DummyCandle:
    def __init__(self, dt, o, h, l, c):
        self.timestamp = dt
        self.open = Decimal(str(o))
        self.high = Decimal(str(h))
        self.low = Decimal(str(l))
        self.close = Decimal(str(c))


class DummySwing:
    def __init__(self, dt, price, stype, classif=None):
        self.timestamp = dt
        self.price = Decimal(str(price))
        self.swing_type = stype
        self.classification = classif


class DummyEvent:
    def __init__(self, dt, price, stype, direction):
        self.timestamp = dt
        self.price = Decimal(str(price))
        self.structure_type = stype
        self.direction = direction


def test_extract_zigzag():
    engine = SMCEngine()
    base_t = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    swings = [
        DummySwing(base_t, 210.50, "SWING_LOW", "HL"),
        DummySwing(base_t + timedelta(minutes=15), 211.80, "SWING_HIGH", "HH"),
    ]
    zigzag = engine.extract_zigzag(swings)
    assert len(zigzag) == 2
    assert zigzag[0]["value"] == 210.50
    assert zigzag[1]["value"] == 211.80
    assert zigzag[0]["is_high"] is False
    assert zigzag[1]["is_high"] is True


def test_extract_msb_lines():
    engine = SMCEngine()
    base_t = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    candles = [
        DummyCandle(base_t, 210.0, 210.5, 209.8, 210.2),
        DummyCandle(base_t + timedelta(minutes=15), 210.2, 211.5, 210.1, 211.2),
    ]
    events = [
        DummyEvent(base_t + timedelta(minutes=10), 210.80, "BOS_UP", "BULLISH"),
        DummyEvent(base_t + timedelta(minutes=12), 209.50, "CHOCH_DOWN", "BEARISH"),
    ]
    msb_lines = engine.extract_msb_lines(events, candles)
    assert len(msb_lines) == 2
    assert msb_lines[0]["type"] == "MSB_BULLISH"
    assert msb_lines[0]["color"] == "#00e676"
    assert msb_lines[1]["type"] == "MSB_BEARISH"
    assert msb_lines[1]["color"] == "#ff4d6d"


def test_detect_order_blocks():
    engine = SMCEngine()
    base_t = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    atr = 0.50

    # Bu-OB setup: candle 1 is bearish, followed by impulsive candle 2 breaking higher by > atr
    candles = [
        DummyCandle(base_t, 210.0, 210.1, 209.9, 210.0),
        DummyCandle(base_t + timedelta(minutes=5), 210.2, 210.3, 209.5, 209.6),  # Bearish (OB)
        DummyCandle(base_t + timedelta(minutes=10), 209.7, 211.5, 209.6, 211.4), # Impulsive up (> 1.0 * ATR)
        DummyCandle(base_t + timedelta(minutes=15), 211.4, 211.8, 211.3, 211.7),
    ]

    obs = engine.detect_order_blocks(candles, atr=atr)
    bu_obs = [ob for ob in obs if ob["type"] == "Bu-OB"]
    assert len(bu_obs) >= 1
    assert bu_obs[0]["top"] == 210.3
    assert bu_obs[0]["bottom"] == 209.5
    assert not bu_obs[0]["mitigated"]


def test_detect_breaker_blocks():
    engine = SMCEngine()
    base_t = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    candles = [
        DummyCandle(base_t, 210.0, 210.5, 209.5, 210.2),
        DummyCandle(base_t + timedelta(minutes=5), 210.2, 211.5, 210.0, 211.3),
    ]
    obs = [
        {
            "id": "OB-BE-1",
            "type": "Be-OB",
            "top": 210.8,
            "bottom": 210.1,
            "start_time": 1000,
            "end_time": 1500,
            "mitigated": True,
        }
    ]
    breakers = engine.detect_breaker_blocks(candles, obs)
    assert len(breakers) == 1
    assert breakers[0]["type"] == "Bu-BB"
    assert breakers[0]["label"] == "Bu-BB"


def test_momentum_validation():
    engine = SMCEngine()
    base_t = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    atr = 0.50

    # Strong bullish displacement candle
    strong_bull = [
        DummyCandle(base_t, 210.0, 210.2, 209.8, 210.1),
        DummyCandle(base_t + timedelta(minutes=5), 210.1, 210.9, 210.0, 210.85),
    ]
    res_bull = engine.check_momentum(strong_bull, atr=atr, direction="BUY")
    assert res_bull["has_momentum"] is True
    assert res_bull["score"] >= 0.9

    # Weak doji candle (should fail momentum)
    weak_candles = [
        DummyCandle(base_t, 210.0, 210.2, 209.8, 210.1),
        DummyCandle(base_t + timedelta(minutes=5), 210.1, 210.2, 210.0, 210.12),
    ]
    res_weak = engine.check_momentum(weak_candles, atr=atr, direction="BUY")
    assert res_weak["has_momentum"] is False
