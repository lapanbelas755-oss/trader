"""Data Ingestion & Normalization Layer for Trader Machine V1."""
from core.ingestion.contract import ValidatedTickRecord, RejectedRecord, IngestionStatus
from core.ingestion.adapters import DataSourceAdapter, CSVAdapter, JSONAdapter, InMemoryAdapter
from core.ingestion.normalizer import TickNormalizer
from core.ingestion.validator import TickValidator, ValidationResult
from core.ingestion.deduplicator import TickDeduplicator
from core.ingestion.integrity import IntegrityChecker, IntegrityIssue
from core.ingestion.report import IngestionQualityReport
from core.ingestion.loader import DatabaseLoader
from core.ingestion.pipeline import IngestionPipeline

__all__ = [
    "ValidatedTickRecord",
    "RejectedRecord",
    "IngestionStatus",
    "DataSourceAdapter",
    "CSVAdapter",
    "JSONAdapter",
    "InMemoryAdapter",
    "TickNormalizer",
    "TickValidator",
    "ValidationResult",
    "TickDeduplicator",
    "IntegrityChecker",
    "IntegrityIssue",
    "IngestionQualityReport",
    "DatabaseLoader",
    "IngestionPipeline",
]
