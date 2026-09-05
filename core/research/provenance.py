"""
Raw data provenance tracker for Historical Research Engine V1.
Tracks data lineage, source file metadata, content hashes, and timestamps.
Explicitly prevents synthetic test data from being recorded as production research datasets.
"""

from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from core.research.contract import DataProvenance
from core.research.hashing import hash_candles
from core.setups.common import get_val, ensure_utc


class DataProvenanceTracker:
    """
    Creates and audits data provenance records for historical datasets.
    """

    @staticmethod
    def create_provenance(
        source: str,
        candles: Sequence[Any],
        source_file: Optional[str] = None,
        source_format: str = "CSV",
        is_synthetic: bool = False,
    ) -> DataProvenance:
        """Constructs an immutable DataProvenance record from candle records."""
        sorted_candles = sorted(candles, key=lambda c: ensure_utc(get_val(c, "timestamp"))) if candles else []

        first_ts = ensure_utc(get_val(sorted_candles[0], "timestamp")) if sorted_candles else None
        last_ts = ensure_utc(get_val(sorted_candles[-1], "timestamp")) if sorted_candles else None
        content_hash = hash_candles(sorted_candles)

        return DataProvenance(
            source=source.strip().upper(),
            source_file=source_file,
            source_format=source_format.strip().upper(),
            imported_at=datetime.now(timezone.utc),
            content_hash=content_hash,
            row_count=len(sorted_candles),
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            is_synthetic=is_synthetic,
        )

    @staticmethod
    def validate_production_provenance(provenance: DataProvenance) -> bool:
        """
        Validates that a dataset provenance record is valid for real research.
        Fails if synthetic data was flagged or if row count is 0.
        """
        if provenance.is_synthetic:
            raise ValueError(
                "Synthetic data detected! Synthetic data may only be used for unit tests, never in research datasets."
            )
        if provenance.row_count <= 0:
            raise ValueError("Provenance row count must be greater than zero.")
        if not provenance.content_hash:
            raise ValueError("Provenance must contain a non-empty content_hash.")
        return True
