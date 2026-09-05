"""
Contract definitions, Enums, and Pydantic Models for Backtest Engine V1.
Deterministic historical trade simulation, R-multiples, and performance metrics.
Strictly zero broker order generation, zero parameter optimization.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TradeResult(str, Enum):
    TP = "TP"
    SL = "SL"
    TIMEOUT = "TIMEOUT"
    INVALID = "INVALID"
    DATA_ERROR = "DATA_ERROR"
    AMBIGUOUS = "AMBIGUOUS"
    SKIPPED_ACTIVE_TRADE = "SKIPPED_ACTIVE_TRADE"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SKIPPED = "SKIPPED"
    INVALID = "INVALID"


class EntryPriceType(str, Enum):
    REAL_BID_ASK = "REAL_BID_ASK"
    FALLBACK_PRICE = "FALLBACK_PRICE"


class CollisionPolicy(str, Enum):
    MAX_ONE_ACTIVE_TRADE_PER_SYMBOL = "MAX_ONE_ACTIVE_TRADE_PER_SYMBOL"
    ALLOW_ALL = "ALLOW_ALL"


class BacktestTradeRecord(BaseModel):
    """Deterministic simulated trade execution record."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trade_id: Optional[str] = None
    backtest_run_id: Optional[int] = None
    setup_id: str
    setup_code: str
    symbol: str = "EURUSD"
    timeframe: str = "M5"
    direction: str  # BULLISH / BEARISH
    entry_time: datetime
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    exit_time: Optional[datetime] = None
    exit_price: Optional[Decimal] = None
    result: TradeResult
    r_multiple: Optional[Decimal] = None
    mae_r: Optional[Decimal] = None
    mfe_r: Optional[Decimal] = None
    commission: Decimal = Decimal("0.0")
    slippage: Decimal = Decimal("0.0")
    spread: Decimal = Decimal("0.0")
    status: TradeStatus = TradeStatus.CLOSED
    split_type: str = "IN_SAMPLE"
    ambiguity_reason: Optional[str] = None
    entry_price_type: EntryPriceType = EntryPriceType.FALLBACK_PRICE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("entry_time", "exit_time", "created_at")
    @classmethod
    def ensure_tz_aware_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class TradeMetrics(BaseModel):
    """Performance metrics calculated strictly from realized R-multiples."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sample_size: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    ambiguous: int = 0
    skipped: int = 0
    invalid: int = 0
    win_rate: Optional[Decimal] = None
    average_win_r: Optional[Decimal] = None
    average_loss_r: Optional[Decimal] = None
    expectancy_r: Optional[Decimal] = None
    profit_factor: Optional[Decimal] = None  # None / inf if no losses
    total_r: Decimal = Decimal("0.0000")
    max_drawdown_r: Decimal = Decimal("0.0000")
    max_consecutive_losses: int = 0


class SplitMetrics(BaseModel):
    """Partitioned metrics across chronological splits."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    in_sample: TradeMetrics = Field(default_factory=TradeMetrics)
    validation: TradeMetrics = Field(default_factory=TradeMetrics)
    out_of_sample: TradeMetrics = Field(default_factory=TradeMetrics)


class BacktestRunRecord(BaseModel):
    """Execution run metadata."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    research_run_id: int
    backtest_version: str = "1.0.0"
    config_hash: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    status: str = "RUNNING"
    trade_count: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    ambiguous: int = 0
    skipped: int = 0
    total_r: Decimal = Decimal("0.0000")
    metrics: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
