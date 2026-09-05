"""
Contract definitions, Enums, and Pydantic models for Statistical Edge Engine V1.
Deterministic statistical evidence evaluation, Wilson intervals, bootstrapping,
and multi-factor edge classification. Strictly zero parameter optimization or AI/ML.
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EdgeClassification(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NEGATIVE_EDGE = "NEGATIVE_EDGE"
    NO_CLEAR_EDGE = "NO_CLEAR_EDGE"
    PRELIMINARY_EDGE = "PRELIMINARY_EDGE"
    POTENTIAL_EDGE = "POTENTIAL_EDGE"
    ROBUST_EDGE = "ROBUST_EDGE"
    INVALID_DATA = "INVALID_DATA"


class SampleReliability(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    PRELIMINARY = "PRELIMINARY"
    STATISTICALLY_RELEVANT_CANDIDATE = "STATISTICALLY_RELEVANT_CANDIDATE"


class OOSDegradationStatus(str, Enum):
    STABLE = "STABLE"
    DEGRADED = "DEGRADED"
    COLLAPSED = "COLLAPSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SegmentType(str, Enum):
    REGIME = "REGIME"
    SESSION = "SESSION"
    DIRECTION = "DIRECTION"
    LIQUIDITY_TYPE = "LIQUIDITY_TYPE"
    SPREAD_BUCKET = "SPREAD_BUCKET"
    DAY_OF_WEEK = "DAY_OF_WEEK"
    MTF_ALIGNMENT = "MTF_ALIGNMENT"
    VOLATILITY_STATE = "VOLATILITY_STATE"


class WilsonConfidenceInterval(BaseModel):
    """Wilson score confidence interval for binomial proportion."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    lower_bound: Decimal
    upper_bound: Decimal
    confidence_level: Decimal = Decimal("0.95")


class BootstrapMetricResult(BaseModel):
    """Distribution summary from deterministic bootstrap resampling."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    metric: str
    iterations: int = 10000
    lower_bound: Decimal  # e.g. 2.5 percentile
    median: Decimal       # 50.0 percentile
    upper_bound: Decimal  # e.g. 97.5 percentile
    positive_fraction: Decimal  # fraction of iterations > 0


class MonteCarloMetricResult(BaseModel):
    """Sequence-risk distribution from deterministic trade order permutations."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    iterations: int = 1000
    drawdown_p95: Decimal
    drawdown_p99: Decimal
    drawdown_median: Decimal
    terminal_r_p5: Decimal
    terminal_r_median: Decimal
    prob_negative_terminal: Decimal


class OOSDegradationReport(BaseModel):
    """Out-of-sample degradation comparison against in-sample performance."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    is_expectancy: Optional[Decimal] = None
    oos_expectancy: Optional[Decimal] = None
    expectancy_ratio: Optional[Decimal] = None
    is_win_rate: Optional[Decimal] = None
    oos_win_rate: Optional[Decimal] = None
    status: OOSDegradationStatus = OOSDegradationStatus.NOT_APPLICABLE
    reason: str = ""


class StatisticalMetricRecord(BaseModel):
    """Comprehensive statistical metrics record for a setup and split."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    setup_code: str
    split_type: str = "ALL"
    sample_size: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    ambiguous: int = 0
    win_rate: Optional[Decimal] = None
    win_rate_ci: Optional[WilsonConfidenceInterval] = None
    average_win_r: Optional[Decimal] = None
    average_loss_r: Optional[Decimal] = None
    expectancy_r: Optional[Decimal] = None
    expectancy_ci: Optional[BootstrapMetricResult] = None
    profit_factor: Optional[Decimal] = None
    total_r: Decimal = Decimal("0.0000")
    max_drawdown_r: Decimal = Decimal("0.0000")
    max_consecutive_losses: int = 0
    mean_r: Optional[Decimal] = None
    median_r: Optional[Decimal] = None
    std_r: Optional[Decimal] = None
    sample_reliability: SampleReliability = SampleReliability.INSUFFICIENT_DATA
    classification: EdgeClassification = EdgeClassification.INSUFFICIENT_DATA


class SegmentMetricRecord(BaseModel):
    """Performance metrics for an exploratory slice of historical data."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    setup_code: str
    segment_type: SegmentType
    segment_value: str
    sample_size: int = 0
    win_rate: Optional[Decimal] = None
    expectancy_r: Optional[Decimal] = None
    profit_factor: Optional[Decimal] = None
    total_r: Decimal = Decimal("0.0000")
    max_drawdown_r: Decimal = Decimal("0.0000")


class StatisticalRunRecord(BaseModel):
    """Execution run record for statistical edge engine."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    backtest_run_id: int
    dataset_split: str = "ALL"
    engine_version: str = "1.0.0"
    config_hash: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    status: str = "RUNNING"
    overall_classification: EdgeClassification = EdgeClassification.INSUFFICIENT_DATA
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("started_at", "completed_at", "created_at")
    @classmethod
    def ensure_tz_aware_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
