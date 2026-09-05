"""
Contract definitions, Enums, and Pydantic Models for Setup Detector Engine V1.
Deterministic, observational, strictly no trade execution, probabilities, or win rates.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SetupCode(str, Enum):
    S01 = "S01"  # Liquidity Sweep Reversal
    S02 = "S02"  # Liquidity Acceptance Continuation
    S03 = "S03"  # Failed Breakout Trap
    S04 = "S04"  # Effort vs Result Anomaly
    S05 = "S05"  # Compression -> Expansion


class SetupStatus(str, Enum):
    OBSERVE = "OBSERVE"
    WATCH = "WATCH"
    ARMED = "ARMED"
    FIRE = "FIRE"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class SetupDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    UNDEFINED = "UNDEFINED"


class SetupEvidenceItem(BaseModel):
    """Discrete auditable evidence entry."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    key: str
    value: str
    numeric_value: Optional[Decimal] = None
    details: Optional[Dict[str, Any]] = None


class SetupEvidence(BaseModel):
    """
    Categorized evidence supporting a setup decision.
    Every evidence item is deterministic, observable, and explainable.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    liquidity: Optional[str] = None
    price_response: Optional[str] = None
    structure: Optional[str] = None
    anomaly: Optional[str] = None
    trap: Optional[str] = None
    regime: Optional[str] = None
    confirmation: Optional[str] = None
    execution: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)

    def to_evidence_items(self) -> List[SetupEvidenceItem]:
        """Convert fields to a list of auditable evidence items for persistence."""
        items: List[SetupEvidenceItem] = []
        fields = [
            "liquidity",
            "price_response",
            "structure",
            "anomaly",
            "trap",
            "regime",
            "confirmation",
            "execution",
        ]
        for f in fields:
            val = getattr(self, f, None)
            if val is not None:
                numeric_val = None
                if f in self.metrics and isinstance(self.metrics[f], (int, float, Decimal)):
                    numeric_val = Decimal(str(self.metrics[f]))
                items.append(
                    SetupEvidenceItem(
                        key=f,
                        value=str(val),
                        numeric_value=numeric_val,
                        details={"metric": self.metrics.get(f)} if f in self.metrics else None,
                    )
                )
        return items


class SetupRecord(BaseModel):
    """
    Deterministic setup record produced by the Setup Detector Engine.
    Represents an observed market condition satisfying a defined archetype.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    setup_id: str
    setup_code: SetupCode
    symbol: str
    timeframe: str = "M5"
    timestamp: datetime
    direction: SetupDirection
    regime: str = "UNKNOWN"
    liquidity_type: Optional[str] = None
    structure_type: Optional[str] = None
    anomaly_type: Optional[str] = None
    status: SetupStatus
    evidence: SetupEvidence = Field(default_factory=SetupEvidence)
    reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None

    @field_validator("timestamp", "created_at", "expires_at")
    @classmethod
    def must_be_timezone_aware_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("Symbol cannot be empty")
        return s
