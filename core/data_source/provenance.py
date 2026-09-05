"""Provenance tracking and metadata management for acquired market datasets.
Ensures source traceability, immutable audit trails, and strict disclaimers against
unsubstantiated claims of global FX liquidity or volume.
"""
from datetime import datetime, timezone
from typing import Optional, Sequence, Union
from core.data_source.contract import (
    GLOBAL_LIQUIDITY_DISCLAIMER,
    TICK_VOLUME_DISCLAIMER,
    DatasetProvenance,
    ValidatedCandleRecord,
    ValidatedTickRecord,
)
from core.data_source.hashing import CanonicalHasher


class ProvenanceManager:
    """Constructs immutable provenance records for acquired market data."""

    @staticmethod
    def create_provenance(
        source_name: str,
        source_type: str,
        source_file: str,
        source_format: str,
        symbol: str,
        timeframe: str,
        records: Sequence[Union[ValidatedCandleRecord, ValidatedTickRecord]],
        declared_timezone: str,
        content_hash: Optional[str] = None,
        schema_version: str = "V1",
    ) -> DatasetProvenance:
        """Create and certify a DatasetProvenance audit record."""
        row_count = len(records)
        first_ts = records[0].timestamp if records else None
        last_ts = records[-1].timestamp if records else None

        if content_hash is None:
            content_hash = CanonicalHasher.compute_hash(records)

        return DatasetProvenance(
            source_name=source_name,
            source_type=source_type,
            source_file=source_file,
            source_format=source_format,
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            row_count=row_count,
            content_hash=content_hash,
            imported_at=datetime.now(timezone.utc),
            timezone=declared_timezone,
            schema_version=schema_version,
            tick_volume_semantics=TICK_VOLUME_DISCLAIMER,
            liquidity_semantics=GLOBAL_LIQUIDITY_DISCLAIMER,
        )
