"""
Contract definitions, Enums, and Data Models for Liquidity Level Engine V1.
Deterministic, observational, strictly no trade signals or assumptions of institutional identity.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class LiquidityLevelType(str, Enum):
    PREVIOUS_DAY_HIGH = "PREVIOUS_DAY_HIGH"
    PREVIOUS_DAY_LOW = "PREVIOUS_DAY_LOW"
    PREVIOUS_WEEK_HIGH = "PREVIOUS_WEEK_HIGH"
    PREVIOUS_WEEK_LOW = "PREVIOUS_WEEK_LOW"
    SESSION_HIGH = "SESSION_HIGH"
    SESSION_LOW = "SESSION_LOW"
    EQUAL_HIGH = "EQUAL_HIGH"
    EQUAL_LOW = "EQUAL_LOW"
    SIGNIFICANT_SWING_HIGH = "SIGNIFICANT_SWING_HIGH"
    SIGNIFICANT_SWING_LOW = "SIGNIFICANT_SWING_LOW"


class LiquidityStatus(str, Enum):
    UNTOUCHED = "UNTOUCHED"
    APPROACHED = "APPROACHED"
    TOUCHED = "TOUCHED"
    SWEPT = "SWEPT"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    INVALIDATED = "INVALIDATED"


class TradingSession(str, Enum):
    ASIA = "ASIA"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    CUSTOM = "CUSTOM"


class LiquidityLevelRecord(BaseModel):
    """
    In-memory representation of a deterministic liquidity level.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    timeframe: str
    level_type: LiquidityLevelType
    price: Decimal
    created_at: datetime
    strength: Decimal = Decimal("1.0000")
    status: LiquidityStatus = LiquidityStatus.UNTOUCHED
    swept_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    invalidated_at: Optional[datetime] = None
    source_swing_id: Optional[str] = None
    session: Optional[str] = None
    tolerance: Decimal = Decimal("0.00010")
    sweep_depth: Optional[Decimal] = None
    id: Optional[str] = None


class SweepEvent(BaseModel):
    """
    Observation record for a confirmed liquidity sweep.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    level_id: Optional[str] = None
    level_type: LiquidityLevelType
    level_price: Decimal
    sweep_direction: str  # "HIGH_SWEPT" or "LOW_SWEPT"
    sweep_timestamp: datetime
    sweep_extreme: Decimal
    sweep_depth: Decimal
    return_timestamp: datetime
    rejection_confirmed: bool = False
    rejection_displacement: Optional[Decimal] = None
