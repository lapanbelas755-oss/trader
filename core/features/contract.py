"""Contract definitions and Pydantic models for Market Feature Engine V1."""
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

class FeatureStatus(str, Enum):
    VALID = "VALID"
    WARMUP = "WARMUP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID = "INVALID"

class CalculatedFeatureRecord(BaseModel):
    """Pydantic model representing a calculated feature record for a single candle bar."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: str = Field(..., min_length=1, max_length=16)
    timeframe: str = Field(..., min_length=1, max_length=8)
    timestamp: datetime = Field(..., description="Candle open timestamp in UTC")

    # Geometry & ATR
    atr: Optional[Decimal] = None
    range: Decimal = Field(..., ge=Decimal("0"))
    body: Decimal = Field(..., ge=Decimal("0"))
    price_change: Decimal
    movement_efficiency: Optional[Decimal] = None

    # Effort vs Result (Law #4)
    effort: Decimal = Field(..., ge=Decimal("0"))
    result: Optional[Decimal] = None
    effort_result_ratio: Optional[Decimal] = None

    # Volatility & Baselines
    volatility: Optional[Decimal] = None
    volatility_zscore: Optional[Decimal] = None
    activity_zscore: Optional[Decimal] = None
    price_response_zscore: Optional[Decimal] = None

    # Anomaly Flags
    is_anomaly_candidate: bool = False
    is_strong_anomaly: bool = False

    # Market Speed
    movement_speed: Optional[Decimal] = None
    range_per_second: Optional[Decimal] = None
    price_change_per_second: Optional[Decimal] = None

    # Status
    feature_status: FeatureStatus = FeatureStatus.WARMUP

    @field_validator("timestamp")
    @classmethod
    def must_be_timezone_aware_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("Feature timestamp must be timezone-aware UTC")
        return v.astimezone(timezone.utc)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("Symbol cannot be empty")
        return s
