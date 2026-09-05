"""Unified Data Ingestion Pipeline for Trader Machine V1."""
from typing import Any, Sequence
from core.ingestion.adapters import DataSourceAdapter, InMemoryAdapter
from core.ingestion.contract import IngestionStatus, RejectedRecord, ValidatedTickRecord
from core.ingestion.deduplicator import TickDeduplicator
from core.ingestion.integrity import IntegrityChecker
from core.ingestion.loader import DatabaseLoader
from core.ingestion.normalizer import TickNormalizer
from core.ingestion.report import IngestionQualityReport
from core.ingestion.validator import TickValidator

class IngestionPipeline:
    """Orchestrates extraction, normalization, validation, deduplication, integrity analysis, and database loading."""

    def __init__(
        self,
        normalizer: TickNormalizer | None = None,
        validator: TickValidator | None = None,
        deduplicator: TickDeduplicator | None = None,
        integrity_checker: IntegrityChecker | None = None,
        loader: DatabaseLoader | None = None,
    ):
        self.normalizer = normalizer or TickNormalizer()
        self.validator = validator or TickValidator()
        self.deduplicator = deduplicator or TickDeduplicator()
        self.integrity_checker = integrity_checker or IntegrityChecker()
        self.loader = loader or DatabaseLoader()

    def run(
        self,
        adapter: DataSourceAdapter,
        source: Any,
        source_identifier: str = "STREAM",
        dry_run: bool = False,
    ) -> tuple[IngestionQualityReport, int, list[RejectedRecord]]:
        """
        Execute full pipeline on raw data source.
        Returns:
            (quality_report, inserted_count, rejected_records)
        """
        raw_records = list(adapter.read_records(source))
        total_records = len(raw_records)

        report = IngestionQualityReport(
            source_identifier=source_identifier,
            symbol=self.normalizer.default_symbol,
            total_records=total_records,
        )

        if total_records == 0:
            report.determine_status()
            return report, 0, []

        normalized_records: list[dict[str, Any]] = []
        rejected_records: list[RejectedRecord] = []

        # 1. Normalization & Schema Parse
        for idx, raw in enumerate(raw_records):
            try:
                norm = self.normalizer.normalize_record(raw)
                normalized_records.append(norm)
            except ValueError as e:
                err_msg = str(e)
                cat = "TIMESTAMP" if "timestamp" in err_msg.lower() else (
                    "PRICE" if "bid" in err_msg.lower() or "ask" in err_msg.lower() else "SCHEMA"
                )
                rejected = RejectedRecord(
                    record_index=idx,
                    raw_data=raw,
                    reason=err_msg,
                    category=cat,
                )
                rejected_records.append(rejected)
                if "null or empty" in err_msg.lower():
                    report.missing_fields += 1

        # 2. Strict Validation
        val_result = self.validator.validate_batch(normalized_records)
        rejected_records.extend(val_result.rejected_records)

        # Classify rejection issues in report
        for r in rejected_records:
            if r.category == "PRICE":
                report.price_issues.append(f"Row {r.record_index}: {r.reason}")
            elif r.category == "TIMESTAMP":
                report.timestamp_issues.append(f"Row {r.record_index}: {r.reason}")
            elif r.category == "VOLUME":
                report.volume_issues.append(f"Row {r.record_index}: {r.reason}")

        report.invalid_records = len(rejected_records)

        # 3. Deduplication
        unique_records, duplicate_count = self.deduplicator.deduplicate(val_result.valid_records)
        report.duplicate_records = duplicate_count
        report.valid_records = len(unique_records)

        if unique_records:
            report.symbol = unique_records[0].symbol
            report.start_timestamp = unique_records[0].timestamp
            report.end_timestamp = unique_records[-1].timestamp

            # 4. Integrity Checks
            integrity_issues = self.integrity_checker.check(unique_records)
            for issue in integrity_issues:
                if issue.issue_type == "PRICE":
                    report.price_issues.append(str(issue))
                elif issue.issue_type == "TIMESTAMP":
                    report.timestamp_issues.append(str(issue))
                elif issue.issue_type == "VOLUME":
                    report.volume_issues.append(str(issue))
                elif issue.issue_type == "GAP":
                    report.gap_count += 1

        # Determine Report Status
        report.determine_status()

        # 5. Database Load (if not dry run and valid records exist and status != REJECTED)
        inserted_count = 0
        if not dry_run and report.ingestion_status != IngestionStatus.REJECTED and unique_records:
            inserted_count = self.loader.load_ticks(unique_records)

        return report, inserted_count, rejected_records
