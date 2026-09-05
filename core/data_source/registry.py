"""Dataset Registry for persisting and querying market dataset acquisitions and audit reports.
Guarantees database idempotency and enforces uniqueness via canonical content hashes.
"""
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import get_session_factory
from database.models import MarketDataset, MarketDataQualityReport
from core.data_source.contract import DatasetProvenance, DatasetQualityReport, DataQualityStatus

logger = logging.getLogger(__name__)


class DatasetRegistry:
    """Manages database persistence and deduplication of market datasets."""

    def __init__(self, session: Optional[Session] = None):
        self._session = session

    def _get_session(self) -> Session:
        if self._session is not None:
            return self._session
        factory = get_session_factory()
        return factory()

    def find_by_content_hash(self, content_hash: str) -> Optional[MarketDataset]:
        """Find an existing registered dataset by its canonical content hash."""
        session = self._get_session()
        should_close = self._session is None
        try:
            stmt = select(MarketDataset).where(MarketDataset.content_hash == content_hash)
            return session.scalars(stmt).first()
        finally:
            if should_close:
                session.close()

    def find_by_name(self, dataset_name: str) -> Optional[MarketDataset]:
        """Find an existing registered dataset by unique name."""
        session = self._get_session()
        should_close = self._session is None
        try:
            stmt = select(MarketDataset).where(MarketDataset.dataset_name == dataset_name)
            return session.scalars(stmt).first()
        finally:
            if should_close:
                session.close()

    def register_dataset(
        self,
        dataset_name: str,
        provenance: DatasetProvenance,
        quality_report: DatasetQualityReport,
    ) -> tuple[MarketDataset, bool]:
        """Register a dataset and its quality audit reports in the database.
        
        Returns:
            (market_dataset_instance, is_new_record)
        """
        session = self._get_session()
        should_close = self._session is None
        try:
            # 1. Check for existing dataset with identical content hash
            existing_by_hash = session.scalars(
                select(MarketDataset).where(MarketDataset.content_hash == provenance.content_hash)
            ).first()

            if existing_by_hash:
                logger.info(
                    f"Dataset with identical content hash '{provenance.content_hash}' already exists: "
                    f"id={existing_by_hash.id}, name='{existing_by_hash.dataset_name}'. Skipping duplicate insert."
                )
                return existing_by_hash, False

            # 2. Check for duplicate dataset name
            existing_by_name = session.scalars(
                select(MarketDataset).where(MarketDataset.dataset_name == dataset_name)
            ).first()

            if existing_by_name:
                raise ValueError(
                    f"Dataset name '{dataset_name}' already exists with different content hash. "
                    f"Please provide a unique dataset name."
                )

            # 3. Create MarketDataset record
            dataset_record = MarketDataset(
                dataset_name=dataset_name,
                source_name=provenance.source_name,
                source_type=provenance.source_type,
                source_file=provenance.source_file,
                format=provenance.source_format,
                symbol=provenance.symbol,
                timeframe=provenance.timeframe,
                timezone=provenance.timezone,
                first_timestamp=provenance.first_timestamp,
                last_timestamp=provenance.last_timestamp,
                row_count=provenance.row_count,
                content_hash=provenance.content_hash,
                schema_version=provenance.schema_version,
                quality_status=quality_report.status.value,
            )
            session.add(dataset_record)
            session.flush()

            # 4. Create Quality Report entries
            for check in quality_report.checks:
                report_entry = MarketDataQualityReport(
                    dataset_id=dataset_record.id,
                    check_name=check.check_name,
                    status=check.status.value,
                    affected_rows=check.affected_rows,
                    details=check.details,
                )
                session.add(report_entry)

            session.commit()
            return dataset_record, True
        except Exception:
            session.rollback()
            raise
        finally:
            if should_close:
                session.close()
