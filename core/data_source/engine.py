"""Real Market Data Acquisition & Dataset Validation Engine V1.
Coordinates adapter ingestion, column mapping, quality validation, canonical hashing,
provenance creation, and database registry persistence.
"""
import csv
import json
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence, Union

from sqlalchemy.orm import Session

from core.data_source.contract import (
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
from core.data_source.hashing import CanonicalHasher
from core.data_source.mapping import GENERIC_OHLC_MAPPING, SourceColumnMapping
from core.data_source.provenance import ProvenanceManager
from core.data_source.registry import DatasetRegistry
from core.data_source.validator import MarketDataValidator
from database.models import MarketDataset


class MarketDataAcquisitionEngine:
    """End-to-end engine for real market dataset acquisition and validation."""

    def __init__(self, registry: Optional[DatasetRegistry] = None, session: Optional[Session] = None):
        self.registry = registry or DatasetRegistry(session=session)

    @staticmethod
    def read_records_from_source(
        source: Union[str, Path, Sequence[dict[str, Any]]],
        data_format: DataFormat,
        chunk_size: Optional[int] = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream or iterate raw records from various file formats without loading full files into memory."""
        if data_format == DataFormat.IN_MEMORY:
            if isinstance(source, (list, tuple)):
                for item in source:
                    yield dict(item)
            return

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Market data source file not found: {path}")

        if data_format == DataFormat.CSV:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    yield {k.strip(): v.strip() if isinstance(v, str) else v for k, v in row.items() if k is not None}

        elif data_format == DataFormat.JSON:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return
                data = json.loads(content)
                if isinstance(data, list):
                    for row in data:
                        if isinstance(row, dict):
                            yield row
                elif isinstance(data, dict):
                    yield data

        elif data_format == DataFormat.JSONL:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line_clean = line.strip()
                    if line_clean:
                        row = json.loads(line_clean)
                        if isinstance(row, dict):
                            yield row

        elif data_format == DataFormat.PARQUET:
            import pyarrow.parquet as pq
            parquet_file = pq.ParquetFile(path)
            for batch in parquet_file.iter_batches(batch_size=chunk_size or 50000):
                pydict = batch.to_pydict()
                keys = list(pydict.keys())
                num_rows = len(pydict[keys[0]]) if keys else 0
                for i in range(num_rows):
                    yield {k: pydict[k][i] for k in keys}
        else:
            raise ValueError(f"Unsupported data format: {data_format}")

    def acquire_and_validate(
        self,
        dataset_name: str,
        source: Union[str, Path, Sequence[dict[str, Any]]],
        data_format: DataFormat,
        source_name: str,
        symbol: str = "EURUSD",
        timeframe: str = "M5",
        timezone: str = "UTC",
        mapping: Optional[SourceColumnMapping] = None,
        source_type: SourceType = SourceType.FILE,
        persist_db: bool = True,
    ) -> tuple[DatasetProvenance, DatasetQualityReport, list[Union[ValidatedCandleRecord, ValidatedTickRecord]], list[GapRecord], Optional[MarketDataset]]:
        """Acquire, validate, canonicalize, hash, and register an external dataset."""
        mapping = mapping or GENERIC_OHLC_MAPPING

        # Read records
        raw_records = list(self.read_records_from_source(source, data_format=data_format))
        source_file_str = str(source) if not isinstance(source, (list, tuple)) else "IN_MEMORY"

        # Initialize validator
        validator = MarketDataValidator(
            expected_symbol=symbol,
            expected_timeframe=timeframe,
            declared_timezone=timezone,
        )

        # Validate by data type
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
            raise ValueError(f"Unsupported market data type: {mapping.data_type}")

        # Compute canonical hash
        content_hash = CanonicalHasher.compute_hash(validated_records)

        # Create provenance record
        provenance = ProvenanceManager.create_provenance(
            source_name=source_name,
            source_type=source_type.value,
            source_file=source_file_str,
            source_format=data_format.value,
            symbol=symbol,
            timeframe=timeframe,
            records=validated_records,
            declared_timezone=timezone,
            content_hash=content_hash,
        )

        # Register in database if requested
        market_dataset_model: Optional[MarketDataset] = None
        if persist_db and self.registry is not None:
            market_dataset_model, _ = self.registry.register_dataset(
                dataset_name=dataset_name,
                provenance=provenance,
                quality_report=quality_report,
            )

        return provenance, quality_report, validated_records, gaps, market_dataset_model
