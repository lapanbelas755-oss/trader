"""Comprehensive test suite for Candle Aggregation Engine V1 covering all 12 Phase 16 test cases."""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import text

from core.candles.boundary import get_candle_bucket
from core.candles.contract import AggregatedCandle, Timeframe
from core.candles.aggregator import CandleAggregator
from core.candles.loader import CandleDatabaseLoader
from core.candles.engine import CandleAggregationEngine
from database.connection import get_engine

# --- CASE 1: M1 NORMAL ---
def test_case_1_m1_normal():
    ticks = [
        {"timestamp": datetime(2026, 9, 1, 10, 0, 10, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08500"), "ask": Decimal("1.08510"), "last": None, "volume": 1},
        {"timestamp": datetime(2026, 9, 1, 10, 0, 20, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08550"), "ask": Decimal("1.08560"), "last": None, "volume": 1},
        {"timestamp": datetime(2026, 9, 1, 10, 0, 30, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08480"), "ask": Decimal("1.08490"), "last": None, "volume": 1},
        {"timestamp": datetime(2026, 9, 1, 10, 0, 50, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08530"), "ask": Decimal("1.08540"), "last": None, "volume": 1},
    ]
    # Data stream ends at 10:01:00 so 10:00:00 candle is closed
    cutoff = datetime(2026, 9, 1, 10, 1, 0, tzinfo=timezone.utc)
    aggregator = CandleAggregator(timeframe=Timeframe.M1)
    candles = aggregator.aggregate_ticks(ticks, data_end_time=cutoff)

    assert len(candles) == 1
    c = candles[0]
    assert c.timestamp == datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    assert c.open == Decimal("1.08500")
    assert c.high == Decimal("1.08550")
    assert c.low == Decimal("1.08480")
    assert c.close == Decimal("1.08530")
    assert c.tick_volume == 4
    assert c.is_closed is True

# --- CASE 2: M5 BOUNDARY ---
def test_case_2_m5_boundary():
    t1 = datetime(2026, 9, 1, 12, 4, 59, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 1, 12, 5, 0, tzinfo=timezone.utc)

    b1_start, b1_end = get_candle_bucket(t1, Timeframe.M5)
    b2_start, b2_end = get_candle_bucket(t2, Timeframe.M5)

    assert b1_start == datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert b1_end == datetime(2026, 9, 1, 12, 5, 0, tzinfo=timezone.utc)
    assert b2_start == datetime(2026, 9, 1, 12, 5, 0, tzinfo=timezone.utc)
    assert b2_end == datetime(2026, 9, 1, 12, 10, 0, tzinfo=timezone.utc)
    assert b1_start != b2_start

# --- CASE 3: M15 BOUNDARY ---
def test_case_3_m15_boundary():
    t1 = datetime(2026, 9, 1, 12, 14, 59, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 1, 12, 15, 0, tzinfo=timezone.utc)

    b1_start, _ = get_candle_bucket(t1, Timeframe.M15)
    b2_start, _ = get_candle_bucket(t2, Timeframe.M15)

    assert b1_start == datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert b2_start == datetime(2026, 9, 1, 12, 15, 0, tzinfo=timezone.utc)

# --- CASE 4: H1 BOUNDARY ---
def test_case_4_h1_boundary():
    t1 = datetime(2026, 9, 1, 12, 59, 59, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 1, 13, 0, 0, tzinfo=timezone.utc)

    b1_start, _ = get_candle_bucket(t1, Timeframe.H1)
    b2_start, _ = get_candle_bucket(t2, Timeframe.H1)

    assert b1_start == datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert b2_start == datetime(2026, 9, 1, 13, 0, 0, tzinfo=timezone.utc)

# --- CASE 5: SAME TIMESTAMP DETERMINISTIC TIE-BREAK ---
def test_case_5_same_timestamp_tie_break():
    ts = datetime(2026, 9, 1, 10, 0, 5, tzinfo=timezone.utc)
    ticks = [
        {"id": 2, "timestamp": ts, "symbol": "EURUSD", "bid": Decimal("1.08510"), "ask": Decimal("1.08520"), "volume": 1},
        {"id": 1, "timestamp": ts, "symbol": "EURUSD", "bid": Decimal("1.08500"), "ask": Decimal("1.08510"), "volume": 1},
    ]
    aggregator = CandleAggregator(timeframe=Timeframe.M1)
    cutoff = datetime(2026, 9, 1, 10, 1, 0, tzinfo=timezone.utc)
    candles = aggregator.aggregate_ticks(ticks, data_end_time=cutoff)

    assert len(candles) == 1
    # Because id 1 comes before id 2 after sorting, open must be 1.08500 and close must be 1.08510
    assert candles[0].open == Decimal("1.08500")
    assert candles[0].close == Decimal("1.08510")

# --- CASE 6: EMPTY BUCKET NO FABRICATION ---
def test_case_6_empty_bucket_no_fabrication():
    # Ticks at 12:00 and 12:02. No tick at 12:01.
    ticks = [
        {"timestamp": datetime(2026, 9, 1, 12, 0, 10, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08500"), "ask": Decimal("1.08510")},
        {"timestamp": datetime(2026, 9, 1, 12, 2, 10, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08520"), "ask": Decimal("1.08530")},
    ]
    cutoff = datetime(2026, 9, 1, 12, 3, 0, tzinfo=timezone.utc)
    aggregator = CandleAggregator(timeframe=Timeframe.M1)
    candles = aggregator.aggregate_ticks(ticks, data_end_time=cutoff)

    assert len(candles) == 2
    timestamps = [c.timestamp for c in candles]
    assert datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc) in timestamps
    assert datetime(2026, 9, 1, 12, 2, 0, tzinfo=timezone.utc) in timestamps
    # 12:01 must be ABSENT, not fabricated!
    assert datetime(2026, 9, 1, 12, 1, 0, tzinfo=timezone.utc) not in timestamps

# --- CASE 7: PARTIAL CANDLE HANDLING ---
def test_case_7_partial_candle():
    ticks = [
        {"timestamp": datetime(2026, 9, 1, 12, 7, 30, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08500"), "ask": Decimal("1.08510")},
    ]
    # Data ends at 12:07:30
    cutoff = datetime(2026, 9, 1, 12, 7, 30, tzinfo=timezone.utc)
    # Default: only_closed = True -> bucket 12:07:00..12:08:00 is NOT closed
    aggregator = CandleAggregator(timeframe=Timeframe.M1, only_closed=True)
    candles = aggregator.aggregate_ticks(ticks, data_end_time=cutoff)
    assert len(candles) == 0

    # If only_closed = False, it is returned with is_closed = False
    open_agg = CandleAggregator(timeframe=Timeframe.M1, only_closed=False)
    open_candles = open_agg.aggregate_ticks(ticks, data_end_time=cutoff)
    assert len(open_candles) == 1
    assert open_candles[0].is_closed is False

# --- CASE 8: DUPLICATE TICKS INPUT ---
def test_case_8_duplicate_ticks_input():
    ticks = [
        {"id": 1, "timestamp": datetime(2026, 9, 1, 10, 0, 10, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08500"), "ask": Decimal("1.08510")},
        {"id": 2, "timestamp": datetime(2026, 9, 1, 10, 0, 10, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08500"), "ask": Decimal("1.08510")},
    ]
    cutoff = datetime(2026, 9, 1, 10, 1, 0, tzinfo=timezone.utc)
    aggregator = CandleAggregator(timeframe=Timeframe.M1)
    candles = aggregator.aggregate_ticks(ticks, data_end_time=cutoff)
    assert len(candles) == 1
    assert candles[0].tick_volume == 2

# --- CASE 9: RE-RUN IDEMPOTENCY IN DATABASE ---
def test_case_9_re_run_idempotency():
    loader = CandleDatabaseLoader()
    c = AggregatedCandle(
        symbol="EURUSD",
        timeframe=Timeframe.M5,
        timestamp=datetime(2026, 9, 1, 14, 0, 0, tzinfo=timezone.utc),
        open=Decimal("1.085000"),
        high=Decimal("1.085500"),
        low=Decimal("1.084900"),
        close=Decimal("1.085300"),
        tick_volume=10,
        real_volume=0,
        spread=Decimal("1.20"),
    )

    # First run
    res1 = loader.upsert_candles([c])
    assert res1.inserted == 1
    assert res1.unchanged == 0
    assert res1.updated == 0

    # Second run with exact same data
    res2 = loader.upsert_candles([c])
    assert res2.inserted == 0
    assert res2.unchanged == 1
    assert res2.updated == 0

    # Cleanup test candle
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM market_candles WHERE symbol = 'EURUSD' AND timeframe = 'M5' AND timestamp = :ts"),
            {"ts": c.timestamp}
        )

# --- CASE 10: ZERO LOOK-AHEAD BIAS ---
def test_case_10_future_leakage_protection():
    # Regular tick in 12:05..12:10 bucket
    regular_tick = {
        "timestamp": datetime(2026, 9, 1, 12, 5, 30, tzinfo=timezone.utc),
        "symbol": "EURUSD",
        "bid": Decimal("1.08500"),
        "ask": Decimal("1.08510"),
    }
    # Extreme future tick in 12:10..12:15 bucket
    extreme_future_tick = {
        "timestamp": datetime(2026, 9, 1, 12, 10, 0, tzinfo=timezone.utc),
        "symbol": "EURUSD",
        "bid": Decimal("2.00000"),  # Extreme price spike in future bucket
        "ask": Decimal("2.00010"),
    }

    cutoff = datetime(2026, 9, 1, 12, 15, 0, tzinfo=timezone.utc)
    aggregator = CandleAggregator(timeframe=Timeframe.M5)
    candles = aggregator.aggregate_ticks([regular_tick, extreme_future_tick], data_end_time=cutoff)

    # There should be two M5 candles: 12:05:00 and 12:10:00
    assert len(candles) == 2
    c_1205 = [c for c in candles if c.timestamp == datetime(2026, 9, 1, 12, 5, 0, tzinfo=timezone.utc)][0]
    # The 12:05 candle MUST NOT be influenced by the 12:10 future tick!
    assert c_1205.high == Decimal("1.08500")
    assert c_1205.close == Decimal("1.08500")

# --- CASE 11: SPREAD ARITHMETIC MEAN ---
def test_case_11_spread_arithmetic_mean():
    ticks = [
        {"timestamp": datetime(2026, 9, 1, 10, 0, 10, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08500"), "ask": Decimal("1.08510")},  # spread = 0.00010 (1.0 pip)
        {"timestamp": datetime(2026, 9, 1, 10, 0, 20, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08500"), "ask": Decimal("1.08530")},  # spread = 0.00030 (3.0 pips)
    ]
    cutoff = datetime(2026, 9, 1, 10, 1, 0, tzinfo=timezone.utc)
    aggregator = CandleAggregator(timeframe=Timeframe.M1)
    candles = aggregator.aggregate_ticks(ticks, data_end_time=cutoff)

    assert len(candles) == 1
    # Average of 1.0 pip (0.00010) and 3.0 pips (0.00030) = 2.00 pips
    assert candles[0].spread == Decimal("2.00")

# --- CASE 12: VOLUME IS TICK COUNT NOT PRICE SUM ---
def test_case_12_volume_is_tick_count():
    ticks = [
        {"timestamp": datetime(2026, 9, 1, 10, 0, 10, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08500"), "ask": Decimal("1.08510"), "volume": 5},
        {"timestamp": datetime(2026, 9, 1, 10, 0, 20, tzinfo=timezone.utc), "symbol": "EURUSD", "bid": Decimal("1.08520"), "ask": Decimal("1.08530"), "volume": 7},
    ]
    cutoff = datetime(2026, 9, 1, 10, 1, 0, tzinfo=timezone.utc)
    aggregator = CandleAggregator(timeframe=Timeframe.M1)
    candles = aggregator.aggregate_ticks(ticks, data_end_time=cutoff)

    assert len(candles) == 1
    # tick_volume MUST BE 2 (count of ticks), NOT price sum or anything else
    assert candles[0].tick_volume == 2
    # real_volume is sum of volumes (5 + 7 = 12)
    assert candles[0].real_volume == 12

# --- INTEGRATION ENGINE TEST ---
def test_candle_aggregation_engine_flow():
    # Insert test ticks into market_ticks
    engine = get_engine()
    t1 = datetime(2026, 9, 2, 8, 0, 10, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 2, 8, 0, 30, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 2, 8, 1, 10, tzinfo=timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO market_ticks (timestamp, symbol, bid, ask, volume, source)
                VALUES
                    (:t1, 'EURUSD', 1.08500, 1.08510, 1, 'CANDLE_TEST'),
                    (:t2, 'EURUSD', 1.08550, 1.08560, 2, 'CANDLE_TEST'),
                    (:t3, 'EURUSD', 1.08530, 1.08540, 1, 'CANDLE_TEST');
            """),
            {"t1": t1, "t2": t2, "t3": t3}
        )

    agg_engine = CandleAggregationEngine()
    summary = agg_engine.aggregate_range(
        symbol="EURUSD",
        timeframe=Timeframe.M1,
        start_timestamp=datetime(2026, 9, 2, 8, 0, 0, tzinfo=timezone.utc),
        end_timestamp=datetime(2026, 9, 2, 8, 2, 0, tzinfo=timezone.utc),
        only_closed=True,
    )

    assert summary.ticks_processed >= 3
    assert summary.candles_generated >= 2
    assert summary.load_result.inserted >= 2

    # Cleanup test data
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM market_candles WHERE symbol = 'EURUSD' AND timestamp >= '2026-09-02 08:00:00+00'"))
        conn.execute(text("DELETE FROM market_ticks WHERE source = 'CANDLE_TEST'"))
