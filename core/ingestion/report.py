"""Ingestion Quality Report module for Trader Machine V1."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from core.ingestion.contract import IngestionStatus

@dataclass
class IngestionQualityReport:
    """Comprehensive quality audit report for an ingestion batch."""
    source_identifier: str
    symbol: str
    start_timestamp: Optional[datetime] = None
    end_timestamp: Optional[datetime] = None
    total_records: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    duplicate_records: int = 0
    missing_fields: int = 0
    timestamp_issues: list[str] = field(default_factory=list)
    price_issues: list[str] = field(default_factory=list)
    volume_issues: list[str] = field(default_factory=list)
    gap_count: int = 0
    ingestion_status: IngestionStatus = IngestionStatus.REJECTED

    def determine_status(self) -> IngestionStatus:
        """Compute final status based on validation and integrity metrics."""
        if self.total_records == 0 or self.valid_records == 0:
            self.ingestion_status = IngestionStatus.REJECTED
        elif (
            self.invalid_records > 0
            or self.duplicate_records > 0
            or len(self.timestamp_issues) > 0
            or len(self.price_issues) > 0
            or len(self.volume_issues) > 0
            or self.gap_count > 0
        ):
            self.ingestion_status = IngestionStatus.PASS_WITH_WARNINGS
        else:
            self.ingestion_status = IngestionStatus.PASS
        return self.ingestion_status

    def summary(self) -> str:
        """Produce a clean text summary of the audit."""
        start_str = self.start_timestamp.isoformat() if self.start_timestamp else "N/A"
        end_str = self.end_timestamp.isoformat() if self.end_timestamp else "N/A"
        return (
            f"=== INGESTION QUALITY REPORT ===\n"
            f"Source: {self.source_identifier}\n"
            f"Symbol: {self.symbol}\n"
            f"Period: {start_str} -> {end_str}\n"
            f"Status: {self.ingestion_status.value}\n"
            f"Records: Total={self.total_records}, Valid={self.valid_records}, "
            f"Invalid={self.invalid_records}, Duplicates={self.duplicate_records}\n"
            f"Issues: MissingFields={self.missing_fields}, Timestamps={len(self.timestamp_issues)}, "
            f"Prices={len(self.price_issues)}, Volumes={len(self.volume_issues)}, Gaps={self.gap_count}"
        )
