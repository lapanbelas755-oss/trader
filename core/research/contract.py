"""
Contract definitions, Enums, and Pydantic models for Historical Research & Dataset Engine V1.
Strictly observational, auditable, and immutable. No profitability or execution fields.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatasetStatus(str, Enum):
    BUILDING = "BUILDING"
    VALIDATED = "VALIDATED"
    READY = "READY"
    REJECTED = "REJECTED"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class SplitType(str, Enum):
    IN_SAMPLE = "IN_SAMPLE"
    VALIDATION = "VALIDATION"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"


class ValidationStatus(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    REJECTED = "REJECTED"


class DataProvenance(BaseModel):
    """Provenance tracking for raw historical input data."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    source: str
    source_file: Optional[str] = None
    source_format: str = "CSV"
    imported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str
    row_count: int
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    is_synthetic: bool = False

    @field_validator("imported_at", "first_timestamp", "last_timestamp")
    @classmethod
    def must_be_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class DatasetMetadata(BaseModel):
    """Deterministic metadata describing a research dataset."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = None
    dataset_name: str
    symbol: str = "EURUSD"
    source: str
    timeframe: str = "M5"
    start_time: datetime
    end_time: datetime
    row_count: int
    dataset_version: str
    content_hash: str
    status: DatasetStatus = DatasetStatus.BUILDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("start_time", "end_time", "created_at")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class DataValidationReport(BaseModel):
    """Quality and integrity audit report of historical input dataset."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: ValidationStatus
    total_candles: int
    valid_candles: int
    duplicate_count: int = 0
    missing_intervals: int = 0
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class ResearchOccurrenceRecord(BaseModel):
    """
    Deterministic setup occurrence observed in historical research data.
    Strictly observational: contains ZERO profit, loss, win, TP, or SL fields.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    occurrence_id: str
    research_run_id: Optional[int] = None
    setup_id: str
    setup_code: str
    symbol: str
    timeframe: str = "M5"
    timestamp: datetime
    direction: str
    status: str
    regime: str = "UNKNOWN"
    liquidity_type: Optional[str] = None
    structure_type: Optional[str] = None
    split_type: SplitType = SplitType.IN_SAMPLE
    evidence_snapshot: Dict[str, Any] = Field(default_factory=dict)
    config_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("timestamp", "created_at")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class ResearchManifest(BaseModel):
    """Machine-readable audit manifest for a research run / dataset."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataset_version: str
    symbol: str
    source: str
    timeframe: str
    start_time: datetime
    end_time: datetime
    row_count: int
    content_hash: str
    config_hash: str
    engine_versions: Dict[str, str]
    occurrence_counts: Dict[str, int] = Field(default_factory=dict)
    split_counts: Dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("start_time", "end_time", "created_at")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
