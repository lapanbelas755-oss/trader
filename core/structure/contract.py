"""Contract definitions and Pydantic models for Market Structure Engine V1."""
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class SwingType(str, Enum):
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"

class StructureClassification(str, Enum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"
    EQH = "EQH"
    EQL = "EQL"

class BreakType(str, Enum):
    BOS = "BOS"
    CHOCH = "CHOCH"
    BOS_BULLISH = "BOS_BULLISH"
    BOS_BEARISH = "BOS_BEARISH"
    CHOCH_UP = "CHOCH_UP"
    CHOCH_DOWN = "CHOCH_DOWN"

class StructureDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    MIXED = "MIXED"
    TRANSITION = "TRANSITION"
    UNDEFINED = "UNDEFINED"

class MTFAlignment(str, Enum):
    ALIGNED_BULLISH = "ALIGNED_BULLISH"
    ALIGNED_BEARISH = "ALIGNED_BEARISH"
    MIXED = "MIXED"
    TRANSITION = "TRANSITION"
    UNDEFINED = "UNDEFINED"

class ConfirmedSwing(BaseModel):
    """Represents a confirmed fractal swing point with strict confirmation delay."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, populate_by_name=True)

    swing_id: str
    symbol: str
    timeframe: str
    swing_type: SwingType
    price: Decimal
    timestamp: datetime = Field(default=None, description="Candle timestamp where fractal peak occurred")
    confirmed_at: datetime = Field(..., description="Candle timestamp when swing became confirmed (t + right_bars)")
    classification: Optional[StructureClassification] = None
    reference_swing_id: Optional[str] = None
    swing_timestamp: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def reconcile_timestamps(cls, values: Any) -> Any:
        if isinstance(values, dict):
            ts = values.get("timestamp") or values.get("swing_timestamp")
            if ts is None:
                raise ValueError("Either 'timestamp' or 'swing_timestamp' must be provided")
            values["timestamp"] = ts
            values["swing_timestamp"] = ts
        return values

    @field_validator("timestamp", "confirmed_at", "swing_timestamp")
    @classmethod
    def must_be_timezone_aware_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

class StructureEvent(BaseModel):
    """Represents a discrete structural event (Swing classification, BOS, or CHoCH)."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: str
    timeframe: str
    structure_type: str  # SWING_HIGH, SWING_LOW, HH, HL, LH, LL, BOS_BULLISH, etc.
    price: Decimal
    timestamp: datetime
    confirmed_at: datetime
    swing_id: Optional[str] = None
    reference_swing_id: Optional[str] = None
    direction: StructureDirection = StructureDirection.UNDEFINED
    displacement: Optional[Decimal] = None
    strength: Optional[Decimal] = None

    @property
    def break_type(self) -> Optional[BreakType]:
        if "BOS" in self.structure_type:
            return BreakType.BOS
        if "CHOCH" in self.structure_type:
            return BreakType.CHOCH
        return None

    @property
    def break_price(self) -> Decimal:
        return self.price

    @field_validator("timestamp", "confirmed_at")
    @classmethod
    def must_be_timezone_aware_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
