"""Candle contracts, Timeframe definitions, and Invariant validation for Trader Machine V1."""
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Timeframe(str, Enum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"

    @property
    def duration_seconds(self) -> int:
        match self:
            case Timeframe.M1:
                return 60
            case Timeframe.M5:
                return 300
            case Timeframe.M15:
                return 900
            case Timeframe.H1:
                return 3600

class AggregatedCandle(BaseModel):
    """Pydantic model representing an aggregated OHLCV candle with strict invariant enforcement."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    symbol: str = Field(..., min_length=1, max_length=16)
    timeframe: Timeframe
    timestamp: datetime = Field(..., description="Bucket open timestamp in UTC")
    open: Decimal = Field(..., gt=Decimal("0"))
    high: Decimal = Field(..., gt=Decimal("0"))
    low: Decimal = Field(..., gt=Decimal("0"))
    close: Decimal = Field(..., gt=Decimal("0"))
    tick_volume: int = Field(..., ge=1, description="Count of valid ticks inside bucket")
    real_volume: int = Field(default=0, ge=0, description="Sum of real trade volume if available")
    spread: Decimal = Field(..., ge=Decimal("0"), description="Arithmetic mean of tick spreads")
    is_closed: bool = Field(default=True, description="Indicates whether candle period has completed")

    @field_validator("timestamp")
    @classmethod
    def must_be_timezone_aware_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("Candle timestamp must be timezone-aware UTC")
        return v.astimezone(timezone.utc)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("Symbol cannot be empty")
        return s

    @model_validator(mode="after")
    def verify_price_invariants(self) -> "AggregatedCandle":
        # Check High invariants
        if self.high < self.open:
            raise ValueError(f"Price invariant violated: High ({self.high}) < Open ({self.open})")
        if self.high < self.close:
            raise ValueError(f"Price invariant violated: High ({self.high}) < Close ({self.close})")
        if self.high < self.low:
            raise ValueError(f"Price invariant violated: High ({self.high}) < Low ({self.low})")

        # Check Low invariants
        if self.low > self.open:
            raise ValueError(f"Price invariant violated: Low ({self.low}) > Open ({self.open})")
        if self.low > self.close:
            raise ValueError(f"Price invariant violated: Low ({self.low}) > Close ({self.close})")

        return self
