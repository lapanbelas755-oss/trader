"""Candle Aggregation Package for Trader Machine V1."""
from core.candles.contract import Timeframe, AggregatedCandle
from core.candles.boundary import get_candle_bucket, is_in_bucket
from core.candles.aggregator import CandleAggregator
from core.candles.loader import CandleDatabaseLoader, CandleLoadResult
from core.candles.engine import CandleAggregationEngine, AggregationSummary

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
]
