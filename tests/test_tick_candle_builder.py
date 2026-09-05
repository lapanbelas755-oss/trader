"""Test suite for Tick to OHLC Candle Builder V1.
Covers M1, M5, M15, H1 aggregation, Mid/Bid/Ask OHLC streams, spread statistics,
tick counts, missing interval / weekend gap handling, critical non-fabrication,
provenance lineage, determinism, chronological ordering, and boundary transitions.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from core.candles.builder import (
    DerivedCandleRecord,
    InputTickRecord,
    InvalidTickError,
    OutOfOrderTickError,
    TickCandleBuilder,
    TimeBucketFloor,
)
from core.candles.contract import Timeframe


def make_tick(
    ts: datetime,
    bid: str,
    ask: str,
    last: str | None = None,
    symbol: str = "EURUSD",
    provider: str = "DUKASCOPY",
    source_ds: str = "DS_TEST_TICK",
) -> InputTickRecord:
    return InputTickRecord(
        timestamp=ts,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        last=Decimal(last) if last is not None else None,
        volume=Decimal("1"),
        provider=provider,
        source_dataset_id=source_ds,
    )


# --- CRITICAL TEST: MATHEMATICAL VERIFICATION ---
def test_critical_mathematical_m1():
    """Verify exact Mid OHLC values from user specification:
    09:00:01: Bid 1.1000, Ask 1.1002 -> Mid = 1.1001
    09:00:10: Bid 1.1005, Ask 1.1007 -> Mid = 1.1006
    09:00:30: Bid 1.0998, Ask 1.1000 -> Mid = 1.0999
    09:00:59: Bid 1.1003, Ask 1.1005 -> Mid = 1.1004
    Expected Mid M1:
      Open  = 1.1001
      High  = 1.1006
      Low   = 1.0999
      Close = 1.1004
    """
    base = datetime(2025, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(seconds=1), "1.1000", "1.1002"),
        make_tick(base + timedelta(seconds=10), "1.1005", "1.1007"),
        make_tick(base + timedelta(seconds=30), "1.0998", "1.1000"),
        make_tick(base + timedelta(seconds=59), "1.1003", "1.1005"),
    ]

    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))

    assert len(candles) == 1
    c = candles[0]
    assert c.mid_open == Decimal("1.1001")
    assert c.mid_high == Decimal("1.1006")
    assert c.mid_low == Decimal("1.0999")
    assert c.mid_close == Decimal("1.1004")
    assert c.tick_count == 4


# --- 1. M1 AGGREGATION ---
def test_m1_aggregation():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(seconds=5), "1.0850", "1.0852"),
        make_tick(base + timedelta(seconds=25), "1.0855", "1.0857"),
        # Next minute
        make_tick(base + timedelta(seconds=65), "1.0853", "1.0855"),
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 2
    assert candles[0].timestamp == base
    assert candles[1].timestamp == base + timedelta(minutes=1)


# --- 2. M5 AGGREGATION ---
def test_m5_aggregation():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(minutes=1), "1.0850", "1.0852"),
        make_tick(base + timedelta(minutes=3), "1.0860", "1.0862"),
        # Next 5-min bucket
        make_tick(base + timedelta(minutes=6), "1.0855", "1.0857"),
    ]
    builder = TickCandleBuilder(Timeframe.M5)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 2
    assert candles[0].timestamp == base
    assert candles[1].timestamp == base + timedelta(minutes=5)


# --- 3. M15 AGGREGATION ---
def test_m15_aggregation():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(minutes=4), "1.0850", "1.0852"),
        make_tick(base + timedelta(minutes=12), "1.0865", "1.0867"),
        # Next 15-min bucket
        make_tick(base + timedelta(minutes=16), "1.0860", "1.0862"),
    ]
    builder = TickCandleBuilder(Timeframe.M15)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 2
    assert candles[0].timestamp == base
    assert candles[1].timestamp == base + timedelta(minutes=15)


# --- 4. H1 AGGREGATION ---
def test_h1_aggregation():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(minutes=15), "1.0850", "1.0852"),
        make_tick(base + timedelta(minutes=45), "1.0870", "1.0872"),
        # Next hour bucket
        make_tick(base + timedelta(minutes=75), "1.0860", "1.0862"),
    ]
    builder = TickCandleBuilder(Timeframe.H1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 2
    assert candles[0].timestamp == base
    assert candles[1].timestamp == base + timedelta(hours=1)


# --- 5. BID OHLC ---
def test_bid_ohlc():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(seconds=10), "1.0850", "1.0852"),
        make_tick(base + timedelta(seconds=20), "1.0860", "1.0862"),
        make_tick(base + timedelta(seconds=30), "1.0840", "1.0842"),
        make_tick(base + timedelta(seconds=40), "1.0855", "1.0857"),
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    c = candles[0]
    assert c.bid_open == Decimal("1.0850")
    assert c.bid_high == Decimal("1.0860")
    assert c.bid_low == Decimal("1.0840")
    assert c.bid_close == Decimal("1.0855")


# --- 6. ASK OHLC ---
def test_ask_ohlc():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(seconds=10), "1.0850", "1.0853"),
        make_tick(base + timedelta(seconds=20), "1.0860", "1.0865"),
        make_tick(base + timedelta(seconds=30), "1.0840", "1.0842"),
        make_tick(base + timedelta(seconds=40), "1.0855", "1.0858"),
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    c = candles[0]
    assert c.ask_open == Decimal("1.0853")
    assert c.ask_high == Decimal("1.0865")
    assert c.ask_low == Decimal("1.0842")
    assert c.ask_close == Decimal("1.0858")


# --- 7. MID OHLC ---
def test_mid_ohlc():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(seconds=10), "1.0850", "1.0852"),  # mid = 1.0851
        make_tick(base + timedelta(seconds=20), "1.0856", "1.0860"),  # mid = 1.0858
        make_tick(base + timedelta(seconds=30), "1.0844", "1.0848"),  # mid = 1.0846
        make_tick(base + timedelta(seconds=40), "1.0852", "1.0854"),  # mid = 1.0853
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    c = candles[0]
    assert c.mid_open == Decimal("1.0851")
    assert c.mid_high == Decimal("1.0858")
    assert c.mid_low == Decimal("1.0846")
    assert c.mid_close == Decimal("1.0853")


# --- 8. SPREAD STATISTICS ---
def test_spread_statistics():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(seconds=5), "1.0850", "1.0852"),   # spread = 0.0002
        make_tick(base + timedelta(seconds=15), "1.0851", "1.0855"),  # spread = 0.0004
        make_tick(base + timedelta(seconds=25), "1.0852", "1.0853"),  # spread = 0.0001
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    c = candles[0]
    assert c.spread_open == Decimal("0.0002")
    assert c.spread_high == Decimal("0.0004")
    assert c.spread_low == Decimal("0.0001")
    assert c.spread_close == Decimal("0.0001")
    assert c.spread_min == Decimal("0.0001")
    assert c.spread_max == Decimal("0.0004")
    assert c.spread_median == Decimal("0.0002")


# --- 9. TICK COUNT ---
def test_tick_count():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(seconds=i * 5), "1.0850", "1.0852")
        for i in range(12)
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 1
    assert candles[0].tick_count == 12


# --- 10. MISSING INTERVAL DETECTION ---
def test_missing_interval():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(minutes=1), "1.0850", "1.0852"),
        # 20-min missing gap on M5
        make_tick(base + timedelta(minutes=26), "1.0855", "1.0857"),
    ]
    builder = TickCandleBuilder(Timeframe.M5)
    candles = list(builder.aggregate_stream(iter(ticks)))

    # Only 2 candles yielded, gap period has NO synthetic candles
    assert len(candles) == 2
    assert candles[0].timestamp == base
    assert candles[1].timestamp == base + timedelta(minutes=25)


# --- 11. WEEKEND GAP ---
def test_weekend_gap():
    # Friday 21:55 to Sunday 22:05
    fri = datetime(2025, 1, 17, 21, 58, 0, tzinfo=timezone.utc)
    sun = datetime(2025, 1, 19, 22, 2, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(fri, "1.0850", "1.0852"),
        make_tick(sun, "1.0845", "1.0847"),
    ]
    builder = TickCandleBuilder(Timeframe.M5)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 2
    assert candles[0].timestamp == datetime(2025, 1, 17, 21, 55, tzinfo=timezone.utc)
    assert candles[1].timestamp == datetime(2025, 1, 19, 22, 0, tzinfo=timezone.utc)


# --- 12. NO FABRICATION ---
def test_no_fabrication():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base, "1.0850", "1.0852"),
        # 1-hour gap on M1
        make_tick(base + timedelta(hours=1), "1.0860", "1.0862"),
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    # Exactly 2 candles must exist! Zero fabricated candles between 10:01 and 10:59
    assert len(candles) == 2


# --- 13. PROVENANCE LINEAGE ---
def test_provenance():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [make_tick(base, "1.0850", "1.0852", provider="DUKASCOPY", source_ds="DUKASCOPY_RAW_2025")]
    builder = TickCandleBuilder(Timeframe.M5)
    candles = list(builder.aggregate_stream(iter(ticks)))
    c = candles[0]
    assert c.provider == "DUKASCOPY"
    assert c.source_dataset_id == "DUKASCOPY_RAW_2025"
    assert c.derivation_version == "V1"


# --- 14. DETERMINISTIC RESULT ---
def test_deterministic_result():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(
            base + timedelta(seconds=i * 10),
            str(Decimal("1.08500") + Decimal(i) * Decimal("0.00010")),
            str(Decimal("1.08520") + Decimal(i) * Decimal("0.00010")),
        )
        for i in range(10)
    ]
    builder1 = TickCandleBuilder(Timeframe.M1)
    builder2 = TickCandleBuilder(Timeframe.M1)
    res1 = list(builder1.aggregate_stream(iter(ticks)))
    res2 = list(builder2.aggregate_stream(iter(ticks)))
    assert res1 == res2


# --- 15. CHANGED TICK AFFECTS EXPECTED CANDLE ---
def test_changed_tick_affects_expected_candle():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks_orig = [
        make_tick(base + timedelta(seconds=10), "1.0850", "1.0852"),  # Minute 0
        make_tick(base + timedelta(seconds=70), "1.0855", "1.0857"),  # Minute 1
    ]
    ticks_mod = [
        make_tick(base + timedelta(seconds=10), "1.0850", "1.0852"),
        make_tick(base + timedelta(seconds=70), "1.0890", "1.0892"),  # Modified tick in Minute 1
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    res_orig = list(builder.aggregate_stream(iter(ticks_orig)))
    res_mod = list(builder.aggregate_stream(iter(ticks_mod)))

    # Candle 0 is completely identical
    assert res_orig[0] == res_mod[0]
    # Candle 1 reflects the change
    assert res_orig[1].mid_close != res_mod[1].mid_close


# --- 16. IDENTICAL TIMESTAMP TICKS ---
def test_identical_timestamp_ticks():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base, "1.0850", "1.0852"),
        make_tick(base, "1.0851", "1.0853"),
        make_tick(base, "1.0849", "1.0851"),
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 1
    assert candles[0].tick_count == 3
    assert candles[0].bid_open == Decimal("1.0850")
    assert candles[0].bid_close == Decimal("1.0849")


# --- 17. TIMEZONE NORMALIZATION ---
def test_timezone_normalization():
    # Input with local offset (e.g. UTC+2)
    dt_local = datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    tick = make_tick(dt_local, "1.0850", "1.0852")
    builder = TickCandleBuilder(Timeframe.M5)
    candles = list(builder.aggregate_stream(iter([tick])))
    # 12:00 UTC+2 is 10:00 UTC
    assert candles[0].timestamp == datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc)


# --- 18. MISSING LAST (MID DERIVED FROM BID/ASK) ---
def test_missing_last():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    tick = make_tick(base, "1.0850", "1.0860", last=None)
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter([tick])))
    assert candles[0].mid_open == Decimal("1.0855")


# --- 19. INVALID PRICE ---
def test_invalid_price():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    # Inverted spread
    bad_tick = make_tick(base, "1.0860", "1.0850")
    builder = TickCandleBuilder(Timeframe.M1)
    with pytest.raises(InvalidTickError):
        list(builder.aggregate_stream(iter([bad_tick])))


# --- 20. CHRONOLOGICAL ORDERING ---
def test_chronological_ordering():
    base = datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
    ticks = [
        make_tick(base + timedelta(seconds=20), "1.0850", "1.0852"),
        make_tick(base + timedelta(seconds=10), "1.0851", "1.0853"),  # Out of order
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    with pytest.raises(OutOfOrderTickError):
        list(builder.aggregate_stream(iter(ticks)))


# --- 21. BOUNDARY TIMESTAMPS ---
def test_boundary_timestamps():
    t0 = datetime(2025, 2, 1, 10, 0, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2025, 2, 1, 10, 0, 59, 999999, tzinfo=timezone.utc)
    t2 = datetime(2025, 2, 1, 10, 1, 0, 0, tzinfo=timezone.utc)

    ticks = [
        make_tick(t0, "1.0850", "1.0852"),
        make_tick(t1, "1.0855", "1.0857"),
        make_tick(t2, "1.0860", "1.0862"),
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 2
    assert candles[0].timestamp == t0
    assert candles[0].tick_count == 2
    assert candles[1].timestamp == t2
    assert candles[1].tick_count == 1


# --- 22. MONTH BOUNDARY ---
def test_month_boundary():
    # Jan 31 23:59 to Feb 1 00:00
    t1 = datetime(2025, 1, 31, 23, 59, 30, tzinfo=timezone.utc)
    t2 = datetime(2025, 2, 1, 0, 0, 15, tzinfo=timezone.utc)
    ticks = [
        make_tick(t1, "1.0850", "1.0852"),
        make_tick(t2, "1.0855", "1.0857"),
    ]
    builder = TickCandleBuilder(Timeframe.H1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 2
    assert candles[0].timestamp == datetime(2025, 1, 31, 23, 0, tzinfo=timezone.utc)
    assert candles[1].timestamp == datetime(2025, 2, 1, 0, 0, tzinfo=timezone.utc)


# --- 23. YEAR BOUNDARY ---
def test_year_boundary():
    # Dec 31 23:59:45 to Jan 1 00:00:10
    t1 = datetime(2024, 12, 31, 23, 59, 45, tzinfo=timezone.utc)
    t2 = datetime(2025, 1, 1, 0, 0, 10, tzinfo=timezone.utc)
    ticks = [
        make_tick(t1, "1.0850", "1.0852"),
        make_tick(t2, "1.0855", "1.0857"),
    ]
    builder = TickCandleBuilder(Timeframe.M1)
    candles = list(builder.aggregate_stream(iter(ticks)))
    assert len(candles) == 2
    assert candles[0].timestamp == datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc)
    assert candles[1].timestamp == datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)


# --- 24. EMPTY DATASET ---
def test_empty_dataset():
    builder = TickCandleBuilder(Timeframe.M5)
    candles = list(builder.aggregate_stream(iter([])))
    assert len(candles) == 0


# --- 25. LARGE STREAMING DATASET ---
def test_large_streaming_dataset():
    base = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    # Stream 1,000 ticks across 100 minutes
    def tick_generator():
        for i in range(1000):
            ts = base + timedelta(seconds=i * 6)  # 1 tick every 6 seconds = 10 ticks per minute
            yield make_tick(ts, "1.0850", "1.0852")

    builder = TickCandleBuilder(Timeframe.M5)
    candles = list(builder.aggregate_stream(tick_generator()))

    # 1000 ticks * 6s = 6000s = 100 minutes = 20 M5 candles
    assert len(candles) == 20
    for c in candles:
        assert c.tick_count == 50  # 300s / 6s = 50 ticks per M5 candle
