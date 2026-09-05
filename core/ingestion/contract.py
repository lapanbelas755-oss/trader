"""Data contracts and record definitions for Trader Machine V1 Data Ingestion."""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

class IngestionStatus(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    REJECTED = "REJECTED"

class ValidatedTickRecord(BaseModel):
    """Pydantic model representing a strictly validated and normalized raw tick.
    Follows OBSERVED and DERIVED contract boundaries.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: str = Field(..., min_length=1, max_length=16, description="Normalized symbol identifier")
    timestamp: datetime = Field(..., description="Timezone-aware UTC timestamp")
    bid: Decimal = Field(..., gt=Decimal("0"), description="Best bid price (> 0)")
    ask: Decimal = Field(..., gt=Decimal("0"), description="Best ask price (> 0)")
    last: Optional[Decimal] = Field(None, ge=Decimal("0"), description="Last traded price if available")
    volume: Decimal = Field(default=Decimal("0"), ge=Decimal("0"), description="Non-negative transaction/tick volume")
    tick_direction: Optional[str] = Field(None, max_length=8, description="UP, DOWN, or FLAT direction")
    source: str = Field(default="UNKNOWN_SOURCE", min_length=1, max_length=32)
    tick_id: Optional[str] = Field(None, description="Source-provided unique trade or tick ID if available")

    @field_validator("timestamp")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("Timestamp must be timezone-aware UTC")
        return v

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("Symbol cannot be empty")
        return s

    @field_validator("tick_direction")
    @classmethod
    def validate_tick_direction(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v_upper = v.strip().upper()
            if v_upper not in ("UP", "DOWN", "FLAT", "BUY", "SELL"):
                raise ValueError(f"Invalid tick direction: {v}")
            return v_upper
        return None

class RejectedRecord(BaseModel):
    """Container for records rejected during ingestion with immutable reason."""
    record_index: int
    raw_data: dict[str, Any]
    reason: str
    category: str  # 'PRICE', 'TIMESTAMP', 'VOLUME', 'SCHEMA', 'INTEGRITY'
