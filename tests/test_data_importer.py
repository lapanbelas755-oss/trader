"""Tests for Operational Real Market Data Import Workflow & CLI V1.
Covers dry run, full atomic import, rejected datasets, duplicate hash detection,
manifest generation, warnings, UTC normalization, no fabrication, chunking, and transaction rollback.
"""
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
from pathlib import Path
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.data_source.cli import main
from core.data_source.contract import DataFormat, DataQualityStatus
from core.data_source.importer import MarketDataImporter
from database.connection import get_engine, get_session_factory
from database.models import MarketCandle, MarketDataset


@pytest.fixture(autouse=True)
def cleanup_test_datasets():
    """Ensure test tables are cleaned up before and after each test."""
    session_factory = get_session_factory()
    with session_factory() as session:
        session.execute(text("DELETE FROM market_datasets WHERE dataset_name LIKE 'TEST_IMP_%';"))
        session.execute(text("DELETE FROM market_candles WHERE symbol = 'TESTEUR';"))
        session.commit()
    yield
    with session_factory() as session:
        session.execute(text("DELETE FROM market_datasets WHERE dataset_name LIKE 'TEST_IMP_%';"))
        session.execute(text("DELETE FROM market_candles WHERE symbol = 'TESTEUR';"))
        session.commit()


# --- 1. CLI DRY RUN ---
def test_cli_dry_run(tmp_path: Path, capsys):
    csv_file = tmp_path / "dry_run.csv"
    csv_file.write_text(
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 00:00:00,TESTEUR,1.08500,1.08550,1.08480,1.08520,100,1.5\n"
        "2026-02-01 00:05:00,TESTEUR,1.08520,1.08580,1.08510,1.08560,120,1.4\n"
    )

    exit_code = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--dataset-name", "TEST_IMP_DRY_RUN",
        "--dry-run",
    ])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Dataset: TEST_IMP_DRY_RUN" in captured
    assert "Mode: DRY_RUN" in captured
    assert "Quality: PASS" in captured

    # Verify no records in database
    session_factory = get_session_factory()
    with session_factory() as session:
        ds = session.execute(text("SELECT id FROM market_datasets WHERE dataset_name = 'TEST_IMP_DRY_RUN';")).scalar()
        assert ds is None
        candles_count = session.execute(text("SELECT count(*) FROM market_candles WHERE symbol = 'TESTEUR';")).scalar()
        assert candles_count == 0


# --- 2. CLI SUCCESSFUL IMPORT ---
def test_cli_successful_import(tmp_path: Path, capsys):
    csv_file = tmp_path / "valid_import.csv"
    csv_file.write_text(
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 00:00:00,TESTEUR,1.08500,1.08550,1.08480,1.08520,100,1.5\n"
        "2026-02-01 00:05:00,TESTEUR,1.08520,1.08580,1.08510,1.08560,120,1.4\n"
    )

    exit_code = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--dataset-name", "TEST_IMP_SUCCESS",
    ])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Status: IMPORTED" in captured

    # Verify database insertion
    session_factory = get_session_factory()
    with session_factory() as session:
        ds = session.execute(text("SELECT id, quality_status FROM market_datasets WHERE dataset_name = 'TEST_IMP_SUCCESS';")).first()
        assert ds is not None
        assert ds[1] == "PASS"

        candles = session.execute(text("SELECT count(*), min(close), max(close) FROM market_candles WHERE symbol = 'TESTEUR';")).first()
        assert candles[0] == 2
        assert Decimal(str(candles[1])) == Decimal("1.085200")
        assert Decimal(str(candles[2])) == Decimal("1.085600")


# --- 3. CLI REJECTED DATASET ---
def test_cli_rejected_dataset(tmp_path: Path, capsys):
    csv_file = tmp_path / "invalid_ohlc.csv"
    csv_file.write_text(
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 00:00:00,TESTEUR,1.08500,1.08400,1.08300,1.08450,100,1.5\n"  # Invalid High < Open
    )

    exit_code = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--dataset-name", "TEST_IMP_REJECTED",
    ])
    assert exit_code == 1
    captured = capsys.readouterr().out
    assert "Quality: REJECTED" in captured
    assert "Errors: 1" in captured

    # Verify no records in database
    session_factory = get_session_factory()
    with session_factory() as session:
        candles_count = session.execute(text("SELECT count(*) FROM market_candles WHERE symbol = 'TESTEUR';")).scalar()
        assert candles_count == 0


# --- 4. DUPLICATE HASH DETECTION ---
def test_duplicate_hash_detection(tmp_path: Path, capsys):
    csv_file = tmp_path / "dup_hash.csv"
    csv_file.write_text(
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 01:00:00,TESTEUR,1.08500,1.08550,1.08480,1.08520,100,1.5\n"
    )

    # First import
    exit_code_1 = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--dataset-name", "TEST_IMP_DUP_1",
    ])
    assert exit_code_1 == 0

    # Second import with identical content
    exit_code_2 = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--dataset-name", "TEST_IMP_DUP_2",
    ])
    assert exit_code_2 == 0
    captured = capsys.readouterr().out
    assert "Status: EXISTING_DATASET" in captured


# --- 5. MANIFEST GENERATION ---
def test_manifest_generation(tmp_path: Path):
    csv_file = tmp_path / "manifest_test.csv"
    manifest_file = tmp_path / "manifest.json"
    csv_file.write_text(
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 02:00:00,TESTEUR,1.08500,1.08550,1.08480,1.08520,100,1.5\n"
    )

    exit_code = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--dataset-name", "TEST_IMP_MANIFEST",
        "--output-manifest", str(manifest_file),
        "--dry-run",
    ])
    assert exit_code == 0
    assert manifest_file.exists()

    with open(manifest_file, "r") as f:
        data = json.load(f)

    assert data["dataset_name"] == "TEST_IMP_MANIFEST"
    assert data["symbol"] == "TESTEUR"
    assert data["row_count"] == 1
    assert "content_hash" in data
    assert "tick_volume" in data["disclaimers"]
    assert "liquidity" in data["disclaimers"]


# --- 6. PASS WITH WARNINGS ---
def test_pass_with_warnings(tmp_path: Path, capsys):
    csv_file = tmp_path / "warnings.csv"
    csv_file.write_text(
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 03:00:00,TESTEUR,1.08500,1.08550,1.08480,1.08520,100,1.5\n"
        "2026-02-01 03:20:00,TESTEUR,1.08520,1.08580,1.08510,1.08560,120,1.4\n"  # 20 min gap on M5
    )

    exit_code = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--dataset-name", "TEST_IMP_WARNINGS",
    ])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Quality: PASS_WITH_WARNINGS" in captured
    assert "Warnings: 1" in captured
    assert "Status: IMPORTED" in captured


# --- 7. UTC NORMALIZATION ---
def test_utc_normalization(tmp_path: Path):
    csv_file = tmp_path / "tz_jakarta.csv"
    csv_file.write_text(
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 07:00:00,TESTEUR,1.08500,1.08550,1.08480,1.08520,100,1.5\n"
    )

    exit_code = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--timezone", "Asia/Jakarta",
        "--dataset-name", "TEST_IMP_TZ",
    ])
    assert exit_code == 0

    session_factory = get_session_factory()
    with session_factory() as session:
        candle = session.execute(text("SELECT timestamp FROM market_candles WHERE symbol = 'TESTEUR';")).scalar()
        assert candle.hour == 0  # 07:00 in Jakarta is 00:00 UTC


# --- 8. NO FABRICATION ---
def test_no_fabrication(tmp_path: Path):
    csv_file = tmp_path / "no_fab.csv"
    csv_file.write_text(
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 04:00:00,TESTEUR,1.08500,1.08550,1.08480,1.08520,100,1.5\n"
        "2026-02-01 04:30:00,TESTEUR,1.08520,1.08580,1.08510,1.08560,120,1.4\n"  # 30 min gap (missing 5 M5 bars)
    )

    exit_code = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--dataset-name", "TEST_IMP_NO_FAB",
    ])
    assert exit_code == 0

    session_factory = get_session_factory()
    with session_factory() as session:
        # Exactly 2 candles must exist! Zero fabricated candles
        count = session.execute(text("SELECT count(*) FROM market_candles WHERE symbol = 'TESTEUR';")).scalar()
        assert count == 2


# --- 9. LARGE FILE CHUNKING ---
def test_large_file_chunking(tmp_path: Path):
    csv_file = tmp_path / "chunking.csv"
    with open(csv_file, "w") as f:
        f.write("timestamp,symbol,open,high,low,close,volume,spread\n")
        for i in range(120):
            hour = i // 12
            minute = (i % 12) * 5
            f.write(f"2026-02-02 {hour:02d}:{minute:02d}:00,TESTEUR,1.08500,1.08550,1.08480,1.08520,100,1.5\n")

    exit_code = main([
        "import",
        "--file", str(csv_file),
        "--symbol", "TESTEUR",
        "--timeframe", "M5",
        "--dataset-name", "TEST_IMP_CHUNKING",
        "--chunk-size", "25",  # Forces multiple database chunks
    ])
    assert exit_code == 0

    session_factory = get_session_factory()
    with session_factory() as session:
        count = session.execute(text("SELECT count(*) FROM market_candles WHERE symbol = 'TESTEUR';")).scalar()
        assert count == 120


# --- 10. DATABASE TRANSACTION ROLLBACK ON FAILED IMPORT ---
def test_database_rollback_on_failed_import(tmp_path: Path, monkeypatch):
    csv_file = tmp_path / "rollback.csv"
    csv_file.write_text(
        "timestamp,symbol,open,high,low,close,volume,spread\n"
        "2026-02-01 05:00:00,TESTEUR,1.08500,1.08550,1.08480,1.08520,100,1.5\n"
    )

    importer = MarketDataImporter()

    # Monkeypatch session.execute to fail during candle insertion
    orig_execute = Session.execute
    def fail_execute(self, *args, **kwargs):
        stmt = str(args[0]) if args else ""
        if "market_candles" in stmt.lower():
            raise RuntimeError("SIMULATED_DB_ERROR_DURING_INSERTION")
        return orig_execute(self, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", fail_execute)

    with pytest.raises(RuntimeError, match="SIMULATED_DB_ERROR_DURING_INSERTION"):
        importer.import_dataset(
            source_file=csv_file,
            symbol="TESTEUR",
            timeframe="M5",
            dataset_name="TEST_IMP_ROLLBACK",
            dry_run=False,
        )

    # Undo monkeypatch so verification queries can run
    monkeypatch.undo()

    # Verify complete rollback: neither market_datasets nor market_candles contains the dataset
    session_factory = get_session_factory()
    with session_factory() as session:
        ds = session.execute(text("SELECT id FROM market_datasets WHERE dataset_name = 'TEST_IMP_ROLLBACK';")).scalar()
        assert ds is None
        candles = session.execute(text("SELECT count(*) FROM market_candles WHERE symbol = 'TESTEUR';")).scalar()
        assert candles == 0
