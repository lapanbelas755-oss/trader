"""Comprehensive test suite for Trader Machine V1 Data Ingestion & Normalization Layer."""
from datetime import datetime, timezone
from decimal import Decimal
import tempfile
from pathlib import Path
import pytest
from sqlalchemy import text

from core.ingestion.adapters import CSVAdapter, InMemoryAdapter, JSONAdapter
from core.ingestion.contract import IngestionStatus, ValidatedTickRecord
from core.ingestion.deduplicator import TickDeduplicator
from core.ingestion.integrity import IntegrityChecker
from core.ingestion.loader import DatabaseLoader
from core.ingestion.normalizer import TickNormalizer
from core.ingestion.pipeline import IngestionPipeline
from core.ingestion.report import IngestionQualityReport
from core.ingestion.validator import TickValidator
from database.connection import get_engine

from tests.fixtures.synthetic_ticks import (
    VALID_TICK_1,
    DUPLICATE_TICK_1,
    INVALID_BID_TICK,
    INVALID_ASK_TICK,
    INVERTED_SPREAD_TICK,
    NEGATIVE_VOLUME_TICK,
    MISSING_TIMESTAMP_TICK,
    NAIVE_TIMESTAMP_TICK,
    SAME_TIMESTAMP_TICK_A,
    SAME_TIMESTAMP_TICK_B,
    BACKWARD_TIMESTAMP_TICK,
    WEEKEND_GAP_TICK,
    MALFORMED_ROW_TICK,
)

# --- 1. NORMALIZATION TESTS ---

def test_normalization_valid_record():
    normalizer = TickNormalizer()
    norm = normalizer.normalize_record(VALID_TICK_1)
    assert norm["symbol"] == "EURUSD"
    assert norm["timestamp"].tzinfo == timezone.utc
    assert isinstance(norm["bid"], Decimal)
    assert norm["bid"] == Decimal("1.08520")
    assert norm["ask"] == Decimal("1.08530")
    assert norm["tick_direction"] == "FLAT"

def test_normalization_naive_timestamp():
    normalizer = TickNormalizer()
    norm = normalizer.normalize_record(NAIVE_TIMESTAMP_TICK)
    assert norm["timestamp"].tzinfo == timezone.utc
    assert norm["timestamp"].year == 2026

def test_normalization_symbol_casing():
    normalizer = TickNormalizer()
    raw = dict(VALID_TICK_1, symbol="  eurusd  ")
    norm = normalizer.normalize_record(raw)
    assert norm["symbol"] == "EURUSD"

def test_normalization_tick_direction_deterministic():
    normalizer = TickNormalizer()
    # First tick
    normalizer.normalize_record({"timestamp": "2026-09-01T10:00:00Z", "bid": "1.08500", "ask": "1.08510"})
    # Second tick: bid went up
    norm_up = normalizer.normalize_record({"timestamp": "2026-09-01T10:00:01Z", "bid": "1.08510", "ask": "1.08520"})
    assert norm_up["tick_direction"] == "UP"
    # Third tick: bid went down
    norm_down = normalizer.normalize_record({"timestamp": "2026-09-01T10:00:02Z", "bid": "1.08505", "ask": "1.08515"})
    assert norm_down["tick_direction"] == "DOWN"


# --- 2. VALIDATION TESTS ---

def test_validation_rejects_non_positive_bid():
    normalizer = TickNormalizer()
    validator = TickValidator()
    norm = normalizer.normalize_record(INVALID_BID_TICK)
    result = validator.validate_record(0, norm)
    assert not isinstance(result, ValidatedTickRecord)
    assert result.category == "PRICE"

def test_validation_rejects_non_positive_ask():
    normalizer = TickNormalizer()
    validator = TickValidator()
    norm = normalizer.normalize_record(INVALID_ASK_TICK)
    result = validator.validate_record(0, norm)
    assert not isinstance(result, ValidatedTickRecord)
    assert result.category == "PRICE"

def test_validation_rejects_inverted_spread():
    normalizer = TickNormalizer()
    validator = TickValidator()
    norm = normalizer.normalize_record(INVERTED_SPREAD_TICK)
    result = validator.validate_record(0, norm)
    assert not isinstance(result, ValidatedTickRecord)
    assert "Inverted spread" in result.reason

def test_validation_rejects_negative_volume():
    normalizer = TickNormalizer()
    validator = TickValidator()
    norm = normalizer.normalize_record(NEGATIVE_VOLUME_TICK)
    result = validator.validate_record(0, norm)
    assert not isinstance(result, ValidatedTickRecord)
    assert result.category == "VOLUME"

def test_validation_missing_timestamp():
    normalizer = TickNormalizer()
    with pytest.raises(ValueError, match="null or empty"):
        normalizer.normalize_record(MISSING_TIMESTAMP_TICK)

def test_validation_malformed_numeric():
    normalizer = TickNormalizer()
    with pytest.raises(ValueError, match="Invalid numeric format"):
        normalizer.normalize_record(MALFORMED_ROW_TICK)


# --- 3. DEDUPLICATION TESTS ---

def test_deduplication_exact_duplicate():
    normalizer = TickNormalizer()
    validator = TickValidator()
    dedup = TickDeduplicator()

    norm1 = normalizer.normalize_record(VALID_TICK_1)
    norm2 = normalizer.normalize_record(DUPLICATE_TICK_1)

    rec1 = validator.validate_record(0, norm1)
    rec2 = validator.validate_record(1, norm2)
    assert isinstance(rec1, ValidatedTickRecord)
    assert isinstance(rec2, ValidatedTickRecord)

    unique, dup_count = dedup.deduplicate([rec1, rec2])
    assert len(unique) == 1
    assert dup_count == 1

def test_deduplication_preserves_same_timestamp_different_values():
    normalizer = TickNormalizer()
    validator = TickValidator()
    dedup = TickDeduplicator()

    norm_a = normalizer.normalize_record(SAME_TIMESTAMP_TICK_A)
    norm_b = normalizer.normalize_record(SAME_TIMESTAMP_TICK_B)

    rec_a = validator.validate_record(0, norm_a)
    rec_b = validator.validate_record(1, norm_b)
    assert isinstance(rec_a, ValidatedTickRecord)
    assert isinstance(rec_b, ValidatedTickRecord)

    unique, dup_count = dedup.deduplicate([rec_a, rec_b])
    assert len(unique) == 2
    assert dup_count == 0


# --- 4. INTEGRITY TESTS ---

def test_integrity_detects_backward_timestamp():
    normalizer = TickNormalizer()
    validator = TickValidator()
    checker = IntegrityChecker()

    norm1 = normalizer.normalize_record(VALID_TICK_1)
    norm2 = normalizer.normalize_record(BACKWARD_TIMESTAMP_TICK)

    rec1 = validator.validate_record(0, norm1)
    rec2 = validator.validate_record(1, norm2)
    assert isinstance(rec1, ValidatedTickRecord)
    assert isinstance(rec2, ValidatedTickRecord)

    issues = checker.check([rec1, rec2])
    timestamp_issues = [i for i in issues if i.issue_type == "TIMESTAMP"]
    assert len(timestamp_issues) == 1
    assert "Backward timestamp" in timestamp_issues[0].message

def test_integrity_detects_market_gap():
    normalizer = TickNormalizer()
    validator = TickValidator()
    checker = IntegrityChecker(gap_threshold_seconds=3600.0)

    norm1 = normalizer.normalize_record(VALID_TICK_1)
    norm2 = normalizer.normalize_record(WEEKEND_GAP_TICK)

    rec1 = validator.validate_record(0, norm1)
    rec2 = validator.validate_record(1, norm2)
    assert isinstance(rec1, ValidatedTickRecord)
    assert isinstance(rec2, ValidatedTickRecord)

    issues = checker.check([rec1, rec2])
    gap_issues = [i for i in issues if i.issue_type == "GAP"]
    assert len(gap_issues) == 1
    assert "Market gap detected" in gap_issues[0].message


# --- 5. QUALITY REPORT TESTS ---

def test_quality_report_status_computation():
    # 1. Clean report -> PASS
    rep_pass = IngestionQualityReport(source_identifier="SRC", symbol="EURUSD", total_records=10, valid_records=10)
    assert rep_pass.determine_status() == IngestionStatus.PASS

    # 2. Warnings (duplicates / anomalies) -> PASS_WITH_WARNINGS
    rep_warn = IngestionQualityReport(
        source_identifier="SRC", symbol="EURUSD", total_records=10, valid_records=8, invalid_records=2
    )
    assert rep_warn.determine_status() == IngestionStatus.PASS_WITH_WARNINGS

    # 3. Empty or zero valid -> REJECTED
    rep_rej = IngestionQualityReport(source_identifier="SRC", symbol="EURUSD", total_records=5, valid_records=0)
    assert rep_rej.determine_status() == IngestionStatus.REJECTED


# --- 6. ADAPTER TESTS ---

def test_csv_adapter_and_json_adapter():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "test.csv"
        csv_path.write_text("timestamp,symbol,bid,ask,volume\n2026-09-01T10:00:00Z,EURUSD,1.0850,1.0851,1.0\n")

        csv_adapter = CSVAdapter()
        csv_records = list(csv_adapter.read_records(csv_path))
        assert len(csv_records) == 1
        assert csv_records[0]["symbol"] == "EURUSD"

        json_path = Path(tmpdir) / "test.json"
        json_path.write_text('[{"timestamp": "2026-09-01T10:00:00Z", "symbol": "EURUSD", "bid": "1.0850", "ask": "1.0851"}]')
        json_adapter = JSONAdapter()
        json_records = list(json_adapter.read_records(json_path))
        assert len(json_records) == 1
        assert json_records[0]["bid"] == "1.0850"


# --- 7. DATABASE LOADER & ROLLBACK TESTS ---

def test_database_loader_and_query():
    loader = DatabaseLoader(batch_size=10)
    test_dt = datetime(2026, 9, 1, 15, 0, 0, tzinfo=timezone.utc)
    rec = ValidatedTickRecord(
        symbol="EURUSD",
        timestamp=test_dt,
        bid=Decimal("1.085250"),
        ask=Decimal("1.085350"),
        volume=Decimal("2.5"),
        tick_direction="UP",
        source="LOADER_TEST",
    )

    inserted = loader.load_ticks([rec])
    assert inserted == 1

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT symbol, bid, ask, volume FROM market_ticks WHERE source = 'LOADER_TEST' AND timestamp = :ts"),
            {"ts": test_dt}
        ).fetchone()
        assert row is not None
        assert row[0] == "EURUSD"
        assert row[1] == Decimal("1.085250")
        assert row[2] == Decimal("1.085350")
        assert row[3] == Decimal("2.5000")

        # Cleanup
        conn.execute(text("DELETE FROM market_ticks WHERE source = 'LOADER_TEST'"))
        conn.commit()

def test_database_loader_atomic_rollback():
    loader = DatabaseLoader(batch_size=2)
    # Valid record
    rec1 = ValidatedTickRecord(
        symbol="EURUSD",
        timestamp=datetime(2026, 9, 1, 16, 0, 0, tzinfo=timezone.utc),
        bid=Decimal("1.085000"),
        ask=Decimal("1.085100"),
        source="ROLLBACK_TEST",
    )
    # Simulated invalid mock that fails during SQL execution (e.g. symbol exceeding length VARCHAR(16))
    rec_bad = ValidatedTickRecord.model_construct(
        symbol="VERY_LONG_SYMBOL_THAT_EXCEEDS_VARCHAR_16_CONSTRAINT",
        timestamp=datetime(2026, 9, 1, 16, 0, 1, tzinfo=timezone.utc),
        bid=Decimal("1.085000"),
        ask=Decimal("1.085100"),
        volume=Decimal("1.0"),
        tick_direction="UP",
        source="ROLLBACK_TEST",
    )

    with pytest.raises(Exception):
        loader.load_ticks([rec1, rec_bad])

    # Verify that rec1 was rolled back and NOT inserted
    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM market_ticks WHERE source = 'ROLLBACK_TEST'")
        ).scalar()
        assert count == 0


# --- 8. FULL PIPELINE INTEGRATION TEST ---

def test_full_pipeline_orchestration():
    fixtures = [
        VALID_TICK_1,
        DUPLICATE_TICK_1,       # Duplicate -> ignored
        INVALID_BID_TICK,       # Invalid -> rejected
        INVERTED_SPREAD_TICK,   # Inverted spread -> rejected
        SAME_TIMESTAMP_TICK_A,  # Valid
        SAME_TIMESTAMP_TICK_B,  # Valid (same ts, different price)
        WEEKEND_GAP_TICK,       # Valid, but gap flagged
    ]

    adapter = InMemoryAdapter(fixtures)
    pipeline = IngestionPipeline()
    report, inserted, rejected = pipeline.run(
        adapter, source=None, source_identifier="SYNTHETIC_BATCH", dry_run=False
    )

    # Verify report metrics
    assert report.total_records == 7
    assert report.invalid_records == 2  # INVALID_BID_TICK & INVERTED_SPREAD_TICK
    assert report.duplicate_records == 1  # DUPLICATE_TICK_1
    assert report.valid_records == 4    # VALID_TICK_1, SAME_TS_A, SAME_TS_B, WEEKEND_GAP
    assert report.gap_count >= 1
    assert report.ingestion_status == IngestionStatus.PASS_WITH_WARNINGS
    assert inserted == 4

    # Verify clean insertion in database and cleanup
    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM market_ticks WHERE source = 'SYNTHETIC_TEST'")
        ).scalar()
        assert count == 4
        conn.execute(text("DELETE FROM market_ticks WHERE source = 'SYNTHETIC_TEST'"))
        conn.commit()
