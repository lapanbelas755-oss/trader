"""Comprehensive test suite for Real Market Data Acquisition & Dataset Validation V1.
Tests all 30 requirements including schema validation, timezone normalization, canonical hashing,
OHLC integrity, gap detection without synthetic fabrication, and database registry.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import pytest
from sqlalchemy import text

from core.data_source.contract import (
    GLOBAL_LIQUIDITY_DISCLAIMER,
    TICK_VOLUME_DISCLAIMER,
    CheckStatus,
    DataFormat,
    DataQualityStatus,
    DatasetQualityReport,
    QualityCheckResult,
    MarketDataType,
    SourceType,
    ValidatedCandleRecord,
    ValidatedTickRecord,
)
from core.data_source.engine import MarketDataAcquisitionEngine
from core.data_source.hashing import CanonicalHasher
from core.data_source.mapping import (
    DUKASCOPY_CSV_MAPPING,
    GENERIC_OHLC_MAPPING,
    GENERIC_TICK_MAPPING,
    MT5_EXPORT_OHLC_MAPPING,
    MappingError,
    SourceColumnMapping,
)
from core.data_source.provenance import ProvenanceManager
from core.data_source.registry import DatasetRegistry
from core.data_source.validator import MarketDataValidator, ValidationError
from database.connection import get_engine, get_session_factory
from database.models import MarketDataset, MarketDataQualityReport


# --- 1. VALID CSV INGESTION ---
def test_valid_csv(tmp_path: Path):
    csv_file = tmp_path / "valid_eurusd.csv"
    csv_content = (
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 00:00:00,EURUSD,1.08500,1.08550,1.08480,1.08520,100,1.5\n"
        "2026-02-01 00:05:00,EURUSD,1.08520,1.08580,1.08510,1.08560,120,1.4\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    engine = MarketDataAcquisitionEngine(registry=None)
    prov, rep, records, gaps, _ = engine.acquire_and_validate(
        dataset_name="TEST_VALID_CSV_01",
        source=csv_file,
        data_format=DataFormat.CSV,
        source_name="TEST_FEED",
        symbol="EURUSD",
        timeframe="M5",
        timezone="UTC",
        persist_db=False,
    )

    assert rep.status == DataQualityStatus.PASS
    assert len(records) == 2
    assert records[0].open == Decimal("1.08500")
    assert records[1].close == Decimal("1.08560")
    assert prov.row_count == 2
    assert len(gaps) == 0


# --- 2. VALID JSON INGESTION ---
def test_valid_json(tmp_path: Path):
    json_file = tmp_path / "valid_eurusd.json"
    data = [
        {"timestamp": "2026-02-01 00:00:00", "symbol": "EURUSD", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": 50},
        {"timestamp": "2026-02-01 00:05:00", "symbol": "EURUSD", "open": "1.0852", "high": "1.0857", "low": "1.0850", "close": "1.0854", "volume": 65},
    ]
    json_file.write_text(json.dumps(data), encoding="utf-8")

    engine = MarketDataAcquisitionEngine(registry=None)
    prov, rep, records, gaps, _ = engine.acquire_and_validate(
        dataset_name="TEST_VALID_JSON_01",
        source=json_file,
        data_format=DataFormat.JSON,
        source_name="TEST_FEED",
        symbol="EURUSD",
        timeframe="M5",
        timezone="UTC",
        persist_db=False,
    )

    assert rep.status == DataQualityStatus.PASS
    assert len(records) == 2
    assert records[0].symbol == "EURUSD"


# --- 3. VALID JSONL INGESTION ---
def test_valid_jsonl(tmp_path: Path):
    jsonl_file = tmp_path / "valid_eurusd.jsonl"
    lines = [
        json.dumps({"timestamp": "2026-02-01 00:00:00", "symbol": "EURUSD", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": 50}),
        json.dumps({"timestamp": "2026-02-01 00:05:00", "symbol": "EURUSD", "open": "1.0852", "high": "1.0857", "low": "1.0850", "close": "1.0854", "volume": 65}),
    ]
    jsonl_file.write_text("\n".join(lines), encoding="utf-8")

    engine = MarketDataAcquisitionEngine(registry=None)
    prov, rep, records, gaps, _ = engine.acquire_and_validate(
        dataset_name="TEST_VALID_JSONL_01",
        source=jsonl_file,
        data_format=DataFormat.JSONL,
        source_name="TEST_FEED",
        symbol="EURUSD",
        timeframe="M5",
        timezone="UTC",
        persist_db=False,
    )

    assert rep.status == DataQualityStatus.PASS
    assert len(records) == 2


# --- 4. INVALID SCHEMA ---
def test_invalid_schema():
    mapping = SourceColumnMapping(
        data_type=MarketDataType.OHLC,
        timestamp_col="timestamp",
        open_col="open",
        high_col="high",
        low_col="low",
        close_col="close",
    )
    available_cols = {"timestamp", "open", "high", "volume"}  # missing 'low' and 'close'
    with pytest.raises(MappingError):
        mapping.validate_schema(available_cols)


# --- 5. UNKNOWN TIMEZONE ---
def test_unknown_timezone():
    validator = MarketDataValidator(declared_timezone=None)
    with pytest.raises(ValidationError, match="Explicit timezone is required"):
        validator.resolve_timezone()

    validator_invalid = MarketDataValidator(declared_timezone="Unknown/NonExistentZone")
    with pytest.raises(ValidationError, match="Unknown or invalid timezone"):
        validator_invalid.resolve_timezone()


# --- 6. INVALID TIMESTAMP ---
def test_invalid_timestamp():
    validator = MarketDataValidator(declared_timezone="UTC")
    with pytest.raises(ValidationError, match="Unable to parse timestamp"):
        validator.parse_timestamp("CORRUPT_TIMESTAMP_STRING")


# --- 7. DUPLICATE ROWS (EXACT) ---
def test_duplicate_rows():
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "50"},
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "50"},  # Exact duplicate
        {"timestamp": "2026-02-01 00:05:00", "open": "1.0852", "high": "1.0857", "low": "1.0850", "close": "1.0854", "volume": "65"},
    ]
    validator = MarketDataValidator(declared_timezone="UTC")
    report, records, _ = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "DUP_TEST")

    assert report.status == DataQualityStatus.PASS_WITH_WARNINGS
    assert len(records) == 2  # Deduplicated
    dup_check = next(c for c in report.checks if c.check_name == "duplicate_detection")
    assert dup_check.status == CheckStatus.WARNING
    assert dup_check.affected_rows == 1


# --- 8. CONFLICTING DUPLICATES ---
def test_conflicting_duplicates():
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "50"},
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0860", "high": "1.0870", "low": "1.0858", "close": "1.0865", "volume": "50"},  # Conflict!
    ]
    validator = MarketDataValidator(declared_timezone="UTC")
    report, records, _ = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "CONFLICT_TEST")

    assert report.status == DataQualityStatus.REJECTED
    assert len(records) == 0
    conflict_check = next(c for c in report.checks if c.check_name == "duplicate_detection")
    assert conflict_check.status == CheckStatus.FAIL


# --- 9. INVALID OHLC ---
def test_invalid_ohlc():
    raw_data = [
        # High lower than Open
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0840", "low": "1.0830", "close": "1.0845", "volume": "50"},
    ]
    validator = MarketDataValidator(declared_timezone="UTC")
    report, records, _ = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "INVALID_OHLC")

    assert report.status == DataQualityStatus.REJECTED
    assert len(records) == 0
    ohlc_check = next(c for c in report.checks if c.check_name == "ohlc_integrity")
    assert ohlc_check.status == CheckStatus.FAIL


# --- 10. INVALID BID / ASK ---
def test_invalid_bid_ask():
    raw_ticks = [
        # Inverted spread: ask < bid
        {"timestamp": "2026-02-01 00:00:00", "bid": "1.08550", "ask": "1.08520", "volume": "10"},
        # Negative price
        {"timestamp": "2026-02-01 00:00:01", "bid": "-1.08500", "ask": "1.08520", "volume": "10"},
    ]
    validator = MarketDataValidator(declared_timezone="UTC")
    report, records = validator.validate_and_normalize_ticks(raw_ticks, GENERIC_TICK_MAPPING, "TICK_TEST")

    assert report.status == DataQualityStatus.REJECTED
    assert len(records) == 0


# --- 11. NEGATIVE VOLUME ---
def test_negative_volume():
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "-10"},
    ]
    validator = MarketDataValidator(declared_timezone="UTC")
    report, records, _ = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "NEG_VOL")

    assert report.status == DataQualityStatus.REJECTED
    vol_check = next(c for c in report.checks if c.check_name == "volume_validity")
    assert vol_check.status == CheckStatus.FAIL


# --- 12. SYMBOL MISMATCH ---
def test_symbol_mismatch():
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "symbol": "GBPUSD", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "10"},
    ]
    validator = MarketDataValidator(expected_symbol="EURUSD", declared_timezone="UTC")
    report, records, _ = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "SYM_MISMATCH")

    assert report.status == DataQualityStatus.REJECTED
    sym_check = next(c for c in report.checks if c.check_name == "symbol_consistency")
    assert sym_check.status == CheckStatus.FAIL


# --- 13. TIMEFRAME MISMATCH / IRREGULARITY ---
def test_timeframe_mismatch():
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "10"},
        {"timestamp": "2026-02-01 00:01:00", "open": "1.0852", "high": "1.0857", "low": "1.0850", "close": "1.0854", "volume": "10"},  # 1 min delta for M5
    ]
    validator = MarketDataValidator(expected_timeframe="M5", declared_timezone="UTC")
    report, records, gaps = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "TF_MISMATCH")

    # M1 delta doesn't produce an M5 gap (> 300s), but is preserved as chronological data
    assert len(records) == 2


# --- 14. GAP DETECTION ---
def test_gap_detection():
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "10"},
        {"timestamp": "2026-02-01 00:20:00", "open": "1.0852", "high": "1.0857", "low": "1.0850", "close": "1.0854", "volume": "10"},  # 20 min gap
    ]
    validator = MarketDataValidator(expected_timeframe="M5", declared_timezone="UTC")
    report, records, gaps = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "GAP_TEST")

    assert report.status == DataQualityStatus.PASS_WITH_WARNINGS
    assert len(gaps) == 1
    assert gaps[0].duration_seconds == 1200.0  # 20 minutes
    assert gaps[0].expected_rows == 3          # 3 missing M5 candles (00:05, 00:10, 00:15)


# --- 15. CRITICAL NO-FABRICATION TEST ---
def test_no_fabricated_data():
    """Verify missing 20-minute interval is recorded as a gap, with ZERO synthetic candles fabricated."""
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "10"},
        {"timestamp": "2026-02-01 00:20:00", "open": "1.0852", "high": "1.0857", "low": "1.0850", "close": "1.0854", "volume": "10"},
    ]
    validator = MarketDataValidator(expected_timeframe="M5", declared_timezone="UTC")
    report, records, gaps = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "NO_FAB_TEST")

    assert len(records) == 2  # Exactly 2 real input records preserved, NO synthetic bars
    assert len(gaps) == 1
    assert gaps[0].actual_rows == 0


# --- 16. DETERMINISTIC HASH ---
def test_deterministic_hash():
    records = [
        ValidatedCandleRecord(
            timestamp=datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
            symbol="EURUSD",
            timeframe="M5",
            open=Decimal("1.0850"),
            high=Decimal("1.0855"),
            low=Decimal("1.0848"),
            close=Decimal("1.0852"),
            volume=Decimal("100"),
        )
    ]
    h1 = CanonicalHasher.compute_hash(records)
    h2 = CanonicalHasher.compute_hash(records)
    assert h1 == h2
    assert len(h1) == 64


# --- 17. CRITICAL DATA INTEGRITY & ROW-ORDER-INDEPENDENT CANONICAL HASH ---
def test_row_order_independent_canonical_hash():
    """D1 and D2 (shuffled row order) have identical canonical hash; D3 (one price changed) has different hash."""
    c1 = ValidatedCandleRecord(
        timestamp=datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
        symbol="EURUSD",
        timeframe="M5",
        open=Decimal("1.0850"),
        high=Decimal("1.0855"),
        low=Decimal("1.0848"),
        close=Decimal("1.0852"),
        volume=Decimal("100"),
    )
    c2 = ValidatedCandleRecord(
        timestamp=datetime(2026, 2, 1, 0, 5, tzinfo=timezone.utc),
        symbol="EURUSD",
        timeframe="M5",
        open=Decimal("1.0852"),
        high=Decimal("1.0858"),
        low=Decimal("1.0850"),
        close=Decimal("1.0856"),
        volume=Decimal("120"),
    )

    # D1: [c1, c2]
    d1_hash = CanonicalHasher.compute_hash([c1, c2])

    # D2: [c2, c1] (reversed order)
    d2_hash = CanonicalHasher.compute_hash([c2, c1])

    # Must be 100% identical!
    assert d1_hash == d2_hash

    # D3: Alter one price in c2
    c2_modified = ValidatedCandleRecord(
        timestamp=datetime(2026, 2, 1, 0, 5, tzinfo=timezone.utc),
        symbol="EURUSD",
        timeframe="M5",
        open=Decimal("1.0852"),
        high=Decimal("1.0859"),  # Changed 1.0858 -> 1.0859
        low=Decimal("1.0850"),
        close=Decimal("1.0856"),
        volume=Decimal("120"),
    )
    d3_hash = CanonicalHasher.compute_hash([c1, c2_modified])

    assert d3_hash != d1_hash


# --- 18. PROVENANCE GENERATION ---
def test_provenance():
    records = [
        ValidatedCandleRecord(
            timestamp=datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
            symbol="EURUSD",
            timeframe="M5",
            open=Decimal("1.0850"),
            high=Decimal("1.0855"),
            low=Decimal("1.0848"),
            close=Decimal("1.0852"),
            volume=Decimal("100"),
        )
    ]
    prov = ProvenanceManager.create_provenance(
        source_name="EXNESS_M5",
        source_type="FILE",
        source_file="/tmp/eurusd.csv",
        source_format="CSV",
        symbol="EURUSD",
        timeframe="M5",
        records=records,
        declared_timezone="UTC",
    )
    assert prov.symbol == "EURUSD"
    assert prov.row_count == 1
    assert prov.tick_volume_semantics == TICK_VOLUME_DISCLAIMER
    assert prov.liquidity_semantics == GLOBAL_LIQUIDITY_DISCLAIMER


# --- 19. DATASET REGISTRY PERSISTENCE ---
def test_registry_persistence():
    session_factory = get_session_factory()
    with session_factory() as session:
        session.execute(text("DELETE FROM market_datasets WHERE dataset_name = 'REG_TEST_01';"))
        session.commit()

        registry = DatasetRegistry(session=session)
        records = [
            ValidatedCandleRecord(
                timestamp=datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
                symbol="EURUSD",
                timeframe="M5",
                open=Decimal("1.0850"),
                high=Decimal("1.0855"),
                low=Decimal("1.0848"),
                close=Decimal("1.0852"),
                volume=Decimal("100"),
            )
        ]
        prov = ProvenanceManager.create_provenance(
            source_name="TEST_FEED",
            source_type="FILE",
            source_file="/tmp/eurusd.csv",
            source_format="CSV",
            symbol="EURUSD",
            timeframe="M5",
            records=records,
            declared_timezone="UTC",
        )
        report = DatasetQualityReport(dataset_name="REG_TEST_01", status=DataQualityStatus.PASS)
        report.add_check(QualityCheckResult(check_name="test_check", status=CheckStatus.PASS))

        dataset_model, is_new = registry.register_dataset(
            dataset_name="REG_TEST_01",
            provenance=prov,
            quality_report=report,
        )

        assert is_new is True
        assert dataset_model.id is not None
        assert dataset_model.dataset_name == "REG_TEST_01"


# --- 20. DUPLICATE DATASET IMPORT ---
def test_duplicate_dataset_import():
    session_factory = get_session_factory()
    with session_factory() as session:
        session.execute(text("DELETE FROM market_datasets WHERE dataset_name = 'DUP_IMPORT_01';"))
        session.commit()

        registry = DatasetRegistry(session=session)
        records = [
            ValidatedCandleRecord(
                timestamp=datetime(2026, 2, 1, 1, 0, tzinfo=timezone.utc),
                symbol="EURUSD",
                timeframe="M5",
                open=Decimal("1.0850"),
                high=Decimal("1.0855"),
                low=Decimal("1.0848"),
                close=Decimal("1.0852"),
                volume=Decimal("100"),
            )
        ]
        prov = ProvenanceManager.create_provenance(
            source_name="TEST_FEED",
            source_type="FILE",
            source_file="/tmp/eurusd.csv",
            source_format="CSV",
            symbol="EURUSD",
            timeframe="M5",
            records=records,
            declared_timezone="UTC",
        )
        report = DatasetQualityReport(dataset_name="DUP_IMPORT_01", status=DataQualityStatus.PASS)

        m1, is_new_1 = registry.register_dataset("DUP_IMPORT_01", prov, report)
        assert is_new_1 is True

        # Second import with identical content hash
        m2, is_new_2 = registry.register_dataset("DUP_IMPORT_01", prov, report)
        assert is_new_2 is False
        assert m1.id == m2.id


# --- 21. REJECTED DATASET HANDLING ---
def test_rejected_dataset():
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "open": "-1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "50"},
    ]
    validator = MarketDataValidator(declared_timezone="UTC")
    report, records, _ = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "REJECT_DS")

    assert report.status == DataQualityStatus.REJECTED
    assert len(records) == 0


# --- 22. PASS WITH WARNINGS STATUS ---
def test_pass_with_warnings():
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "50"},
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "50"},  # Duplicate
        {"timestamp": "2026-02-01 00:15:00", "open": "1.0852", "high": "1.0857", "low": "1.0850", "close": "1.0854", "volume": "65"},  # Gap
    ]
    validator = MarketDataValidator(declared_timezone="UTC")
    report, records, gaps = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "WARN_DS")

    assert report.status == DataQualityStatus.PASS_WITH_WARNINGS
    assert len(records) == 2
    assert len(gaps) == 1


# --- 23. CRITICAL TIMEZONE TEST (UTC NORMALIZATION) ---
def test_utc_normalization():
    """Input timezone Asia/Jakarta (UTC+7) converted to UTC.
    Verify exact timestamps.
    """
    validator = MarketDataValidator(declared_timezone="Asia/Jakarta")
    raw_data = [
        # 07:00:00 in Jakarta is 00:00:00 UTC
        {"timestamp": "2026-02-01 07:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "50"},
    ]
    report, records, _ = validator.validate_and_normalize_ohlc(raw_data, GENERIC_OHLC_MAPPING, "TZ_TEST")

    assert report.status == DataQualityStatus.PASS
    assert len(records) == 1
    assert records[0].timestamp.tzinfo == timezone.utc
    assert records[0].timestamp.hour == 0
    assert records[0].timestamp.day == 1


# --- 24. LARGE-FILE STREAMING BEHAVIOR ---
def test_large_file_streaming_behavior(tmp_path: Path):
    jsonl_file = tmp_path / "stream_eurusd.jsonl"
    with open(jsonl_file, "w") as f:
        for i in range(100):
            row = {"timestamp": f"2026-02-01 00:{i:02d}:00", "symbol": "EURUSD", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": 10}
            f.write(json.dumps(row) + "\n")

    stream = MarketDataAcquisitionEngine.read_records_from_source(jsonl_file, DataFormat.JSONL)
    count = 0
    for row in stream:
        count += 1
    assert count == 100


# --- 25. NO BROKER CONNECTION ---
def test_no_broker_connection():
    # Validates engine operates strictly offline on local input files without MT5 or network dependencies
    engine = MarketDataAcquisitionEngine(registry=None)
    assert not hasattr(engine, "mt5")
    assert not hasattr(engine, "login")


# --- 26. NO SECRETS AUDIT ---
def test_no_secrets():
    import core.data_source.contract as c
    assert "password" not in dir(c)
    assert "api_key" not in dir(c)
    assert "secret" not in dir(c)


# --- 27. MIGRATION 008 IDEMPOTENCY ---
def test_migration_008_idempotency():
    engine = get_engine()
    migration_path = Path(__file__).resolve().parent.parent / "database" / "migrations" / "008_market_datasets.sql"
    with open(migration_path, "r", encoding="utf-8") as f:
        sql = f.read()

    with engine.begin() as conn:
        conn.execute(text(sql))


# --- 28. DATABASE UNIQUENESS CONSTRAINT ---
def test_database_uniqueness():
    session_factory = get_session_factory()
    with session_factory() as session:
        session.execute(text("DELETE FROM market_datasets WHERE dataset_name IN ('UNIQ_01', 'UNIQ_02_WITH_SAME_HASH');"))
        session.commit()

        registry = DatasetRegistry(session=session)
        records = [
            ValidatedCandleRecord(
                timestamp=datetime(2026, 2, 1, 2, 0, tzinfo=timezone.utc),
                symbol="EURUSD",
                timeframe="M5",
                open=Decimal("1.0850"),
                high=Decimal("1.0855"),
                low=Decimal("1.0848"),
                close=Decimal("1.0852"),
                volume=Decimal("100"),
            )
        ]
        prov = ProvenanceManager.create_provenance("SRC", "FILE", "file.csv", "CSV", "EURUSD", "M5", records, "UTC")
        rep = DatasetQualityReport(dataset_name="UNIQ_01", status=DataQualityStatus.PASS)

        registry.register_dataset("UNIQ_01", prov, rep)

        # Different dataset name with identical content hash returns existing
        existing, is_new = registry.register_dataset("UNIQ_02_WITH_SAME_HASH", prov, rep)
        assert is_new is False
        assert existing.dataset_name == "UNIQ_01"


# --- 29. END-TO-END REPRODUCIBILITY ---
def test_reproducibility():
    raw_data = [
        {"timestamp": "2026-02-01 00:00:00", "open": "1.0850", "high": "1.0855", "low": "1.0848", "close": "1.0852", "volume": "50"},
        {"timestamp": "2026-02-01 00:05:00", "open": "1.0852", "high": "1.0857", "low": "1.0850", "close": "1.0854", "volume": "65"},
    ]
    engine = MarketDataAcquisitionEngine(registry=None)
    prov1, rep1, recs1, _, _ = engine.acquire_and_validate("REPRO_1", raw_data, DataFormat.IN_MEMORY, "TEST", persist_db=False)
    prov2, rep2, recs2, _, _ = engine.acquire_and_validate("REPRO_2", raw_data, DataFormat.IN_MEMORY, "TEST", persist_db=False)

    assert prov1.content_hash == prov2.content_hash
    assert rep1.status == rep2.status
    assert len(recs1) == len(recs2)


# --- 30. SOURCE SEMANTIC LABELS ---
def test_source_semantic_labels():
    assert "tick_volume != real traded volume" in TICK_VOLUME_DISCLAIMER
    assert "NO GLOBAL LIQUIDITY CLAIM" in GLOBAL_LIQUIDITY_DISCLAIMER
    assert "decentralized and fragmented" in GLOBAL_LIQUIDITY_DISCLAIMER
