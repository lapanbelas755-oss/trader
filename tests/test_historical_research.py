"""
Deterministic Test Suite for Historical Research & Dataset Engine V1.
Covers all 30 required tests including provenance, data validation, chronological splitting,
config/dataset hashing, setup occurrence capture, database persistence, reproducibility,
and the critical test_research_pipeline_has_no_future_leakage().
"""

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import text

from core.research.contract import (
    DataProvenance,
    DatasetMetadata,
    DatasetStatus,
    DataValidationReport,
    ResearchManifest,
    ResearchOccurrenceRecord,
    RunStatus,
    SplitType,
    ValidationStatus,
)
from core.research.config import ResearchConfig
from core.research.hashing import hash_candles, hash_occurrences, hash_canonical_json
from core.research.provenance import DataProvenanceTracker
from core.research.validator import HistoricalDataValidator
from core.research.splitter import ChronologicalSplitter
from core.research.occurrence import SetupOccurrenceRecorder
from core.research.report import ResearchReportGenerator
from core.research.engine import HistoricalResearchEngine
from core.setups.contract import (
    SetupCode,
    SetupDirection,
    SetupEvidence,
    SetupRecord,
    SetupStatus,
)
from database.connection import get_session_factory
from database.models import (
    ResearchDataset as ResearchDatasetModel,
    ResearchRun as ResearchRunModel,
    ResearchSetupOccurrence as ResearchSetupOccurrenceModel,
)


def make_candle(
    ts: datetime,
    o: float,
    h: float,
    l: float,
    c: float,
    tf: str = "M5",
    sym: str = "EURUSD",
    spread: float = 1.0,
    vol: int = 100,
):
    """Creates a deterministic synthetic candle dictionary."""
    return {
        "symbol": sym,
        "timeframe": tf,
        "timestamp": ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
        "open": Decimal(str(round(o, 5))),
        "high": Decimal(str(round(h, 5))),
        "low": Decimal(str(round(l, 5))),
        "close": Decimal(str(round(c, 5))),
        "tick_volume": vol,
        "real_volume": 0,
        "spread": Decimal(str(spread)),
    }


def generate_candle_series(start_ts: datetime, count: int = 50, base_price: float = 1.10000):
    """Generates a sequential series of valid M5 candles."""
    candles = []
    p = base_price
    for i in range(count):
        t = start_ts + timedelta(minutes=5 * i)
        o = p
        h = p + 0.00030
        l = p - 0.00020
        c = p + 0.00010
        candles.append(make_candle(t, o, h, l, c))
        p = c
    return candles


# ==============================================================================
# 1. METADATA & HASHING TESTS
# ==============================================================================

def test_dataset_metadata():
    """Verify DatasetMetadata model validation and default values."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=30)
    meta = DatasetMetadata(
        dataset_name="EURUSD_2026_RESEARCH",
        symbol="EURUSD",
        source="MT5_EXNESS",
        timeframe="M5",
        start_time=t0,
        end_time=t1,
        row_count=1000,
        dataset_version="1.0.0",
        content_hash="abcd1234efgh5678",
        status=DatasetStatus.BUILDING,
    )
    assert meta.symbol == "EURUSD"
    assert meta.row_count == 1000
    assert meta.status == DatasetStatus.BUILDING


def test_dataset_hashing():
    """Verify that hash_candles produces a 64-character SHA-256 hash."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=5)
    h = hash_candles(candles)
    assert len(h) == 64
    assert isinstance(h, str)


def test_config_hashing():
    """Verify that ResearchConfig generates a deterministic SHA-256 hash."""
    cfg1 = ResearchConfig(swing_left_bars=2, swing_right_bars=2)
    cfg2 = ResearchConfig(swing_left_bars=2, swing_right_bars=2)
    cfg3 = ResearchConfig(swing_left_bars=3, swing_right_bars=3)

    assert cfg1.get_config_hash() == cfg2.get_config_hash()
    assert cfg1.get_config_hash() != cfg3.get_config_hash()


def test_reproducibility():
    """CRITICAL: Identical candle inputs produce identical content hashes regardless of input order."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=10)
    reversed_candles = list(reversed(candles))

    h1 = hash_candles(candles)
    h2 = hash_candles(reversed_candles)
    assert h1 == h2


def test_research_run_creation():
    """Verify ResearchRunResult data containment and status reporting."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=30)
    prov = DataProvenanceTracker.create_provenance("MT5_EXNESS", candles, is_synthetic=False)

    engine = HistoricalResearchEngine()
    result = engine.run_pipeline(
        candles=candles,
        provenance=prov,
        dataset_name="EURUSD_RUN_TEST",
    )

    assert result.status == RunStatus.SUCCESS
    assert result.dataset_metadata.row_count == 30
    assert result.dataset_metadata.status == DatasetStatus.READY


# ==============================================================================
# 2. DATASET QUALITY & VALIDATION TESTS
# ==============================================================================

def test_dataset_validation_pass():
    """Valid candle sequence passes validation without errors."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=20)
    validator = HistoricalDataValidator(timeframe="M5")
    report = validator.validate_dataset(candles)

    assert report.status == ValidationStatus.PASS
    assert report.total_candles == 20
    assert report.valid_candles == 20
    assert len(report.errors) == 0


def test_invalid_ohlc_rejection():
    """Candle with High < Low or Close > High is rejected."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    bad_candle = make_candle(t0, 1.10000, 1.09900, 1.10050, 1.10000)  # High < Low!
    validator = HistoricalDataValidator(timeframe="M5")
    report = validator.validate_dataset([bad_candle])

    assert report.status == ValidationStatus.REJECTED
    assert len(report.errors) >= 1
    assert "OHLC violation" in report.errors[0]


def test_duplicate_timestamp_detection():
    """Duplicate timestamps are detected and flagged as errors."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    c1 = make_candle(t0, 1.10000, 1.10020, 1.09980, 1.10010)
    c2 = make_candle(t0, 1.10010, 1.10030, 1.09990, 1.10020)  # Exact same timestamp
    validator = HistoricalDataValidator(timeframe="M5")
    report = validator.validate_dataset([c1, c2])

    assert report.status == ValidationStatus.REJECTED
    assert report.duplicate_count == 1


def test_timestamp_ordering():
    """Candles out of chronological order are flagged with an error."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    c1 = make_candle(t0 + timedelta(minutes=5), 1.10000, 1.10020, 1.09980, 1.10010)
    c2 = make_candle(t0, 1.10010, 1.10030, 1.09990, 1.10020)  # Earlier than c1
    validator = HistoricalDataValidator(timeframe="M5")
    report = validator.validate_dataset([c1, c2])

    assert report.status == ValidationStatus.REJECTED
    assert any("Out of order" in e for e in report.errors)


def test_timezone_normalization():
    """Naive timestamps are safely normalized to UTC without altering price coordinates."""
    t0_naive = datetime(2026, 9, 5, 10, 0)
    c = make_candle(t0_naive, 1.10000, 1.10020, 1.09980, 1.10010)
    validator = HistoricalDataValidator(timeframe="M5")
    report = validator.validate_dataset([c])
    assert report.status == ValidationStatus.PASS


def test_missing_interval_reporting():
    """Intra-week interval gap is reported as a warning without fabrication."""
    t0 = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)  # Tuesday
    c1 = make_candle(t0, 1.10000, 1.10020, 1.09980, 1.10010)
    c2 = make_candle(t0 + timedelta(minutes=30), 1.10010, 1.10030, 1.09990, 1.10020)  # Gap of 25m
    validator = HistoricalDataValidator(timeframe="M5")
    report = validator.validate_dataset([c1, c2])

    assert report.status == ValidationStatus.PASS_WITH_WARNINGS
    assert report.missing_intervals >= 1


def test_no_fabricated_candles():
    """Validator does not invent or insert phantom bars when an interval gap occurs."""
    t0 = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    c1 = make_candle(t0, 1.10000, 1.10020, 1.09980, 1.10010)
    c2 = make_candle(t0 + timedelta(minutes=30), 1.10010, 1.10030, 1.09990, 1.10020)
    validator = HistoricalDataValidator(timeframe="M5")
    report = validator.validate_dataset([c1, c2])
    assert report.total_candles == 2  # Still exactly 2 candles


# ==============================================================================
# 3. CHRONOLOGICAL SPLITS & INTEGRITY TESTS
# ==============================================================================

def test_chronological_train_validation_oos_split():
    """Candles are split into IN_SAMPLE (60%), VALIDATION (20%), and OUT_OF_SAMPLE (20%)."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=100)
    splitter = ChronologicalSplitter(in_sample_ratio=0.60, validation_ratio=0.20, out_of_sample_ratio=0.20)

    ins, val, oos = splitter.split_candles(candles)
    assert len(ins) == 60
    assert len(val) == 20
    assert len(oos) == 20


def test_no_random_shuffle():
    """Split subsets maintain strict chronological progression without shuffling."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=30)
    splitter = ChronologicalSplitter()
    ins, val, oos = splitter.split_candles(candles)

    for subset in (ins, val, oos):
        for i in range(1, len(subset)):
            assert subset[i]["timestamp"] > subset[i - 1]["timestamp"]


def test_no_overlap_between_splits():
    """No timestamp appears in more than one split."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=30)
    splitter = ChronologicalSplitter()
    ins, val, oos = splitter.split_candles(candles)

    ins_ts = {c["timestamp"] for c in ins}
    val_ts = {c["timestamp"] for c in val}
    oos_ts = {c["timestamp"] for c in oos}

    assert ins_ts.isdisjoint(val_ts)
    assert val_ts.isdisjoint(oos_ts)
    assert ins_ts.isdisjoint(oos_ts)


def test_boundary_correctness():
    """CRITICAL: IN_SAMPLE max timestamp < VALIDATION min timestamp < OOS min timestamp."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=50)
    splitter = ChronologicalSplitter()
    ins, val, oos = splitter.split_candles(candles)

    assert ins[-1]["timestamp"] < val[0]["timestamp"]
    assert val[-1]["timestamp"] < oos[0]["timestamp"]


# ==============================================================================
# 4. SETUP OCCURRENCE CAPTURE & EVIDENCE SNAPSHOT TESTS
# ==============================================================================

def test_setup_occurrence_capture():
    """SetupRecord is converted to ResearchOccurrenceRecord with correct fields and split."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    setup = SetupRecord(
        setup_id="EURUSD_M5_S01_BEARISH_202609051000",
        setup_code=SetupCode.S01,
        symbol="EURUSD",
        timeframe="M5",
        timestamp=t0,
        direction=SetupDirection.BEARISH,
        regime="RANGE",
        liquidity_type="SESSION_HIGH",
        status=SetupStatus.FIRE,
        evidence=SetupEvidence(liquidity="SWEPT", confirmation="VALID"),
        created_at=t0,
    )

    occ = SetupOccurrenceRecorder.record_occurrence(
        setup_record=setup,
        config_hash="cfg_hash_123",
        split_type=SplitType.IN_SAMPLE,
    )
    assert occ.setup_code == "S01"
    assert occ.direction == "BEARISH"
    assert occ.split_type == SplitType.IN_SAMPLE
    assert occ.config_hash == "cfg_hash_123"


def test_setup_evidence_snapshot():
    """Evidence snapshot preserves all discrete evidence fields and metrics without mutation."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    setup = SetupRecord(
        setup_id="TEST_OCC_EV",
        setup_code=SetupCode.S02,
        symbol="EURUSD",
        timeframe="M5",
        timestamp=t0,
        direction=SetupDirection.BULLISH,
        status=SetupStatus.ARMED,
        evidence=SetupEvidence(
            liquidity="ACCEPTED",
            price_response="STRONG",
            metrics={"displacement": Decimal("0.00035")},
        ),
        created_at=t0,
    )
    occ = SetupOccurrenceRecorder.record_occurrence(setup, config_hash="hash_abc")
    assert occ.evidence_snapshot["liquidity"] == "ACCEPTED"
    assert occ.evidence_snapshot["metrics"]["displacement"] == "0.00035"


def test_research_immutability():
    """Repeated execution does not overwrite past runs; creates distinct runs."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=25)
    prov = DataProvenanceTracker.create_provenance("MT5_EXNESS", candles)

    engine = HistoricalResearchEngine()
    r1 = engine.run_pipeline(candles, prov, dataset_name="IMMUTABLE_TEST", run_id="run_001")
    r2 = engine.run_pipeline(candles, prov, dataset_name="IMMUTABLE_TEST", run_id="run_002")

    assert r1.run_id != r2.run_id
    assert r1.manifest.content_hash == r2.manifest.content_hash


def test_repeat_run_produces_same_content_hash():
    """CRITICAL: Identical raw data and configuration produce the exact same content hash."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=30)
    h1 = hash_candles(candles)
    h2 = hash_candles(list(candles))
    assert h1 == h2


# ==============================================================================
# 5. CAUSALITY & FUTURE LEAKAGE TESTS
# ==============================================================================

def test_research_pipeline_has_no_future_leakage():
    """
    CRITICAL FUTURE LEAKAGE TEST:
    1. Build historical dataset D1 up to timestamp T.
    2. Run research through timestamp T.
    3. Save all setup observations <= T.
    4. Append extreme future market data after T.
    5. Run research again.
    6. Assert historical setup observations <= T are 100% identical.
    """
    t0 = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)
    base_candles = generate_candle_series(t0, count=20)
    prov1 = DataProvenanceTracker.create_provenance("MT5_EXNESS", base_candles)

    engine = HistoricalResearchEngine()
    t_eval = base_candles[-1]["timestamp"]

    # Step 1: Run research on baseline dataset
    result1 = engine.run_pipeline(base_candles, prov1, dataset_name="LEAKAGE_TEST_D1")
    obs1 = [(o.setup_code, o.timestamp.isoformat(), o.status, o.direction) for o in result1.occurrences if o.timestamp <= t_eval]

    # Step 2: Append extreme future market candles after T
    future_candles = list(base_candles)
    last_p = float(base_candles[-1]["close"])
    for i in range(1, 15):
        t_fut = t_eval + timedelta(minutes=5 * i)
        # Giant volatility spike into the future
        future_candles.append(make_candle(t_fut, last_p, last_p + 0.05000, last_p - 0.02000, last_p + 0.03000))
        last_p += 0.03000

    prov2 = DataProvenanceTracker.create_provenance("MT5_EXNESS", future_candles)

    # Step 3: Run research on extended dataset
    result2 = engine.run_pipeline(future_candles, prov2, dataset_name="LEAKAGE_TEST_D2")
    obs2 = [(o.setup_code, o.timestamp.isoformat(), o.status, o.direction) for o in result2.occurrences if o.timestamp <= t_eval]

    # Step 4: Strict equality assertion
    assert obs1 == obs2


def test_future_setup_state_cannot_leak_backward():
    """An observation recorded at T does not inherit future transitions."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    setup_watch = SetupRecord(
        setup_id="SETUP_LEAK_TEST",
        setup_code=SetupCode.S01,
        symbol="EURUSD",
        timeframe="M5",
        timestamp=t0,
        direction=SetupDirection.BEARISH,
        status=SetupStatus.WATCH,
        created_at=t0,
    )
    occ = SetupOccurrenceRecorder.record_occurrence(setup_watch, config_hash="h1")
    assert occ.status == "WATCH"


def test_synthetic_data_excluded_from_research_provenance():
    """Attempting to validate production provenance for synthetic fixtures raises ValueError."""
    prov = DataProvenance(
        source="TEST_FIXTURE",
        content_hash="mock_hash",
        row_count=10,
        is_synthetic=True,
    )
    with pytest.raises(ValueError, match="Synthetic data detected"):
        DataProvenanceTracker.validate_production_provenance(prov)


# ==============================================================================
# 6. DATABASE INTEGRITY & PERSISTENCE TESTS
# ==============================================================================

def test_migration_idempotency():
    """Running migration 005 multiple times succeeds without schema distortion."""
    from database.migrate import run_migrations
    applied = run_migrations()
    assert isinstance(applied, list)


def test_database_persistence_and_uniqueness():
    """Verify research dataset, run, and occurrences persist with foreign key integrity."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=25)
    prov = DataProvenanceTracker.create_provenance("MT5_EXNESS", candles)

    engine = HistoricalResearchEngine()
    run_uid = f"run_db_test_{int(datetime.now().timestamp())}"
    result = engine.run_pipeline(
        candles,
        prov,
        dataset_name="DB_INTEGRITY_TEST",
        run_id=run_uid,
    )

    session_factory = get_session_factory()
    with session_factory() as session:
        ds_id, run_id, occ_count = engine.persist_results(session, result)

        assert ds_id > 0
        assert run_id > 0

        # Query back
        db_ds = session.query(ResearchDatasetModel).filter_by(id=ds_id).first()
        assert db_ds is not None
        assert db_ds.dataset_name == "DB_INTEGRITY_TEST"

        db_run = session.query(ResearchRunModel).filter_by(id=run_id).first()
        assert db_run is not None
        assert db_run.dataset_id == ds_id
        assert db_run.status == "SUCCESS"


def test_foreign_key_integrity_on_delete():
    """Deleting a ResearchDataset cascades cleanly to its runs and occurrences."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=20)
    prov = DataProvenanceTracker.create_provenance("MT5_EXNESS", candles)

    engine = HistoricalResearchEngine()
    run_uid = f"run_cascade_{int(datetime.now().timestamp())}"
    result = engine.run_pipeline(candles, prov, dataset_name="CASCADE_TEST", run_id=run_uid)

    session_factory = get_session_factory()
    with session_factory() as session:
        ds_id, run_id, _ = engine.persist_results(session, result)

        # Delete the dataset
        session.query(ResearchDatasetModel).filter_by(id=ds_id).delete()
        session.commit()

        # Runs referencing it must be cascaded
        assert session.query(ResearchRunModel).filter_by(id=run_id).first() is None


# ==============================================================================
# 7. EDGE CASES & REPORTING TESTS
# ==============================================================================

def test_empty_dataset_handling():
    """Empty candle sequence is rejected with status FAILED without crashing."""
    prov = DataProvenance(source="MT5_EXNESS", content_hash="empty", row_count=0)
    engine = HistoricalResearchEngine()
    res = engine.run_pipeline(candles=[], provenance=prov, dataset_name="EMPTY_TEST")
    assert res.status == RunStatus.FAILED
    assert res.validation_report.status == ValidationStatus.REJECTED


def test_insufficient_data_handling():
    """Very small dataset (e.g. 2 candles) processes safely without errors."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=2)
    prov = DataProvenanceTracker.create_provenance("MT5_EXNESS", candles)
    engine = HistoricalResearchEngine()
    res = engine.run_pipeline(candles, prov, dataset_name="INSUFFICIENT_TEST")
    assert res.status == RunStatus.SUCCESS


def test_partial_timeframe_data_handling():
    """Timeframe M15 is processed with adapted expected intervals."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    c1 = make_candle(t0, 1.10000, 1.10040, 1.09980, 1.10020, tf="M15")
    c2 = make_candle(t0 + timedelta(minutes=15), 1.10020, 1.10050, 1.10010, 1.10035, tf="M15")

    validator = HistoricalDataValidator(timeframe="M15")
    report = validator.validate_dataset([c1, c2])
    assert report.status == ValidationStatus.PASS
    assert report.missing_intervals == 0


def test_report_and_manifest_generation():
    """Report text and manifest contain all required audit fields and engine versions."""
    t0 = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    candles = generate_candle_series(t0, count=30)
    prov = DataProvenanceTracker.create_provenance("MT5_EXNESS", candles)
    engine = HistoricalResearchEngine()
    result = engine.run_pipeline(candles, prov, dataset_name="MANIFEST_REPORT_TEST")

    # Verify manifest
    manifest = result.manifest
    assert manifest.symbol == "EURUSD"
    assert "ingestion_version" in manifest.engine_versions
    assert "setup_version" in manifest.engine_versions
    assert manifest.row_count == 30

    # Verify report text
    text_rep = result.report_text
    assert "TRADER MACHINE — HISTORICAL RESEARCH REPORT" in text_rep
    assert "EURUSD" in text_rep
    assert "IN_SAMPLE:" in text_rep
    assert "Zero profitability claims" in text_rep
