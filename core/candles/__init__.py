"""Candle Aggregation Package for Trader Machine V1."""
from core.candles.contract import Timeframe, AggregatedCandle
from core.candles.boundary import get_candle_bucket, is_in_bucket
from core.candles.aggregator import CandleAggregator
from core.candles.loader import CandleDatabaseLoader, CandleLoadResult
from core.candles.engine import CandleAggregationEngine, AggregationSummary
from core.candles.builder import (
    DerivedCandleRecord,
    InputTickRecord,
    TickCandleBuilder,
    TimeBucketFloor,
    OutOfOrderTickError,
    InvalidTickError,
)
from core.candles.resampler import (
    BidOnlyDataError,
    CandleResampler,
    DerivedBidCandleRecord,
)

__all__ = [
    "Timeframe",
    "AggregatedCandle",
    "get_candle_bucket",
    "is_in_bucket",
    "CandleAggregator",
    "CandleDatabaseLoader",
    "CandleLoadResult",
    "CandleAggregationEngine",
    "AggregationSummary",
    "DerivedCandleRecord",
    "InputTickRecord",
    "TickCandleBuilder",
    "TimeBucketFloor",
    "OutOfOrderTickError",
    "InvalidTickError",
    "BidOnlyDataError",
    "CandleResampler",
    "DerivedBidCandleRecord",
]
