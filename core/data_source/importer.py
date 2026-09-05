"""Operational Import Workflow for Real Market Datasets.
Orchestrates detection, mapping, validation, canonical hashing, provenance manifest,
and atomic database transactions with chunked streaming and rollback safety.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.data_source.contract import (
    CheckStatus,
    DataFormat,
    DataQualityStatus,
    DatasetProvenance,
    DatasetQualityReport,
    GapRecord,
    MarketDataType,
    SourceType,
    ValidatedCandleRecord,
    ValidatedTickRecord,
)
from core.data_source.engine import MarketDataAcquisitionEngine
from core.data_source.hashing import CanonicalHasher
from core.data_source.mapping import (
    DUKASCOPY_CSV_MAPPING,
    ETC_UTC_OHLC_MAPPING,
    GENERIC_OHLC_MAPPING,
    GENERIC_TICK_MAPPING,
    MT5_EXPORT_OHLC_MAPPING,
    SourceColumnMapping,
)
from core.data_source.provenance import ProvenanceManager
from core.data_source.registry import DatasetRegistry
from core.data_source.validator import MarketDataValidator
from database.connection import get_session_factory
from database.models import MarketCandle, MarketDataQualityReport, MarketDataset

logger = logging.getLogger(__name__)


MAPPING_PROFILES: dict[str, SourceColumnMapping] = {
    "generic": GENERIC_OHLC_MAPPING,
    "mt5": MT5_EXPORT_OHLC_MAPPING,
    "dukascopy": DUKASCOPY_CSV_MAPPING,
    "generic_tick": GENERIC_TICK_MAPPING,
    "etc_utc": ETC_UTC_OHLC_MAPPING,
}


def detect_file_format(file_path: Union[str, Path]) -> DataFormat:
    """Detect DataFormat from file extension."""
    suffix = Path(file_path).suffix.lower()
    if suffix in (".csv", ".txt"):
        return DataFormat.CSV
    elif suffix == ".json":
        return DataFormat.JSON
    elif suffix in (".jsonl", ".ndjson"):
        return DataFormat.JSONL
    elif suffix in (".parquet", ".pq"):
        return DataFormat.PARQUET
    else:
        raise ValueError(f"Unable to auto-detect data format for file '{file_path}'. Please specify --format explicitly.")


class MarketDataImporter:
    """Workflow coordinator for ingesting real market historical datasets."""

    def __init__(self, session: Optional[Session] = None):
        self._session = session

    def _get_session(self) -> Session:
        if self._session is not None:
            return self._session
        factory = get_session_factory()
        return factory()

    def generate_manifest(
        self,
        dataset_name: str,
        provenance: DatasetProvenance,
        quality_report: DatasetQualityReport,
    ) -> dict[str, Any]:
        """Generate a machine-readable provenance and quality audit manifest."""
        return {
            "dataset_name": dataset_name,
            "source_name": provenance.source_name,
            "source_type": provenance.source_type,
            "source_file": provenance.source_file,
            "symbol": provenance.symbol,
            "timeframe": provenance.timeframe,
            "timezone": provenance.timezone,
            "first_timestamp": provenance.first_timestamp.isoformat() if provenance.first_timestamp else None,
            "last_timestamp": provenance.last_timestamp.isoformat() if provenance.last_timestamp else None,
            "row_count": provenance.row_count,
            "content_hash": provenance.content_hash,
            "quality_status": quality_report.status.value,
            "schema_version": provenance.schema_version,
            "warnings_count": sum(1 for c in quality_report.checks if c.status == CheckStatus.WARNING),
            "errors_count": sum(1 for c in quality_report.checks if c.status == CheckStatus.FAIL),
            "disclaimers": {
                "tick_volume": provenance.tick_volume_semantics,
                "liquidity": provenance.liquidity_semantics,
            }
        }

    def import_dataset(
        self,
        source_file: Union[str, Path],
        symbol: str = "EURUSD",
        timeframe: str = "M5",
        timezone_str: str = "UTC",
        source_name: str = "EXTERNAL_HISTORICAL",
        dataset_name: Optional[str] = None,
        mapping_profile: str = "generic",
        data_format: Optional[DataFormat] = None,
        dry_run: bool = False,
        chunk_size: int = 5000,
        output_manifest_path: Optional[Union[str, Path]] = None,
    ) -> dict[str, Any]:
        """Execute the end-to-end import workflow with atomic transaction and dry-run support."""
        path = Path(source_file)
        if not path.exists():
            raise FileNotFoundError(f"Source file not found: {path}")

        # 1. Detect format if not provided
        format_resolved = data_format or detect_file_format(path)

        # 2. Resolve mapping
        if mapping_profile not in MAPPING_PROFILES:
            raise ValueError(f"Unknown mapping profile '{mapping_profile}'. Available: {list(MAPPING_PROFILES.keys())}")
        mapping = MAPPING_PROFILES[mapping_profile]

        # 3. Stream & parse records
        raw_records = list(MarketDataAcquisitionEngine.read_records_from_source(path, format_resolved))

        # 4. Generate default dataset name if not provided
        if not dataset_name:
            dataset_name = f"{symbol.upper()}_{timeframe.upper()}_{source_name.upper()}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # 5. Validate & Normalize
        validator = MarketDataValidator(
            expected_symbol=symbol,
            expected_timeframe=timeframe,
            declared_timezone=timezone_str,
        )

        if mapping.data_type == MarketDataType.OHLC:
            quality_report, validated_records, gaps = validator.validate_and_normalize_ohlc(
                raw_records=raw_records,
                mapping=mapping,
                dataset_name=dataset_name,
            )
        elif mapping.data_type == MarketDataType.TICK:
            quality_report, validated_records = validator.validate_and_normalize_ticks(
                raw_records=raw_records,
                mapping=mapping,
                dataset_name=dataset_name,
            )
            gaps = []
        else:
            raise ValueError(f"Unsupported data type: {mapping.data_type}")

        # 6. Canonical Hash & Provenance
        content_hash = CanonicalHasher.compute_hash(validated_records)
        provenance = ProvenanceManager.create_provenance(
            source_name=source_name,
            source_type=SourceType.FILE.value,
            source_file=str(path),
            source_format=format_resolved.value,
            symbol=symbol,
            timeframe=timeframe,
            records=validated_records,
            declared_timezone=timezone_str,
            content_hash=content_hash,
        )

        # 7. Generate Manifest
        manifest = self.generate_manifest(dataset_name, provenance, quality_report)
        if output_manifest_path:
            with open(output_manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

        result_summary = {
            "dataset_name": dataset_name,
            "source_name": source_name,
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "timezone": timezone_str,
            "first_timestamp": provenance.first_timestamp.isoformat() if provenance.first_timestamp else None,
            "last_timestamp": provenance.last_timestamp.isoformat() if provenance.last_timestamp else None,
            "row_count": provenance.row_count,
            "content_hash": provenance.content_hash,
            "quality_status": quality_report.status.value,
            "warnings_count": manifest["warnings_count"],
            "errors_count": manifest["errors_count"],
            "dry_run": dry_run,
            "status": "VALIDATED" if dry_run else "PENDING_IMPORT",
            "dataset_id": None,
            "gaps": [g.model_dump() for g in gaps],
        }

        # 8. Check Quality Status
        if quality_report.status == DataQualityStatus.REJECTED:
            result_summary["status"] = "REJECTED"
            return result_summary

        # 9. If Dry Run, stop here without database interaction
        if dry_run:
            result_summary["status"] = "DRY_RUN_PASS"
            return result_summary

        # 10. Database Persistence with Atomic Transaction
        session = self._get_session()
        should_close = self._session is None
        try:
            # Check duplicate content hash
            registry = DatasetRegistry(session=session)
            existing_ds = registry.find_by_content_hash(provenance.content_hash)
            if existing_ds:
                result_summary["status"] = "EXISTING_DATASET"
                result_summary["dataset_id"] = existing_ds.id
                result_summary["dataset_name"] = existing_ds.dataset_name
                return result_summary

            # Register Dataset & Quality Reports
            dataset_model, is_new = registry.register_dataset(
                dataset_name=dataset_name,
                provenance=provenance,
                quality_report=quality_report,
                auto_commit=False,
            )
            result_summary["dataset_id"] = dataset_model.id

            # Insert MarketCandles in chunks if OHLC data
            if mapping.data_type == MarketDataType.OHLC and validated_records:
                for i in range(0, len(validated_records), chunk_size):
                    chunk = validated_records[i : i + chunk_size]
                    stmt = insert(MarketCandle).values([
                        {
                            "symbol": c.symbol,
                            "timeframe": c.timeframe,
                            "timestamp": c.timestamp,
                            "open": c.open,
                            "high": c.high,
                            "low": c.low,
                            "close": c.close,
                            "tick_volume": int(c.volume),
                            "real_volume": 0,
                            "spread": c.spread or Decimal("0.0"),
                        }
                        for c in chunk
                    ])
                    # Avoid failure on pre-existing overlapping candles
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["symbol", "timeframe", "timestamp"]
                    )
                    session.execute(stmt)

            session.commit()
            result_summary["status"] = "IMPORTED"
            return result_summary
        except Exception as e:
            session.rollback()
            logger.error(f"Import failed with error, transaction rolled back cleanly: {e}")
            raise
        finally:
            if should_close:
                session.close()
