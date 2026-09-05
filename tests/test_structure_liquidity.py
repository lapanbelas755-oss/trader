"""
Deterministic Test Suite for Market Structure & Liquidity Detector Engine V1.
Covers all 40 required test groups plus mandatory causality test test_structure_has_no_future_leakage().
"""

from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import text

from core.structure.contract import (
    SwingType,
    StructureClassification,
    BreakType,
    StructureDirection,
    MTFAlignment,
    ConfirmedSwing,
    StructureEvent,
)
from core.structure.swings import SwingDetector
from core.structure.classifier import SwingClassifier
from core.structure.bos_choch import BreakDetector
from core.structure.strength import StructureStrengthCalculator
from core.structure.engine import MarketStructureEngine

from core.liquidity.contract import (
    LiquidityLevelType,
    LiquidityStatus,
    TradingSession,
    LiquidityLevelRecord,
    SweepEvent,
)
from core.liquidity.sessions import SessionDetector, DEFAULT_SESSIONS
from core.liquidity.levels import LiquidityLevelDetector
from core.liquidity.sweep import SweepDetector
from core.liquidity.acceptance import AcceptanceRejectionDetector
from core.liquidity.engine import LiquidityEngine

from database.connection import get_engine, get_session_factory
from database.models import MarketStructure, LiquidityLevel


def make_candle(ts: datetime, o: float, h: float, l: float, c: float, tf: str = "M5", sym: str = "EURUSD"):
    """Helper to create synthetic candle dictionary."""
    return {
        "symbol": sym,
        "timeframe": tf,
        "timestamp": ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
        "open": Decimal(str(round(o, 5))),
        "high": Decimal(str(round(h, 5))),
        "low": Decimal(str(round(l, 5))),
        "close": Decimal(str(round(c, 5))),
        "tick_volume": 100,
        "real_volume": 0,
        "spread": Decimal("1.0"),
    }


# ==============================================================================
# 1. SWING HIGH DETECTION
# ==============================================================================
def test_group_01_swing_high_detection():
    detector = SwingDetector(left_bars=2, right_bars=2)
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    # 5 candles: Highs: 1.1000, 1.1020, 1.1050, 1.1010, 1.0990 -> Swing High at idx 2
    candles = [
        make_candle(base + timedelta(minutes=5 * i), 1.1000, h, 1.0980, 1.1000)
        for i, h in enumerate([1.1000, 1.1020, 1.1050, 1.1010, 1.0990])
    ]
    swings = detector.detect_swings(candles)
    highs = [s for s in swings if s.swing_type == SwingType.SWING_HIGH]
    assert len(highs) == 1
    assert highs[0].price == Decimal("1.1050")
    assert highs[0].swing_timestamp == base + timedelta(minutes=10)


# ==============================================================================
# 2. SWING LOW DETECTION
# ==============================================================================
def test_group_02_swing_low_detection():
    detector = SwingDetector(left_bars=2, right_bars=2)
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    # Lows: 1.1000, 1.0980, 1.0950, 1.0970, 1.0990 -> Swing Low at idx 2
    candles = [
        make_candle(base + timedelta(minutes=5 * i), 1.1000, 1.1020, l, 1.1000)
        for i, l in enumerate([1.1000, 1.0980, 1.0950, 1.0970, 1.0990])
    ]
    swings = detector.detect_swings(candles)
    lows = [s for s in swings if s.swing_type == SwingType.SWING_LOW]
    assert len(lows) == 1
    assert lows[0].price == Decimal("1.0950")
    assert lows[0].swing_timestamp == base + timedelta(minutes=10)


# ==============================================================================
# 3. SWING CONFIRMATION DELAY
# ==============================================================================
def test_group_03_swing_confirmation_delay():
    detector = SwingDetector(left_bars=2, right_bars=2)
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    candles = [
        make_candle(base + timedelta(minutes=5 * i), 1.1000, h, 1.0980, 1.1000)
        for i, h in enumerate([1.1000, 1.1020, 1.1050, 1.1010, 1.0990])
    ]
    swings = detector.detect_swings(candles)
    assert len(swings) == 1
    # Swing occurs at t=2 (10:10), right_bars=2, so confirmed at t=4 (10:20)
    assert swings[0].swing_timestamp == base + timedelta(minutes=10)
    assert swings[0].confirmed_at == base + timedelta(minutes=20)
    assert swings[0].confirmed_at > swings[0].swing_timestamp


# ==============================================================================
# 4. NO LOOK-AHEAD
# ==============================================================================
def test_group_04_no_lookahead():
    detector = SwingDetector(left_bars=2, right_bars=2)
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    candles = [
        make_candle(base + timedelta(minutes=5 * i), 1.1000, h, 1.0980, 1.1000)
        for i, h in enumerate([1.1000, 1.1020, 1.1050, 1.1010])  # Only 4 candles, right_bars=2 incomplete for idx 2!
    ]
    swings = detector.detect_swings(candles)
    # At t=3, candle at t=2 only has 1 right bar, so CANNOT be confirmed yet
    assert len(swings) == 0


# ==============================================================================
# 5. HIGHER HIGH (HH)
# ==============================================================================
def test_group_05_higher_high():
    classifier = SwingClassifier()
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s1 = ConfirmedSwing(
        swing_id="S1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1050"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10)
    )
    s2 = ConfirmedSwing(
        swing_id="S2", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1080"),
        swing_timestamp=base + timedelta(minutes=20), confirmed_at=base + timedelta(minutes=30)
    )
    classified = classifier.classify_swings([s1, s2])
    assert classified[0].classification is None
    assert classified[1].classification == StructureClassification.HH


# ==============================================================================
# 6. HIGHER LOW (HL)
# ==============================================================================
def test_group_06_higher_low():
    classifier = SwingClassifier()
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s1 = ConfirmedSwing(
        swing_id="S1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_LOW, price=Decimal("1.0950"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10)
    )
    s2 = ConfirmedSwing(
        swing_id="S2", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_LOW, price=Decimal("1.0980"),
        swing_timestamp=base + timedelta(minutes=20), confirmed_at=base + timedelta(minutes=30)
    )
    classified = classifier.classify_swings([s1, s2])
    assert classified[1].classification == StructureClassification.HL


# ==============================================================================
# 7. LOWER HIGH (LH)
# ==============================================================================
def test_group_07_lower_high():
    classifier = SwingClassifier()
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s1 = ConfirmedSwing(
        swing_id="S1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1100"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10)
    )
    s2 = ConfirmedSwing(
        swing_id="S2", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1070"),
        swing_timestamp=base + timedelta(minutes=20), confirmed_at=base + timedelta(minutes=30)
    )
    classified = classifier.classify_swings([s1, s2])
    assert classified[1].classification == StructureClassification.LH


# ==============================================================================
# 8. LOWER LOW (LL)
# ==============================================================================
def test_group_08_lower_low():
    classifier = SwingClassifier()
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s1 = ConfirmedSwing(
        swing_id="S1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_LOW, price=Decimal("1.0950"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10)
    )
    s2 = ConfirmedSwing(
        swing_id="S2", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_LOW, price=Decimal("1.0920"),
        swing_timestamp=base + timedelta(minutes=20), confirmed_at=base + timedelta(minutes=30)
    )
    classified = classifier.classify_swings([s1, s2])
    assert classified[1].classification == StructureClassification.LL


# ==============================================================================
# 9. BULLISH STRUCTURE
# ==============================================================================
def test_group_09_bullish_structure():
    classifier = SwingClassifier()
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    swings = [
        ConfirmedSwing(swing_id="S1", symbol="EURUSD", timeframe="M5", swing_type=SwingType.SWING_LOW, price=Decimal("1.0900"), swing_timestamp=base, confirmed_at=base + timedelta(minutes=5), classification=None),
        ConfirmedSwing(swing_id="S2", symbol="EURUSD", timeframe="M5", swing_type=SwingType.SWING_HIGH, price=Decimal("1.1000"), swing_timestamp=base + timedelta(minutes=10), confirmed_at=base + timedelta(minutes=15), classification=None),
        ConfirmedSwing(swing_id="S3", symbol="EURUSD", timeframe="M5", swing_type=SwingType.SWING_LOW, price=Decimal("1.0950"), swing_timestamp=base + timedelta(minutes=20), confirmed_at=base + timedelta(minutes=25), classification=StructureClassification.HL),
        ConfirmedSwing(swing_id="S4", symbol="EURUSD", timeframe="M5", swing_type=SwingType.SWING_HIGH, price=Decimal("1.1050"), swing_timestamp=base + timedelta(minutes=30), confirmed_at=base + timedelta(minutes=35), classification=StructureClassification.HH),
    ]
    direction = classifier.derive_direction(swings)
    assert direction == StructureDirection.BULLISH


# ==============================================================================
# 10. BEARISH STRUCTURE
# ==============================================================================
def test_group_10_bearish_structure():
    classifier = SwingClassifier()
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    swings = [
        ConfirmedSwing(swing_id="S1", symbol="EURUSD", timeframe="M5", swing_type=SwingType.SWING_HIGH, price=Decimal("1.1100"), swing_timestamp=base, confirmed_at=base + timedelta(minutes=5), classification=None),
        ConfirmedSwing(swing_id="S2", symbol="EURUSD", timeframe="M5", swing_type=SwingType.SWING_LOW, price=Decimal("1.1000"), swing_timestamp=base + timedelta(minutes=10), confirmed_at=base + timedelta(minutes=15), classification=None),
        ConfirmedSwing(swing_id="S3", symbol="EURUSD", timeframe="M5", swing_type=SwingType.SWING_HIGH, price=Decimal("1.1050"), swing_timestamp=base + timedelta(minutes=20), confirmed_at=base + timedelta(minutes=25), classification=StructureClassification.LH),
        ConfirmedSwing(swing_id="S4", symbol="EURUSD", timeframe="M5", swing_type=SwingType.SWING_LOW, price=Decimal("1.0950"), swing_timestamp=base + timedelta(minutes=30), confirmed_at=base + timedelta(minutes=35), classification=StructureClassification.LL),
    ]
    direction = classifier.derive_direction(swings)
    assert direction == StructureDirection.BEARISH


# ==============================================================================
# 11. BOS BULLISH
# ==============================================================================
def test_group_11_bos_bullish():
    detector = BreakDetector(min_displacement_atr_mult=Decimal("0.10"), fallback_displacement=Decimal("0.00010"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s_high = ConfirmedSwing(
        swing_id="SW1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1000"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10),
        classification=StructureClassification.HH
    )
    # Candle after confirmation closes above 1.1000 by 0.00030
    c1 = make_candle(base + timedelta(minutes=15), 1.0990, 1.1040, 1.0990, 1.1030)
    events = detector.detect_breaks([c1], [s_high])
    assert len(events) == 1
    assert events[0].break_type == BreakType.BOS
    assert events[0].direction == StructureDirection.BULLISH
    assert events[0].break_price == Decimal("1.1030")


# ==============================================================================
# 12. BOS BEARISH
# ==============================================================================
def test_group_12_bos_bearish():
    detector = BreakDetector(min_displacement_atr_mult=Decimal("0.10"), fallback_displacement=Decimal("0.00010"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s_low = ConfirmedSwing(
        swing_id="SW1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_LOW, price=Decimal("1.0950"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10),
        classification=StructureClassification.LL
    )
    c1 = make_candle(base + timedelta(minutes=15), 1.0960, 1.0960, 1.0910, 1.0920)
    events = detector.detect_breaks([c1], [s_low])
    assert len(events) == 1
    assert events[0].break_type == BreakType.BOS
    assert events[0].direction == StructureDirection.BEARISH
    assert events[0].break_price == Decimal("1.0920")


# ==============================================================================
# 13. WICK DOES NOT CREATE BOS
# ==============================================================================
def test_group_13_wick_does_not_create_bos():
    detector = BreakDetector(min_displacement_atr_mult=Decimal("0.10"), fallback_displacement=Decimal("0.00010"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s_high = ConfirmedSwing(
        swing_id="SW1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1000"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10)
    )
    # Candle wicks to 1.1050 but closes at 1.0995 (below 1.1000)
    c1 = make_candle(base + timedelta(minutes=15), 1.0980, 1.1050, 1.0980, 1.0995)
    events = detector.detect_breaks([c1], [s_high])
    assert len(events) == 0


# ==============================================================================
# 14. CHOCH BULLISH
# ==============================================================================
def test_group_14_choch_bullish():
    detector = BreakDetector(min_displacement_atr_mult=Decimal("0.10"), fallback_displacement=Decimal("0.00010"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    # In a bearish structure, breaking above LH is CHoCH
    s_lh = ConfirmedSwing(
        swing_id="SW1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1050"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10),
        classification=StructureClassification.LH
    )
    c1 = make_candle(base + timedelta(minutes=15), 1.1030, 1.1090, 1.1030, 1.1080)
    events = detector.detect_breaks([c1], [s_lh])
    assert len(events) == 1
    assert events[0].break_type == BreakType.CHOCH
    assert events[0].direction == StructureDirection.BULLISH


# ==============================================================================
# 15. CHOCH BEARISH
# ==============================================================================
def test_group_15_choch_bearish():
    detector = BreakDetector(min_displacement_atr_mult=Decimal("0.10"), fallback_displacement=Decimal("0.00010"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    # In a bullish structure, breaking below HL is CHoCH
    s_hl = ConfirmedSwing(
        swing_id="SW1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_LOW, price=Decimal("1.0950"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10),
        classification=StructureClassification.HL
    )
    c1 = make_candle(base + timedelta(minutes=15), 1.0960, 1.0960, 1.0900, 1.0910)
    events = detector.detect_breaks([c1], [s_hl])
    assert len(events) == 1
    assert events[0].break_type == BreakType.CHOCH
    assert events[0].direction == StructureDirection.BEARISH


# ==============================================================================
# 16. BOS VS CHOCH DISTINCTION
# ==============================================================================
def test_group_16_bos_choch_distinction():
    detector = BreakDetector(min_displacement_atr_mult=Decimal("0.10"), fallback_displacement=Decimal("0.00010"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s_hh = ConfirmedSwing(
        swing_id="SW_HH", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1000"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10),
        classification=StructureClassification.HH
    )
    s_lh = ConfirmedSwing(
        swing_id="SW_LH", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1000"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10),
        classification=StructureClassification.LH
    )
    c_break = make_candle(base + timedelta(minutes=15), 1.0990, 1.1040, 1.0990, 1.1030)

    # HH break -> BOS
    ev_bos = detector.detect_breaks([c_break], [s_hh])
    assert ev_bos[0].break_type == BreakType.BOS

    # LH break -> CHoCH
    ev_choch = detector.detect_breaks([c_break], [s_lh])
    assert ev_choch[0].break_type == BreakType.CHOCH


# ==============================================================================
# 17. EQUAL HIGH (EQH)
# ==============================================================================
def test_group_17_equal_high():
    lvl_detector = LiquidityLevelDetector()
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s1 = ConfirmedSwing(
        swing_id="S1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.10500"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10)
    )
    s2 = ConfirmedSwing(
        swing_id="S2", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.10504"),  # Within 0.00010 tolerance
        swing_timestamp=base + timedelta(minutes=30), confirmed_at=base + timedelta(minutes=40)
    )
    eq_levels = lvl_detector.detect_equal_high_low([s1, s2])
    assert len(eq_levels) == 1
    assert eq_levels[0].level_type == LiquidityLevelType.EQUAL_HIGH
    assert eq_levels[0].price == Decimal("1.10504")


# ==============================================================================
# 18. EQUAL LOW (EQL)
# ==============================================================================
def test_group_18_equal_low():
    lvl_detector = LiquidityLevelDetector()
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s1 = ConfirmedSwing(
        swing_id="S1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_LOW, price=Decimal("1.09500"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10)
    )
    s2 = ConfirmedSwing(
        swing_id="S2", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_LOW, price=Decimal("1.09495"),  # Within 0.00010 tolerance
        swing_timestamp=base + timedelta(minutes=30), confirmed_at=base + timedelta(minutes=40)
    )
    eq_levels = lvl_detector.detect_equal_high_low([s1, s2])
    assert len(eq_levels) == 1
    assert eq_levels[0].level_type == LiquidityLevelType.EQUAL_LOW
    assert eq_levels[0].price == Decimal("1.09495")


# ==============================================================================
# 19. PREVIOUS DAY HIGH (PDH)
# ==============================================================================
def test_group_19_previous_day_high():
    lvl_detector = LiquidityLevelDetector()
    # Day 1: 2026-09-01
    d1 = [
        make_candle(datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc), 1.1000, 1.1080, 1.0980, 1.1050),
        make_candle(datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc), 1.1050, 1.1120, 1.1020, 1.1090),
    ]
    # Target day: 2026-09-02
    res = lvl_detector.extract_previous_day_levels(d1, date(2026, 9, 2))
    assert res is not None
    pdh, pdl = res
    assert pdh.level_type == LiquidityLevelType.PREVIOUS_DAY_HIGH
    assert pdh.price == Decimal("1.1120")
    assert pdh.created_at == datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)


# ==============================================================================
# 20. PREVIOUS DAY LOW (PDL)
# ==============================================================================
def test_group_20_previous_day_low():
    lvl_detector = LiquidityLevelDetector()
    d1 = [
        make_candle(datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc), 1.1000, 1.1080, 1.0920, 1.1050),
        make_candle(datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc), 1.1050, 1.1120, 1.1020, 1.1090),
    ]
    res = lvl_detector.extract_previous_day_levels(d1, date(2026, 9, 2))
    assert res is not None
    pdh, pdl = res
    assert pdl.level_type == LiquidityLevelType.PREVIOUS_DAY_LOW
    assert pdl.price == Decimal("1.0920")


# ==============================================================================
# 21. PREVIOUS WEEK HIGH (PWH)
# ==============================================================================
def test_group_21_previous_week_high():
    lvl_detector = LiquidityLevelDetector()
    # Week 36 (Monday 2026-08-31 to Friday 2026-09-04)
    w_candles = [
        make_candle(datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc), 1.1000, 1.1200, 1.0950, 1.1100),
        make_candle(datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc), 1.1100, 1.1150, 1.1020, 1.1130),
    ]
    # Target date: Week 37 (2026-09-07)
    res = lvl_detector.extract_previous_week_levels(w_candles, date(2026, 9, 7))
    assert res is not None
    pwh, pwl = res
    assert pwh.level_type == LiquidityLevelType.PREVIOUS_WEEK_HIGH
    assert pwh.price == Decimal("1.1200")


# ==============================================================================
# 22. PREVIOUS WEEK LOW (PWL)
# ==============================================================================
def test_group_22_previous_week_low():
    lvl_detector = LiquidityLevelDetector()
    w_candles = [
        make_candle(datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc), 1.1000, 1.1200, 1.0850, 1.1100),
        make_candle(datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc), 1.1100, 1.1150, 1.1020, 1.1130),
    ]
    res = lvl_detector.extract_previous_week_levels(w_candles, date(2026, 9, 7))
    assert res is not None
    pwh, pwl = res
    assert pwl.level_type == LiquidityLevelType.PREVIOUS_WEEK_LOW
    assert pwl.price == Decimal("1.0850")


# ==============================================================================
# 23. SESSION HIGH
# ==============================================================================
def test_group_23_session_high():
    s_detector = SessionDetector()
    # London: 07:00 - 15:30 UTC
    ref_d = date(2026, 9, 1)
    candles = [
        make_candle(datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc), 1.1000, 1.1080, 1.0990, 1.1050),
        make_candle(datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc), 1.1050, 1.1150, 1.1020, 1.1110),
        make_candle(datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc), 1.1110, 1.1130, 1.1060, 1.1080),
    ]
    res = s_detector.extract_session_levels(candles, TradingSession.LONDON, ref_d)
    assert res is not None
    sh, sl = res
    assert sh.level_type == LiquidityLevelType.SESSION_HIGH
    assert sh.price == Decimal("1.1150")
    assert sh.session == "LONDON"


# ==============================================================================
# 24. SESSION LOW
# ==============================================================================
def test_group_24_session_low():
    s_detector = SessionDetector()
    ref_d = date(2026, 9, 1)
    candles = [
        make_candle(datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc), 1.1000, 1.1080, 1.0960, 1.1050),
        make_candle(datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc), 1.1050, 1.1150, 1.1020, 1.1110),
    ]
    res = s_detector.extract_session_levels(candles, TradingSession.LONDON, ref_d)
    assert res is not None
    sh, sl = res
    assert sl.level_type == LiquidityLevelType.SESSION_LOW
    assert sl.price == Decimal("1.0960")


# ==============================================================================
# 25. SESSION TIMEZONE (EXPLICIT UTC)
# ==============================================================================
def test_group_25_session_timezone():
    s_detector = SessionDetector(tz=timezone.utc)
    # 07:30 UTC is inside London (07:00 - 15:30 UTC)
    t_inside = datetime(2026, 9, 1, 7, 30, tzinfo=timezone.utc)
    # 06:30 UTC is outside London
    t_outside = datetime(2026, 9, 1, 6, 30, tzinfo=timezone.utc)
    assert s_detector.is_in_session(t_inside, TradingSession.LONDON) is True
    assert s_detector.is_in_session(t_outside, TradingSession.LONDON) is False


# ==============================================================================
# 26. DST-SAFE BEHAVIOR
# ==============================================================================
def test_group_26_dst_safe_behavior():
    # Winter UTC timestamp vs Summer UTC timestamp: UTC boundaries are strictly static and unaffected
    s_detector = SessionDetector(tz=timezone.utc)
    summer_dt = datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)
    winter_dt = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    assert s_detector.is_in_session(summer_dt, TradingSession.NEW_YORK) is True
    assert s_detector.is_in_session(winter_dt, TradingSession.NEW_YORK) is True


# ==============================================================================
# 27. LIQUIDITY TOUCH
# ==============================================================================
def test_group_27_liquidity_touch():
    engine = LiquidityEngine(touch_mult=Decimal("0.05"), fallback_atr=Decimal("0.00100"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    lvl = LiquidityLevelRecord(
        symbol="EURUSD", timeframe="M5", level_type=LiquidityLevelType.PREVIOUS_DAY_HIGH,
        price=Decimal("1.1000"), created_at=base, status=LiquidityStatus.UNTOUCHED
    )
    # Candle approaches within touch threshold (1.1000 - 0.00005 = 1.09995)
    c1 = make_candle(base + timedelta(minutes=5), 1.0980, 1.09998, 1.0975, 1.0990)
    updated = engine.process_lifecycle([lvl], [c1], atr_value=Decimal("0.00100"))
    assert updated[0].status == LiquidityStatus.TOUCHED


# ==============================================================================
# 28. LIQUIDITY SWEEP
# ==============================================================================
def test_group_28_liquidity_sweep():
    detector = SweepDetector(min_sweep_atr_mult=Decimal("0.05"), max_sweep_atr_mult=Decimal("0.50"), fallback_atr=Decimal("0.00100"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    lvl = LiquidityLevelRecord(
        symbol="EURUSD", timeframe="M5", level_type=LiquidityLevelType.PREVIOUS_DAY_HIGH,
        price=Decimal("1.1000"), created_at=base
    )
    # Penetrates to 1.10020 (0.00020 depth = 0.20 ATR, within [0.05, 0.50])
    # and returns by closing at 1.0995 (< 1.1000)
    c1 = make_candle(base + timedelta(minutes=5), 1.0990, 1.10020, 1.0985, 1.0995)
    sweep_evt = detector.evaluate_sweep(lvl, [c1], 0, atr_value=Decimal("0.00100"))
    assert sweep_evt is not None
    assert sweep_evt.sweep_direction == "HIGH_SWEPT"
    assert sweep_evt.sweep_depth == Decimal("0.00020")


# ==============================================================================
# 29. SWEEP WITHOUT REJECTION
# ==============================================================================
def test_group_29_sweep_without_rejection():
    acc_detector = AcceptanceRejectionDetector(rejection_atr_mult=Decimal("0.30"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    lvl = LiquidityLevelRecord(
        symbol="EURUSD", timeframe="M5", level_type=LiquidityLevelType.PREVIOUS_DAY_HIGH,
        price=Decimal("1.1000"), created_at=base
    )
    sweep_evt = SweepEvent(
        symbol="EURUSD", level_type=lvl.level_type, level_price=lvl.price,
        sweep_direction="HIGH_SWEPT", sweep_timestamp=base + timedelta(minutes=5),
        sweep_extreme=Decimal("1.10020"), sweep_depth=Decimal("0.00020"),
        return_timestamp=base + timedelta(minutes=5)
    )
    # Subsequent candle closes at 1.0998 (displacement = 0.00020, less than 0.30 ATR = 0.00030)
    c_next = make_candle(base + timedelta(minutes=10), 1.0999, 1.0999, 1.0997, 1.0998)
    is_rej, disp, _ = acc_detector.evaluate_rejection(lvl, sweep_evt, [c_next], atr_value=Decimal("0.00100"))
    assert is_rej is False


# ==============================================================================
# 30. SWEEP WITH REJECTION
# ==============================================================================
def test_group_30_sweep_with_rejection():
    acc_detector = AcceptanceRejectionDetector(rejection_atr_mult=Decimal("0.30"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    lvl = LiquidityLevelRecord(
        symbol="EURUSD", timeframe="M5", level_type=LiquidityLevelType.PREVIOUS_DAY_HIGH,
        price=Decimal("1.1000"), created_at=base
    )
    sweep_evt = SweepEvent(
        symbol="EURUSD", level_type=lvl.level_type, level_price=lvl.price,
        sweep_direction="HIGH_SWEPT", sweep_timestamp=base + timedelta(minutes=5),
        sweep_extreme=Decimal("1.10020"), sweep_depth=Decimal("0.00020"),
        return_timestamp=base + timedelta(minutes=5)
    )
    # Subsequent candle drops to close at 1.09965 (displacement = 0.00035 >= 0.00030 threshold)
    c_next = make_candle(base + timedelta(minutes=10), 1.0999, 1.0999, 1.0996, 1.09965)
    is_rej, disp, rej_c = acc_detector.evaluate_rejection(lvl, sweep_evt, [c_next], atr_value=Decimal("0.00100"))
    assert is_rej is True
    assert disp == Decimal("0.00035")


# ==============================================================================
# 31. ACCEPTANCE
# ==============================================================================
def test_group_31_acceptance():
    acc_detector = AcceptanceRejectionDetector(acceptance_atr_mult=Decimal("0.30"), acceptance_min_candles=2)
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    lvl = LiquidityLevelRecord(
        symbol="EURUSD", timeframe="M5", level_type=LiquidityLevelType.PREVIOUS_DAY_HIGH,
        price=Decimal("1.1000"), created_at=base
    )
    # 2 consecutive candles closed above 1.1000, with max displacement >= 0.00030 (0.30 * ATR)
    c1 = make_candle(base + timedelta(minutes=5), 1.1001, 1.1003, 1.10005, 1.1002)
    c2 = make_candle(base + timedelta(minutes=10), 1.1002, 1.1004, 1.10015, 1.10035)  # disp = 0.00035
    is_acc, disp, _ = acc_detector.evaluate_acceptance(lvl, [c1, c2], atr_value=Decimal("0.00100"))
    assert is_acc is True
    assert disp == Decimal("0.00035")


# ==============================================================================
# 32. IMMEDIATE RETURN INVALIDATES ACCEPTANCE
# ==============================================================================
def test_group_32_immediate_return_invalidates_acceptance():
    acc_detector = AcceptanceRejectionDetector(acceptance_atr_mult=Decimal("0.30"), acceptance_min_candles=2)
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    lvl = LiquidityLevelRecord(
        symbol="EURUSD", timeframe="M5", level_type=LiquidityLevelType.PREVIOUS_DAY_HIGH,
        price=Decimal("1.1000"), created_at=base
    )
    c1 = make_candle(base + timedelta(minutes=5), 1.1002, 1.1025, 1.1001, 1.1020)
    # Second candle returns back below 1.1000
    c2 = make_candle(base + timedelta(minutes=10), 1.1010, 1.1015, 1.0980, 1.0985)
    is_acc, disp, _ = acc_detector.evaluate_acceptance(lvl, [c1, c2], atr_value=Decimal("0.00100"))
    assert is_acc is False


# ==============================================================================
# 33. MULTI-TIMEFRAME ALIGNMENT
# ==============================================================================
def test_group_33_multi_timeframe_alignment():
    engine = MarketStructureEngine()
    alignment_bull = engine.derive_mtf_alignment(
        StructureDirection.BULLISH, StructureDirection.BULLISH, StructureDirection.BULLISH
    )
    alignment_bear = engine.derive_mtf_alignment(
        StructureDirection.BEARISH, StructureDirection.BEARISH, StructureDirection.BEARISH
    )
    assert alignment_bull == MTFAlignment.ALIGNED_BULLISH
    assert alignment_bear == MTFAlignment.ALIGNED_BEARISH


# ==============================================================================
# 34. MIXED TIMEFRAME STATE
# ==============================================================================
def test_group_34_mixed_timeframe_state():
    engine = MarketStructureEngine()
    alignment = engine.derive_mtf_alignment(
        StructureDirection.BULLISH, StructureDirection.BULLISH, StructureDirection.BEARISH
    )
    assert alignment == MTFAlignment.MIXED


# ==============================================================================
# 35. INSUFFICIENT DATA
# ==============================================================================
def test_group_35_insufficient_data():
    engine = MarketStructureEngine()
    # Less than left_bars + right_bars + 1 candles
    res = engine.process_timeframe("EURUSD", "M5", [])
    assert res == []
    alignment = engine.derive_mtf_alignment(None, None, None)
    assert alignment == MTFAlignment.UNDEFINED


# ==============================================================================
# 36. ZERO ATR / ZERO VOLATILITY EDGE CASES
# ==============================================================================
def test_group_36_zero_atr_fallback():
    detector = BreakDetector(min_displacement_atr_mult=Decimal("0.10"), fallback_displacement=Decimal("0.00010"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s_hh = ConfirmedSwing(
        swing_id="SW1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1000"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10)
    )
    # Zero ATR passed -> Uses fallback displacement without crashing or dividing by zero
    c1 = make_candle(base + timedelta(minutes=15), 1.0990, 1.1003, 1.0990, 1.1002)
    evs = detector.detect_breaks([c1], [s_hh], displacement_map={c1["timestamp"]: Decimal("0")})
    assert len(evs) == 1
    assert evs[0].displacement == Decimal("0.00020")


# ==============================================================================
# 37. DUPLICATE PREVENTION
# ==============================================================================
def test_group_37_duplicate_prevention():
    # Database level duplicate prevention via unique constraints
    engine = get_engine()
    SessionLocal = get_session_factory()
    db_session = SessionLocal()
    try:
        base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        lvl1 = LiquidityLevelRecord(
            symbol="EURUSD", timeframe="M5", level_type=LiquidityLevelType.PREVIOUS_DAY_HIGH,
            price=Decimal("1.10500"), created_at=base, status=LiquidityStatus.UNTOUCHED
        )
        liq_engine = LiquidityEngine()
        cnt1 = liq_engine.upsert_levels(db_session, [lvl1])
        # Insert again with same natural key
        cnt2 = liq_engine.upsert_levels(db_session, [lvl1])
        assert cnt1 == 1
        assert cnt2 == 1

        # Check only 1 row exists in DB
        res = db_session.execute(
            text("SELECT COUNT(*) FROM liquidity_levels WHERE symbol='EURUSD' AND price=1.10500 AND created_at=:dt"),
            {"dt": base}
        ).scalar()
        assert res == 1
    finally:
        db_session.rollback()
        db_session.close()


# ==============================================================================
# 38. MIGRATION IDEMPOTENCY
# ==============================================================================
def test_group_38_migration_idempotency():
    engine = get_engine()
    with engine.connect() as conn:
        # Re-running migration 003 DDL should not fail
        with open("database/migrations/003_market_structure_liquidity.sql") as f:
            ddl = f.read()
        conn.execute(text(ddl))
        conn.commit()


# ==============================================================================
# 39. DATABASE UPSERT
# ==============================================================================
def test_group_39_database_upsert():
    engine = get_engine()
    SessionLocal = get_session_factory()
    db_session = SessionLocal()
    try:
        struct_engine = MarketStructureEngine()
        base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
        ev = StructureEvent(
            symbol="EURUSD", timeframe="M5", timestamp=base + timedelta(minutes=15),
            confirmed_at=base + timedelta(minutes=15), structure_type="BOS",
            price=Decimal("1.1020"), direction=StructureDirection.BULLISH,
            strength=Decimal("1.5000")
        )
        count = struct_engine.upsert_events(db_session, [ev])
        assert count == 1

        # Verify query
        saved = db_session.execute(
            text("SELECT structure_type, direction FROM market_structure WHERE symbol='EURUSD' AND timestamp=:ts"),
            {"ts": ev.timestamp}
        ).fetchone()
        assert saved is not None
        assert saved[0] == "BOS"
        assert saved[1] == "BULLISH"
    finally:
        db_session.rollback()
        db_session.close()


# ==============================================================================
# 40. HISTORICAL IMMUTABILITY
# ==============================================================================
def test_group_40_historical_immutability():
    # Historical events must not be overwritten or retroactively changed when later events occur
    detector = BreakDetector(min_displacement_atr_mult=Decimal("0.10"), fallback_displacement=Decimal("0.00010"))
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    s_hh = ConfirmedSwing(
        swing_id="SW1", symbol="EURUSD", timeframe="M5",
        swing_type=SwingType.SWING_HIGH, price=Decimal("1.1000"),
        swing_timestamp=base, confirmed_at=base + timedelta(minutes=10)
    )
    c1 = make_candle(base + timedelta(minutes=15), 1.0990, 1.1040, 1.0990, 1.1030)
    evs_1 = detector.detect_breaks([c1], [s_hh])
    assert len(evs_1) == 1

    # Later candle in future
    c2 = make_candle(base + timedelta(minutes=20), 1.1030, 1.1080, 1.1020, 1.1070)
    evs_2 = detector.detect_breaks([c1, c2], [s_hh])
    # The event generated for c1 must remain identical
    assert evs_2[0].timestamp == evs_1[0].timestamp
    assert evs_2[0].break_price == evs_1[0].break_price
    assert evs_2[0].direction == evs_1[0].direction


# ==============================================================================
# CRITICAL CAUSALITY TEST: test_structure_has_no_future_leakage()
# ==============================================================================
def test_structure_has_no_future_leakage():
    """
    MANDATORY CAUSALITY TEST:
    1. Generate historical candle dataset.
    2. Calculate structure.
    3. Append future candles containing extreme prices.
    4. Recalculate structure only for timestamps that existed previously.
    5. Assert that all previously available observations remain identical.
    For swing detection specifically:
    A swing at t cannot appear before: t + right_bars.
    """
    engine = MarketStructureEngine(left_bars=2, right_bars=2)
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)

    # 1. Generate 10 historical candles
    history_candles = [
        make_candle(base + timedelta(minutes=5 * i), 1.1000 + i * 0.0001, 1.1005 + i * 0.0001, 1.0995 + i * 0.0001, 1.1002 + i * 0.0001)
        for i in range(10)
    ]
    # Insert clear swing high at index 4 (10:20)
    history_candles[4]["high"] = Decimal("1.1050")
    # Swings can only be confirmed up to index 7 (since index 7 has right_bars=2 ending at index 9)

    # 2. Calculate structure on initial history
    swings_initial = engine.swing_detector.detect_swings(history_candles)
    events_initial = engine.process_timeframe("EURUSD", "M5", history_candles)

    # Verify swing confirmation delay: swing at t=4 must have confirmed_at == t=6 (10:30)
    s_idx4 = [s for s in swings_initial if s.swing_timestamp == base + timedelta(minutes=20)]
    assert len(s_idx4) == 1
    assert s_idx4[0].confirmed_at == base + timedelta(minutes=30)
    assert s_idx4[0].confirmed_at > s_idx4[0].swing_timestamp

    # 3. Append future candles with extreme volatility/spikes
    future_candles = [
        make_candle(base + timedelta(minutes=5 * i), 1.1200, 1.1500, 1.0500, 1.1300)
        for i in range(10, 20)
    ]
    combined_candles = history_candles + future_candles

    # 4. Recalculate structure on combined dataset
    swings_recalculated = engine.swing_detector.detect_swings(combined_candles)
    events_recalculated = engine.process_timeframe("EURUSD", "M5", combined_candles)

    # 5. Filter recalculated swings & events only for timestamps in original history
    original_cutoff = history_candles[-1]["timestamp"]
    swings_filtered = [s for s in swings_recalculated if s.confirmed_at <= original_cutoff]
    events_filtered = [e for e in events_recalculated if e.confirmed_at <= original_cutoff]

    # Assert exact identity
    assert len(swings_filtered) == len(swings_initial)
    for s_init, s_recalc in zip(swings_initial, swings_filtered):
        assert s_init.swing_id == s_recalc.swing_id
        assert s_init.price == s_recalc.price
        assert s_init.swing_timestamp == s_recalc.swing_timestamp
        assert s_init.confirmed_at == s_recalc.confirmed_at

    assert len(events_filtered) == len(events_initial)
    for e_init, e_recalc in zip(events_initial, events_filtered):
        assert e_init.structure_type == e_recalc.structure_type
        assert e_init.price == e_recalc.price
        assert e_init.timestamp == e_recalc.timestamp
        assert e_init.confirmed_at == e_recalc.confirmed_at
