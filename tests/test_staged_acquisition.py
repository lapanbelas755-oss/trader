"""Test suite for Historical Data Acquisition Manager V1.
Covers provider separation, dataset classifications, staged acquisition milestones,
manifest generation, file and dataset hashes, raw immutability, storage safety,
cross-validation framework, partitioning, and Git storage protection.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import tempfile
import pytest

from core.data_source.contract import (
    DataFormat,
    DataQualityStatus,
    MarketDataType,
    ValidatedCandleRecord,
)
from core.data_source.cross_val import (
    CROSS_VALIDATION_DISCLAIMER,
    CrossValidationComparator,
    CrossValidationReport,
)
from core.data_source.hashing import CanonicalHasher
from core.data_source.staged import (
    PROVIDER_SEMANTICS,
    AcquisitionManifest,
    AcquisitionStage,
    DataProvider,
    DatasetClass,
    DatasetPartitioner,
    FileHasher,
    ProviderSeparationError,
    StagedAcquisitionManager,
)
from core.data_source.storage import (
    InsufficientStorageError,
    StorageSafetyChecker,
    StorageSafetyReport,
)


def make_candle(ts: datetime, o: float, h: float, l: float, c: float, spread: float = 1.2) -> ValidatedCandleRecord:
    return ValidatedCandleRecord(
        timestamp=ts,
        symbol="EURUSD",
        timeframe="M5",
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(l)),
        close=Decimal(str(c)),
        volume=Decimal("100"),
        spread=Decimal(str(spread)),
    )


# --- 1. PROVIDER SEPARATION ---
def test_provider_separation():
    # Valid single provider passes
    assert StagedAcquisitionManager.validate_provider_separation([DataProvider.DUKASCOPY]) == DataProvider.DUKASCOPY
    assert StagedAcquisitionManager.validate_provider_separation(["TrueFX", "TRUEFX"]) == DataProvider.TRUEFX


# --- 2. DATASET CLASSIFICATION ---
def test_dataset_classification():
    classes = [DatasetClass.PRIMARY_RESEARCH, DatasetClass.CROSS_VALIDATION, DatasetClass.REFERENCE_ONLY]
    assert len(classes) == 3
    assert DatasetClass.PRIMARY_RESEARCH.value == "PRIMARY_RESEARCH"
    assert DatasetClass.CROSS_VALIDATION.value == "CROSS_VALIDATION"
    assert DatasetClass.REFERENCE_ONLY.value == "REFERENCE_ONLY"


# --- 3. STAGED ACQUISITION ---
def test_staged_acquisition():
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # 3 months (~90 days)
    stage1 = StagedAcquisitionManager.evaluate_stage(base, base + timedelta(days=90))
    assert stage1 == AcquisitionStage.STAGE_1

    # 6 months (~180 days)
    stage2 = StagedAcquisitionManager.evaluate_stage(base, base + timedelta(days=180))
    assert stage2 == AcquisitionStage.STAGE_2

    # 1 year (~365 days)
    stage3 = StagedAcquisitionManager.evaluate_stage(base, base + timedelta(days=365))
    assert stage3 == AcquisitionStage.STAGE_3

    # 3 years (~1100 days)
    stage4 = StagedAcquisitionManager.evaluate_stage(base, base + timedelta(days=1100))
    assert stage4 == AcquisitionStage.STAGE_4

    # 5+ years (~1850 days)
    stage5 = StagedAcquisitionManager.evaluate_stage(base, base + timedelta(days=1850))
    assert stage5 == AcquisitionStage.STAGE_5


# --- 4. MANIFEST GENERATION ---
def test_manifest_generation(tmp_path: Path):
    f1 = tmp_path / "eurusd_m5_chunk1.csv"
    f1.write_text("timestamp,open\n2025-01-01,1.0850\n")

    manifest = StagedAcquisitionManager.create_manifest(
        dataset_id="DUKASCOPY_EURUSD_M5_S1",
        provider=DataProvider.DUKASCOPY,
        dataset_class=DatasetClass.PRIMARY_RESEARCH,
        symbol="EURUSD",
        data_type=MarketDataType.OHLC,
        timeframe="M5",
        files=[f1],
        content_hash="canonical_sha256_placeholder",
        row_count=1000,
        start_ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_ts=datetime(2025, 3, 31, tzinfo=timezone.utc),
        timezone_str="UTC",
    )

    assert manifest.dataset_id == "DUKASCOPY_EURUSD_M5_S1"
    assert manifest.provider == DataProvider.DUKASCOPY
    assert manifest.file_count == 1
    assert "eurusd_m5_chunk1.csv" in manifest.file_hashes
    assert len(manifest.file_hashes["eurusd_m5_chunk1.csv"]) == 64
    assert manifest.content_hash == "canonical_sha256_placeholder"
    assert "Dukascopy:" in manifest.source_description


# --- 5. FILE HASH ---
def test_file_hash(tmp_path: Path):
    f = tmp_path / "test_file.csv"
    f.write_text("fixed_content_to_hash\n")
    h1 = FileHasher.hash_file(f)
    h2 = FileHasher.hash_file(f)
    assert h1 == h2
    assert len(h1) == 64

    # Modify content -> hash must change
    f.write_text("modified_content\n")
    h3 = FileHasher.hash_file(f)
    assert h3 != h1


# --- 6. DATASET HASH (CANONICAL SEPARATE FROM FILE HASH) ---
def test_dataset_hash():
    c1 = make_candle(datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc), 1.0850, 1.0855, 1.0848, 1.0852)
    c2 = make_candle(datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc), 1.0852, 1.0858, 1.0850, 1.0856)

    d_hash1 = CanonicalHasher.compute_hash([c1, c2])
    d_hash2 = CanonicalHasher.compute_hash([c2, c1])  # Order independent
    assert d_hash1 == d_hash2


# --- 7. RAW IMMUTABILITY ---
def test_raw_immutability(tmp_path: Path):
    raw_file = tmp_path / "raw_original.csv"
    original_bytes = b"timestamp,symbol,open,high,low,close,volume\n2025-01-01 00:00:00,EURUSD,1.0850,1.0855,1.0848,1.0852,100\n"
    raw_file.write_bytes(original_bytes)

    # Compute initial hash
    initial_hash = FileHasher.hash_file(raw_file)

    # Execute read via hasher or reader
    _ = FileHasher.hash_file(raw_file)

    # Verify bytes and hash are 100% identical and unchanged
    assert raw_file.read_bytes() == original_bytes
    assert FileHasher.hash_file(raw_file) == initial_hash


# --- 8. PROVENANCE CHAIN ---
def test_provenance_chain(tmp_path: Path):
    f = tmp_path / "chunk.csv"
    f.write_text("sample")

    manifest = StagedAcquisitionManager.create_manifest(
        dataset_id="DERIVED_EURUSD_M5_FROM_TICK",
        provider=DataProvider.DUKASCOPY,
        dataset_class=DatasetClass.PRIMARY_RESEARCH,
        symbol="EURUSD",
        data_type=MarketDataType.OHLC,
        timeframe="M5",
        files=[f],
        content_hash="canonical_hash_m5",
        row_count=500,
        start_ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_ts=datetime(2025, 1, 10, tzinfo=timezone.utc),
        parent_source_dataset_id="RAW_DUKASCOPY_EURUSD_TICK_2025",
    )

    assert manifest.parent_source_dataset_id == "RAW_DUKASCOPY_EURUSD_TICK_2025"


# --- 9. STORAGE SAFETY (PASS) ---
def test_storage_safety(tmp_path: Path):
    report = StorageSafetyChecker.check_storage_safety(
        target_path=tmp_path,
        incoming_bytes=1024 * 1024,  # 1 MB
    )
    assert report.sufficient is True
    assert report.available_bytes > 0
    assert "Storage Audit" in report.format_summary()


# --- 10. INSUFFICIENT STORAGE REJECTION ---
def test_insufficient_storage_rejection(tmp_path: Path):
    with pytest.raises(InsufficientStorageError, match="Insufficient disk space"):
        # Request 100 Petabytes
        StorageSafetyChecker.check_storage_safety(
            target_path=tmp_path,
            incoming_bytes=100 * 1024 * 1024 * 1024 * 1024 * 1024,
        )


# --- 11. TIMEZONE REJECTION ---
def test_timezone_rejection(tmp_path: Path):
    f = tmp_path / "file.csv"
    f.write_text("data")

    with pytest.raises(ValueError, match="Unknown or non-UTC timezone"):
        StagedAcquisitionManager.create_manifest(
            dataset_id="TEST_TZ_FAIL",
            provider=DataProvider.DUKASCOPY,
            dataset_class=DatasetClass.PRIMARY_RESEARCH,
            symbol="EURUSD",
            data_type=MarketDataType.OHLC,
            timeframe="M5",
            files=[f],
            content_hash="h",
            row_count=10,
            start_ts=None,
            end_ts=None,
            timezone_str="Asia/Jakarta",  # Staged manifests require explicit UTC
        )


# --- 12. PROVIDER MIXING REJECTION ---
def test_provider_mixing_rejection():
    mixed = [DataProvider.DUKASCOPY, DataProvider.TRUEFX]
    with pytest.raises(ProviderSeparationError, match="PROVIDER SEPARATION VIOLATION"):
        StagedAcquisitionManager.validate_provider_separation(mixed)


# --- 13. CROSS-VALIDATION METADATA ---
def test_cross_validation_metadata():
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    feed_duk = [
        make_candle(t0 + timedelta(minutes=5 * i), 1.0850 + i * 0.0001, 1.0855 + i * 0.0001, 1.0848 + i * 0.0001, 1.0852 + i * 0.0001, spread=1.2)
        for i in range(20)
    ]
    feed_tfx = [
        make_candle(t0 + timedelta(minutes=5 * i), 1.08505 + i * 0.0001, 1.08552 + i * 0.0001, 1.08479 + i * 0.0001, 1.08522 + i * 0.0001, spread=1.5)
        for i in range(20)
    ]

    report = CrossValidationComparator.compare_feeds(
        primary_provider=DataProvider.DUKASCOPY,
        primary_records=feed_duk,
        comparison_provider=DataProvider.TRUEFX,
        comparison_records=feed_tfx,
    )

    assert report.primary_feed.provider == DataProvider.DUKASCOPY
    assert report.comparison_feed.provider == DataProvider.TRUEFX
    assert report.coverage_overlap_ratio == 1.0
    assert report.spread_ratio > 0.0
    assert "CROSS-VALIDATION NOTICE" in report.disclaimer


# --- 14. PARTITION PATH ---
def test_partition_path():
    path = DatasetPartitioner.build_partition_path(
        base_dir="data",
        provider=DataProvider.DUKASCOPY,
        symbol="EURUSD",
        data_type=MarketDataType.OHLC,
        year=2025,
        month=1,
    )
    assert str(path) == "data/dukascopy/EURUSD/ohlc/2025/01"

    path_tick_day = DatasetPartitioner.build_partition_path(
        base_dir="data",
        provider=DataProvider.TRUEFX,
        symbol="EURUSD",
        data_type="tick",
        year=2025,
        month=3,
        day=15,
    )
    assert str(path_tick_day) == "data/truefx/EURUSD/tick/2025/03/15"


# --- 15. NO GIT DATA FILES ---
def test_no_git_data_files():
    # Verify .gitignore contains data/ and that git status does not track data/
    gitignore_path = Path(__file__).resolve().parent.parent / ".gitignore"
    content = gitignore_path.read_text(encoding="utf-8")
    assert "data/" in content

    # Run git status to ensure no data files are tracked
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(gitignore_path.parent),
        capture_output=True,
        text=True,
    )
    # No files in data/ should be untracked or staged
    for line in res.stdout.splitlines():
        assert not line.strip().endswith(".parquet")
        assert "data/" not in line or line.strip().startswith("M .gitignore")
