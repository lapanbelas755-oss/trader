"""Data contracts, domain models, and semantic disclaimers for Real Market Data Acquisition V1.
Strict separation of Data Acquisition from Data Research.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class DataFormat(str, Enum):
    CSV = "CSV"
    JSON = "JSON"
    JSONL = "JSONL"
    PARQUET = "PARQUET"
    IN_MEMORY = "IN_MEMORY"


class SourceType(str, Enum):
    FILE = "FILE"
    STREAM = "STREAM"
    DIRECTORY = "DIRECTORY"
    IN_MEMORY = "IN_MEMORY"


class DataQualityStatus(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    REJECTED = "REJECTED"


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class MarketDataType(str, Enum):
    OHLC = "OHLC"
    TICK = "TICK"


# Mandatory Architectural & Semantic Disclaimers
TICK_VOLUME_DISCLAIMER = (
    "FOREX SPOT VOLUME SPECIFICATION: tick_volume != real traded volume; "
    "tick_volume != buyer volume; tick_volume != seller volume; "
    "tick_volume != institutional volume. It represents source-specific observed tick activity only."
)

GLOBAL_LIQUIDITY_DISCLAIMER = (
    "NO GLOBAL LIQUIDITY CLAIM: Forex spot trading is decentralized and fragmented. "
    "This dataset captures only observed prices and tick counts from the designated provider/source. "
    "It does not represent global FX market volume, aggregate interbank liquidity, or institutional order flow."
)


class QualityCheckResult(BaseModel):
    """Result of an individual validation check."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    check_name: str
    status: CheckStatus
    affected_rows: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class DatasetQualityReport(BaseModel):
    """Comprehensive quality audit report for an acquired dataset."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataset_name: str
    status: DataQualityStatus
    checks: list[QualityCheckResult] = Field(default_factory=list)
    summary: str = ""

    def add_check(self, check: QualityCheckResult) -> None:
        self.checks.append(check)
        if check.status == CheckStatus.FAIL:
            self.status = DataQualityStatus.REJECTED
        elif check.status == CheckStatus.WARNING and self.status != DataQualityStatus.REJECTED:
            self.status = DataQualityStatus.PASS_WITH_WARNINGS


class GapRecord(BaseModel):
    """Identified missing timeframe interval without fabricated data."""
    start: datetime
    end: datetime
    duration_seconds: float
    expected_rows: int
    actual_rows: int = 0


class ValidatedCandleRecord(BaseModel):
    """Normalized, validated candle record in UTC."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: datetime  # Guaranteed UTC timezone-aware
    symbol: str
    timeframe: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")
    spread: Optional[Decimal] = None


class ValidatedTickRecord(BaseModel):
    """Normalized, validated tick record in UTC."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: datetime  # Guaranteed UTC timezone-aware
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Optional[Decimal] = None
    volume: Decimal = Decimal("0")


class DatasetProvenance(BaseModel):
    """Immutable audit record detailing source provenance and hashing."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_name: str
    source_type: str
    source_file: str
    source_format: str
    symbol: str
    timeframe: str
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    row_count: int
    content_hash: str
    imported_at: datetime
    timezone: str
    schema_version: str = "V1"
    tick_volume_semantics: str = TICK_VOLUME_DISCLAIMER
    liquidity_semantics: str = GLOBAL_LIQUIDITY_DISCLAIMER
