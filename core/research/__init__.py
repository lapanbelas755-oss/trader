"""
Historical Research & Dataset Engine V1 package.
Exposes data provenance, validation, chronological splitting, canonical hashing,
report generation, and research pipeline orchestration.
"""

from core.research.contract import (
    DatasetStatus,
    RunStatus,
    SplitType,
    ValidationStatus,
    DataProvenance,
    DatasetMetadata,
    DataValidationReport,
    ResearchOccurrenceRecord,
    ResearchManifest,
)
from core.research.config import ResearchConfig
from core.research.hashing import hash_candles, hash_occurrences, hash_canonical_json
from core.research.provenance import DataProvenanceTracker
from core.research.validator import HistoricalDataValidator
from core.research.splitter import ChronologicalSplitter
from core.research.occurrence import SetupOccurrenceRecorder
from core.research.report import ResearchReportGenerator, ENGINE_VERSIONS
from core.research.engine import HistoricalResearchEngine, ResearchRunResult

__all__ = [
    "DatasetStatus",
    "RunStatus",
    "SplitType",
    "ValidationStatus",
    "DataProvenance",
    "DatasetMetadata",
    "DataValidationReport",
    "ResearchOccurrenceRecord",
    "ResearchManifest",
    "ResearchConfig",
    "hash_candles",
    "hash_occurrences",
    "hash_canonical_json",
    "DataProvenanceTracker",
    "HistoricalDataValidator",
    "ChronologicalSplitter",
    "SetupOccurrenceRecorder",
    "ResearchReportGenerator",
    "ENGINE_VERSIONS",
    "HistoricalResearchEngine",
    "ResearchRunResult",
]
