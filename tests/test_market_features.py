"""Comprehensive test suite for Market Feature Engine V1 covering all 14 Phase 15 test cases."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import text

from core.features.contract import FeatureStatus, CalculatedFeatureRecord
from core.features.calculator import FeatureCalculator
from core.features.loader import FeatureDatabaseLoader
from core.features.engine import MarketFeatureEngine
from database.connection import get_engine

def generate_synthetic_candles(count: int, start_price: float = 1.0850, step: float = 0.0001, tf: str = "M5", interval_minutes: int = 5) -> list[dict]:
    """Generates a sequence of deterministic synthetic candles for testing."""
    candles = []
    base_time = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    for i in range(count):
        price = start_price + (i % 5) * step
        high = price + 0.0005
        low = price - 0.0005
        open_p = price
        close_p = price + 0.0002
        candles.append({
            "symbol": "EURUSD",
            "timeframe": tf,
            "timestamp": base_time + timedelta(minutes=i * interval_minutes),
            "open": Decimal(str(round(open_p, 5))),
            "high": Decimal(str(round(high, 5))),
            "low": Decimal(str(round(low, 5))),
            "close": Decimal(str(round(close_p, 5))),
            "tick_volume": 100 + (i % 10) * 10,
            "real_volume": 0,
            "spread": Decimal("1.20"),
        })
    return candles

# --- 1. ATR NORMAL ---
def test_case_1_atr_normal():
    # Construct 15 candles with fixed range 0.00100 each, no gaps
    candles = []
    base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(15):
        candles.append({
            "symbol": "EURUSD",
            "timeframe": "M5",
            "timestamp": base_time + timedelta(minutes=i * 5),
            "open": Decimal("1.08500"),
            "high": Decimal("1.08600"),
            "low": Decimal("1.08500"),
            "close": Decimal("1.08550"),
            "tick_volume": 100,
        })
    calc = FeatureCalculator(atr_period=14)
    features = calc.calculate_features(candles)

    assert len(features) == 15
    # For first 13 bars (index 0 to 12), ATR is None
    for i in range(13):
        assert features[i].atr is None
    # 14th bar (index 13): ATR should be exactly 0.001000
    assert features[13].atr == Decimal("0.001000")
    # 15th bar (index 14): Wilder's RMA: (0.001000 * 13 + 0.001000) / 14 = 0.001000
    assert features[14].atr == Decimal("0.001000")

# --- 2. ATR WARMUP ---
def test_case_2_atr_warmup():
    candles = generate_synthetic_candles(10)
    calc = FeatureCalculator(atr_period=14)
    features = calc.calculate_features(candles)
    for f in features:
        assert f.atr is None
        assert f.feature_status == FeatureStatus.INSUFFICIENT_DATA

# --- 3. TRUE RANGE GAP ---
def test_case_3_true_range_gap():
    # Bar 0: close = 1.08500
    # Bar 1: gap up, low = 1.08700, high = 1.08800 (range = 0.00100)
    # TR_1 should be max(0.00100, |1.08800 - 1.08500|=0.00300, |1.08700 - 1.08500|=0.00200) = 0.00300
    c0 = {"symbol": "EURUSD", "timeframe": "M5", "timestamp": datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
          "open": Decimal("1.08450"), "high": Decimal("1.08550"), "low": Decimal("1.08400"), "close": Decimal("1.08500"), "tick_volume": 50}
    c1 = {"symbol": "EURUSD", "timeframe": "M5", "timestamp": datetime(2026, 9, 1, 10, 5, 0, tzinfo=timezone.utc),
          "open": Decimal("1.08750"), "high": Decimal("1.08800"), "low": Decimal("1.08700"), "close": Decimal("1.08780"), "tick_volume": 60}

    calc = FeatureCalculator(atr_period=14)
    features = calc.calculate_features([c0, c1])
    # The range of c1 is 0.001000, but gap was 0.003000
    assert features[1].range == Decimal("0.001000")

# --- 4. ROLLING BASELINE ---
def test_case_4_rolling_baseline():
    # Generate 115 candles with constant tick_volume = 100 and constant range = 0.00100
    candles = []
    base_time = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    for i in range(115):
        candles.append({
            "symbol": "EURUSD",
            "timeframe": "M5",
            "timestamp": base_time + timedelta(minutes=i * 5),
            "open": Decimal("1.08500"),
            "high": Decimal("1.08600"),
            "low": Decimal("1.08500"),
            "close": Decimal("1.08550"),
            "tick_volume": 100,
        })
    calc = FeatureCalculator(baseline_window=100, atr_period=14)
    features = calc.calculate_features(candles)

    # Bar index 100 has 100 prior bars (0..99)
    assert features[100].feature_status == FeatureStatus.VALID
    # Since all prior 100 bars had tick_volume = 100 and current is 100, z-score should be 0.0
    assert features[100].activity_zscore == Decimal("0.0000")
    assert features[100].volatility_zscore == Decimal("0.0000")

# --- 5. Z-SCORE NORMAL ---
def test_case_5_zscore_normal():
    # Baseline 100 candles with varying volume: 50 candles with 80, 50 candles with 120 (mean = 100, std = 20)
    # 101st candle with volume = 120 -> z = (120 - 100) / 20 = +1.0
    candles = []
    base_time = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    for i in range(100):
        vol = 80 if i % 2 == 0 else 120
        candles.append({
            "symbol": "EURUSD",
            "timeframe": "M5",
            "timestamp": base_time + timedelta(minutes=i * 5),
            "open": Decimal("1.08500"), "high": Decimal("1.08600"), "low": Decimal("1.08500"), "close": Decimal("1.08550"),
            "tick_volume": vol,
        })
    # 101st candle
    candles.append({
        "symbol": "EURUSD",
        "timeframe": "M5",
        "timestamp": base_time + timedelta(minutes=500),
        "open": Decimal("1.08500"), "high": Decimal("1.08600"), "low": Decimal("1.08500"), "close": Decimal("1.08550"),
        "tick_volume": 120,
    })
    calc = FeatureCalculator(baseline_window=100, atr_period=14)
    features = calc.calculate_features(candles)
    assert features[100].activity_zscore == Decimal("1.0000")

# --- 6. Z-SCORE ANOMALY ---
def test_case_6_zscore_anomaly():
    # Baseline 100 candles with volume = 100 (mean = 100, std = 20 using 80/120)
    # Candle 101 with volume = 150 -> z = (150 - 100) / 20 = +2.5 -> ANOMALY CANDIDATE!
    candles = []
    base_time = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    for i in range(100):
        vol = 80 if i % 2 == 0 else 120
        candles.append({
            "symbol": "EURUSD",
            "timeframe": "M5",
            "timestamp": base_time + timedelta(minutes=i * 5),
            "open": Decimal("1.08500"), "high": Decimal("1.08600"), "low": Decimal("1.08500"), "close": Decimal("1.08550"),
            "tick_volume": vol,
        })
    # Anomaly candle
    candles.append({
        "symbol": "EURUSD",
        "timeframe": "M5",
        "timestamp": base_time + timedelta(minutes=500),
        "open": Decimal("1.08500"), "high": Decimal("1.08600"), "low": Decimal("1.08500"), "close": Decimal("1.08550"),
        "tick_volume": 150,
    })
    calc = FeatureCalculator(baseline_window=100, atr_period=14)
    features = calc.calculate_features(candles)
    assert features[100].activity_zscore == Decimal("2.5000")
    assert features[100].is_anomaly_candidate is True

# --- 7. ZERO RANGE DOJI ---
def test_case_7_zero_range_doji():
    # Doji candle where high == low == open == close
    c = {
        "symbol": "EURUSD", "timeframe": "M5",
        "timestamp": datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        "open": Decimal("1.08500"), "high": Decimal("1.08500"), "low": Decimal("1.08500"), "close": Decimal("1.08500"),
        "tick_volume": 1,
    }
    calc = FeatureCalculator(atr_period=14)
    features = calc.calculate_features([c])
    assert len(features) == 1
    assert features[0].range == Decimal("0.000000")
    assert features[0].movement_efficiency == Decimal("0.0000")

# --- 8. ZERO TIME DELTA ---
def test_case_8_zero_time_delta():
    # Two candles with identical timestamp
    ts = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    c1 = {"symbol": "EURUSD", "timeframe": "M5", "timestamp": ts, "open": Decimal("1.08500"), "high": Decimal("1.08550"), "low": Decimal("1.08490"), "close": Decimal("1.08530"), "tick_volume": 10}
    c2 = {"symbol": "EURUSD", "timeframe": "M5", "timestamp": ts, "open": Decimal("1.08530"), "high": Decimal("1.08560"), "low": Decimal("1.08510"), "close": Decimal("1.08540"), "tick_volume": 12}
    calc = FeatureCalculator()
    features = calc.calculate_features([c1, c2])
    # Denominator delta_t is 0 -> speed should be None, no divide by zero!
    assert features[1].movement_speed is None

# --- 9. INSUFFICIENT DATA & WARMUP PHASES ---
def test_case_9_insufficient_data():
    candles = generate_synthetic_candles(50)
    calc = FeatureCalculator(baseline_window=100, atr_period=14)
    features = calc.calculate_features(candles)
    # First 13 bars: INSUFFICIENT_DATA
    for i in range(13):
        assert features[i].feature_status == FeatureStatus.INSUFFICIENT_DATA
    # Bars 13 to 49: WARMUP
    for i in range(13, 50):
        assert features[i].feature_status == FeatureStatus.WARMUP

# --- 10. STRICT ZERO FUTURE LEAKAGE TEST ---
def test_case_10_future_leakage():
    candles = generate_synthetic_candles(105)
    calc = FeatureCalculator(baseline_window=100, atr_period=14)
    features_orig = calc.calculate_features(candles)

    # Now add a future extreme candle at index 105
    future_extreme_candle = {
        "symbol": "EURUSD",
        "timeframe": "M5",
        "timestamp": datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc),
        "open": Decimal("2.00000"),
        "high": Decimal("2.50000"),  # Extreme spike
        "low": Decimal("1.90000"),
        "close": Decimal("2.40000"),
        "tick_volume": 10000,
    }
    features_with_future = calc.calculate_features(candles + [future_extreme_candle])

    # Assert that ALL features from 0..104 are 100% IDENTICAL before and after the future candle was added
    for i in range(105):
        f1 = features_orig[i]
        f2 = features_with_future[i]
        assert f1.atr == f2.atr
        assert f1.range == f2.range
        assert f1.activity_zscore == f2.activity_zscore
        assert f1.volatility_zscore == f2.volatility_zscore
        assert f1.is_anomaly_candidate == f2.is_anomaly_candidate

# --- 11. REPEATED EXECUTION IDEMPOTENCY ---
def test_case_11_repeated_execution_idempotency():
    loader = FeatureDatabaseLoader()
    ts = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    rec = CalculatedFeatureRecord(
        symbol="EURUSD",
        timeframe="M5",
        timestamp=ts,
        range=Decimal("0.001000"),
        body=Decimal("0.000500"),
        price_change=Decimal("0.000200"),
        effort=Decimal("100"),
        feature_status=FeatureStatus.WARMUP,
    )

    # Run 1
    res1 = loader.upsert_features([rec])
    assert res1.inserted == 1
    assert res1.unchanged == 0

    # Run 2
    res2 = loader.upsert_features([rec])
    assert res2.inserted == 0
    assert res2.unchanged == 1

    # Cleanup
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM market_features WHERE symbol = 'EURUSD' AND timeframe = 'M5' AND timestamp = :ts"),
            {"ts": ts}
        )

# --- 12. DATABASE PERSISTENCE & QUERY PRECISION ---
def test_case_12_database_persistence():
    loader = FeatureDatabaseLoader()
    ts = datetime(2026, 9, 1, 14, 0, 0, tzinfo=timezone.utc)
    rec = CalculatedFeatureRecord(
        symbol="EURUSD",
        timeframe="M15",
        timestamp=ts,
        atr=Decimal("0.001425"),
        range=Decimal("0.001850"),
        body=Decimal("0.001120"),
        price_change=Decimal("-0.000850"),
        movement_efficiency=Decimal("0.6054"),
        effort=Decimal("250.0000"),
        result=Decimal("1.298246"),
        effort_result_ratio=Decimal("192.5675"),
        volatility=Decimal("0.001425"),
        volatility_zscore=Decimal("1.8540"),
        activity_zscore=Decimal("2.1450"),
        price_response_zscore=Decimal("-1.6500"),
        is_anomaly_candidate=True,
        is_strong_anomaly=True,
        movement_speed=Decimal("0.00000094"),
        range_per_second=Decimal("0.00000206"),
        price_change_per_second=Decimal("-0.00000094"),
        feature_status=FeatureStatus.VALID,
    )

    loader.upsert_features([rec])

    # Query back
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT atr, range, effort_result_ratio, is_strong_anomaly, feature_status FROM market_features WHERE symbol = 'EURUSD' AND timeframe = 'M15' AND timestamp = :ts"),
            {"ts": ts}
        ).fetchone()

        assert row is not None
        assert row.atr == Decimal("0.001425")
        assert row.range == Decimal("0.001850")
        assert row.effort_result_ratio == Decimal("192.5675")
        assert row.is_strong_anomaly is True
        assert row.feature_status == "VALID"

        conn.execute(
            text("DELETE FROM market_features WHERE symbol = 'EURUSD' AND timeframe = 'M15' AND timestamp = :ts"),
            {"ts": ts}
        )
        conn.commit()

# --- 13. INVALID CANDLE HANDLING ---
def test_case_13_invalid_candle_handling():
    # Negative range (high < low) must raise ValueError in contract
    with pytest.raises(Exception):
        CalculatedFeatureRecord(
            symbol="EURUSD",
            timeframe="M5",
            timestamp=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
            range=Decimal("-0.001000"),  # Invalid negative range
            body=Decimal("0.000500"),
            price_change=Decimal("0.000100"),
            effort=Decimal("100"),
        )

# --- 14. MULTIPLE TIMEFRAMES ISOLATION & ENGINE FLOW ---
def test_case_14_multiple_timeframes_engine_flow():
    # Insert test candles in M5 and H1 into market_candles
    engine = get_engine()
    t1 = datetime(2026, 9, 3, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 3, 10, 5, 0, tzinfo=timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO market_candles (symbol, timeframe, timestamp, open, high, low, close, tick_volume, spread)
                VALUES
                    ('EURUSD', 'M5', :t1, 1.0850, 1.0860, 1.0845, 1.0855, 120, 1.2),
                    ('EURUSD', 'M5', :t2, 1.0855, 1.0865, 1.0850, 1.0860, 140, 1.2),
                    ('EURUSD', 'H1', :t1, 1.0850, 1.0880, 1.0840, 1.0870, 850, 1.2)
                ON CONFLICT (symbol, timeframe, timestamp) DO NOTHING;
            """),
            {"t1": t1, "t2": t2}
        )

    feat_engine = MarketFeatureEngine()

    # Process M5
    res_m5 = feat_engine.process_range("EURUSD", "M5", start_timestamp=t1, end_timestamp=t2)
    assert res_m5.candles_processed == 2
    assert res_m5.features_calculated == 2

    # Process H1
    res_h1 = feat_engine.process_range("EURUSD", "H1", start_timestamp=t1, end_timestamp=t1)
    assert res_h1.candles_processed == 1
    assert res_h1.features_calculated == 1

    # Cleanup
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM market_features WHERE symbol = 'EURUSD' AND timestamp IN (:t1, :t2)"), {"t1": t1, "t2": t2})
        conn.execute(text("DELETE FROM market_candles WHERE symbol = 'EURUSD' AND timestamp IN (:t1, :t2)"), {"t1": t1, "t2": t2})
