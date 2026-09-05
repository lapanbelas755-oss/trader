"""Tests for Real EURUSD Data Quality Audit #1, BID-Only Semantics, and Resampling Lineage."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import pytest

from core.candles.contract import Timeframe
from core.candles.resampler import (
    BidOnlyDataError,
    CandleResampler,
    DerivedBidCandleRecord,
)
from core.data_source.contract import (
    CheckStatus,
    DataQualityStatus,
    TICK_VOLUME_DISCLAIMER,
    ValidatedCandleRecord,
)
from core.data_source.importer import MarketDataImporter
from core.data_source.mapping import ETC_UTC_OHLC_MAPPING
from core.data_source.staged import DataProvider, PROVIDER_SEMANTICS
from core.data_source.validator import MarketDataValidator


REAL_FILE_PATH = Path("/Users/macbook/Downloads/EUR-USD_1Minute_BID_2026-07-01_00_00-23_59_Etc_UTC.csv")


def make_m1_bar(
    minute_offset: int,
    open_p: str,
    high_p: str,
    low_p: str,
    close_p: str,
    vol: str = "50000000",
    base_ts: datetime = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
) -> ValidatedCandleRecord:
    return ValidatedCandleRecord(
        timestamp=base_ts + timedelta(minutes=minute_offset),
        symbol="EURUSD",
        timeframe="M1",
        open=Decimal(open_p),
        high=Decimal(high_p),
        low=Decimal(low_p),
        close=Decimal(close_p),
        volume=Decimal(vol),
        spread=None,
    )


# 1. BID-only schema
def test_bid_only_schema():
    candle = DerivedBidCandleRecord(
        source_dataset_id="DS_101",
        provider="USER_SUPPLIED_DATA",
        symbol="EURUSD",
        timeframe=Timeframe.M5,
        timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        price_type="BID",
        open=Decimal("1.14128"),
        high=Decimal("1.14139"),
        low=Decimal("1.14118"),
        close=Decimal("1.14134"),
        volume=Decimal("691950000"),
        m1_bars_count=5,
    )
    assert candle.price_type == "BID"
    assert candle.m1_bars_count == 5
    assert candle.open == Decimal("1.14128")
    assert candle.high == Decimal("1.14139")
    assert candle.low == Decimal("1.14118")
    assert candle.close == Decimal("1.14134")


# 2. No synthetic Ask
def test_no_synthetic_ask():
    candle = DerivedBidCandleRecord(
        source_dataset_id="DS_101",
        provider="USER_SUPPLIED_DATA",
        symbol="EURUSD",
        timeframe=Timeframe.M5,
        timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        open=Decimal("1.14128"),
        high=Decimal("1.14139"),
        low=Decimal("1.14118"),
        close=Decimal("1.14134"),
        volume=Decimal("100"),
        m1_bars_count=5,
    )
    with pytest.raises(BidOnlyDataError, match="Ask price stream is unavailable"):
        _ = candle.ask_open

    with pytest.raises(BidOnlyDataError, match="Ask price stream is unavailable"):
        _ = candle.ask_close


# 3. No synthetic Spread
def test_no_synthetic_spread():
    candle = DerivedBidCandleRecord(
        source_dataset_id="DS_101",
        provider="USER_SUPPLIED_DATA",
        symbol="EURUSD",
        timeframe=Timeframe.M5,
        timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        open=Decimal("1.14128"),
        high=Decimal("1.14139"),
        low=Decimal("1.14118"),
        close=Decimal("1.14134"),
        volume=Decimal("100"),
        m1_bars_count=5,
    )
    with pytest.raises(BidOnlyDataError, match="Spread is unavailable"):
        _ = candle.spread


# 4. No synthetic Mid
def test_no_synthetic_mid():
    candle = DerivedBidCandleRecord(
        source_dataset_id="DS_101",
        provider="USER_SUPPLIED_DATA",
        symbol="EURUSD",
        timeframe=Timeframe.M5,
        timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        open=Decimal("1.14128"),
        high=Decimal("1.14139"),
        low=Decimal("1.14118"),
        close=Decimal("1.14134"),
        volume=Decimal("100"),
        m1_bars_count=5,
    )
    with pytest.raises(BidOnlyDataError, match="Mid price stream is unavailable"):
        _ = candle.mid_close


# 5. UTC validation
def test_utc_validation():
    validator = MarketDataValidator(expected_symbol="EURUSD", expected_timeframe="M1", declared_timezone="UTC")
    ts = validator.parse_timestamp("2026-07-01T00:00:00+00:00")
    assert ts.tzinfo == timezone.utc
    assert ts.hour == 0
    assert ts.minute == 0


# 6. OHLC validation
def test_ohlc_validation():
    # High < Open
    with pytest.raises(ValueError):
        DerivedBidCandleRecord(
            source_dataset_id="DS_101",
            provider="USER_SUPPLIED_DATA",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
            timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
            open=Decimal("1.15000"),
            high=Decimal("1.14000"),
            low=Decimal("1.13000"),
            close=Decimal("1.13500"),
            m1_bars_count=5,
        )

    # Low > Close
    with pytest.raises(ValueError):
        DerivedBidCandleRecord(
            source_dataset_id="DS_101",
            provider="USER_SUPPLIED_DATA",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
            timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
            open=Decimal("1.14000"),
            high=Decimal("1.15000"),
            low=Decimal("1.14500"),
            close=Decimal("1.14100"),
            m1_bars_count=5,
        )


# 7. Duplicate detection
def test_duplicate_detection():
    validator = MarketDataValidator(expected_symbol="EURUSD", expected_timeframe="M1", declared_timezone="UTC")
    raw = [
        {"Etc/UTC": "2026-07-01T00:00:00+00:00", "Open": "1.14", "High": "1.15", "Low": "1.13", "Close": "1.14", "Volume": "100"},
        {"Etc/UTC": "2026-07-01T00:00:00+00:00", "Open": "1.14", "High": "1.15", "Low": "1.13", "Close": "1.14", "Volume": "100"},
    ]
    report, records, gaps = validator.validate_and_normalize_ohlc(raw, ETC_UTC_OHLC_MAPPING, "TEST_DUP")
    assert len(records) == 1
    dup_check = [c for c in report.checks if c.check_name == "duplicate_detection"][0]
    assert dup_check.status == CheckStatus.WARNING
    assert dup_check.affected_rows == 1


# 8. Gap detection
def test_gap_detection():
    validator = MarketDataValidator(expected_symbol="EURUSD", expected_timeframe="M1", declared_timezone="UTC")
    raw = [
        {"Etc/UTC": "2026-07-01T00:00:00+00:00", "Open": "1.14", "High": "1.15", "Low": "1.13", "Close": "1.14", "Volume": "100"},
        {"Etc/UTC": "2026-07-01T00:03:00+00:00", "Open": "1.14", "High": "1.15", "Low": "1.13", "Close": "1.14", "Volume": "100"},
    ]
    report, records, gaps = validator.validate_and_normalize_ohlc(raw, ETC_UTC_OHLC_MAPPING, "TEST_GAP")
    assert len(gaps) == 1
    assert gaps[0].expected_rows == 2
    assert gaps[0].actual_rows == 0  # No synthetic candles fabricated!


# 9. Volume semantics
def test_volume_semantics():
    candle = DerivedBidCandleRecord(
        source_dataset_id="DS_101",
        provider="USER_SUPPLIED_DATA",
        symbol="EURUSD",
        timeframe=Timeframe.M5,
        timestamp=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        open=Decimal("1.14128"),
        high=Decimal("1.14139"),
        low=Decimal("1.14118"),
        close=Decimal("1.14134"),
        volume=Decimal("50000000"),
        m1_bars_count=5,
    )
    assert candle.volume_semantics == TICK_VOLUME_DISCLAIMER
    assert "real traded volume" in candle.volume_semantics
    assert "!= institutional volume" in candle.volume_semantics


# 10. M1 -> M5 derivation
def test_m1_to_m5_derivation():
    m1_bars = [
        make_m1_bar(0, "1.1000", "1.1020", "1.0990", "1.1010", "10"),
        make_m1_bar(1, "1.1010", "1.1035", "1.1005", "1.1030", "20"),
        make_m1_bar(2, "1.1030", "1.1040", "1.1025", "1.1028", "30"),
        make_m1_bar(3, "1.1028", "1.1030", "1.0980", "1.0985", "40"),
        make_m1_bar(4, "1.0985", "1.1005", "1.0982", "1.1002", "50"),
    ]
    m5 = CandleResampler.resample_m1(m1_bars, Timeframe.M5, "DS_M1", "USER_SUPPLIED_DATA", "EURUSD")
    assert len(m5) == 1
    res = m5[0]
    assert res.open == Decimal("1.1000")
    assert res.high == Decimal("1.1040")
    assert res.low == Decimal("1.0980")
    assert res.close == Decimal("1.1002")
    assert res.volume == Decimal("150")
    assert res.m1_bars_count == 5


# 11. M5 provenance
def test_m5_provenance():
    m1_bars = [make_m1_bar(0, "1.1000", "1.1010", "1.0990", "1.1005")]
    m5 = CandleResampler.resample_m1(m1_bars, Timeframe.M5, "SOURCE_DS_999", "USER_SUPPLIED_DATA", "EURUSD")
    assert m5[0].source_dataset_id == "SOURCE_DS_999"
    assert m5[0].provider == "USER_SUPPLIED_DATA"
    assert m5[0].symbol == "EURUSD"
    assert m5[0].derivation_version == "V1"


# 12. No-fabrication
def test_no_fabrication():
    # Only minute 0 and minute 15 provided (minutes 1-14 missing)
    m1_bars = [
        make_m1_bar(0, "1.1000", "1.1010", "1.0990", "1.1005"),
        make_m1_bar(15, "1.1010", "1.1020", "1.1005", "1.1015"),
    ]
    m5 = CandleResampler.resample_m1(m1_bars, Timeframe.M5, "DS_GAP", "USER_SUPPLIED_DATA", "EURUSD")
    # Only bucket 00:00 and bucket 00:15 should exist; 00:05 and 00:10 must NOT be fabricated!
    assert len(m5) == 2
    assert m5[0].timestamp == datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert m5[1].timestamp == datetime(2026, 7, 1, 0, 15, tzinfo=timezone.utc)


# 13. M15 derivation
def test_m15_derivation():
    m1_bars = [
        make_m1_bar(i, "1.1000", "1.1050" if i == 7 else "1.1010", "1.0950" if i == 12 else "1.0990", "1.1020" if i == 14 else "1.1005", "10")
        for i in range(15)
    ]
    m15 = CandleResampler.resample_m1(m1_bars, Timeframe.M15, "DS_M1", "USER_SUPPLIED_DATA", "EURUSD")
    assert len(m15) == 1
    assert m15[0].open == Decimal("1.1000")
    assert m15[0].high == Decimal("1.1050")
    assert m15[0].low == Decimal("1.0950")
    assert m15[0].close == Decimal("1.1020")
    assert m15[0].volume == Decimal("150")
    assert m15[0].m1_bars_count == 15


# 14. H1 derivation
def test_h1_derivation():
    m1_bars = [
        make_m1_bar(i, "1.1000" if i == 0 else "1.1005", "1.1080" if i == 30 else "1.1010", "1.0920" if i == 45 else "1.0990", "1.1040" if i == 59 else "1.1005", "10")
        for i in range(60)
    ]
    h1 = CandleResampler.resample_m1(m1_bars, Timeframe.H1, "DS_M1", "USER_SUPPLIED_DATA", "EURUSD")
    assert len(h1) == 1
    assert h1[0].open == Decimal("1.1000")
    assert h1[0].high == Decimal("1.1080")
    assert h1[0].low == Decimal("1.0920")
    assert h1[0].close == Decimal("1.1040")
    assert h1[0].volume == Decimal("600")
    assert h1[0].m1_bars_count == 60


# 15. Source attribution safety
def test_source_attribution_safety():
    assert DataProvider.USER_SUPPLIED.value == "USER_SUPPLIED"
    assert DataProvider.UNKNOWN.value == "UNKNOWN"
    assert "User-supplied" in PROVIDER_SEMANTICS[DataProvider.USER_SUPPLIED]


# 16. Real dataset integration test
def test_real_dataset_integrity_verification():
    if not REAL_FILE_PATH.exists():
        pytest.skip(f"Real data file not found at {REAL_FILE_PATH}")

    importer = MarketDataImporter()
    res = importer.import_dataset(
        source_file=REAL_FILE_PATH,
        symbol="EURUSD",
        timeframe="M1",
        timezone_str="UTC",
        source_name="USER_SUPPLIED_DATA",
        mapping_profile="etc_utc",
        dry_run=True,
    )
    assert res["status"] == "DRY_RUN_PASS"
    assert res["row_count"] == 1423
    assert res["errors_count"] == 0
    assert len(res["gaps"]) == 13
    assert res["quality_status"] == "PASS_WITH_WARNINGS"
