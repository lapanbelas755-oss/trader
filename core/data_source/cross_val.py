"""Cross-Validation Framework for Comparing Disparate Market Data Feeds.
Provides statistical feed comparisons (coverage, spread distributions, tick frequency,
volatility, and session behavior) without assuming identical candle-level quotes.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import math
from typing import Optional, Sequence
from pydantic import BaseModel, ConfigDict, Field

from core.data_source.contract import ValidatedCandleRecord, ValidatedTickRecord
from core.data_source.staged import DataProvider


CROSS_VALIDATION_DISCLAIMER = (
    "CROSS-VALIDATION NOTICE: Spot FX is an OTC decentralized market. Different providers "
    "(e.g. Dukascopy vs TrueFX) represent distinct liquidity pools, quote aggregators, and filters. "
    "Candle-by-candle price discrepancies are expected and must not be treated as data corruption. "
    "Cross-validation evaluates structural consistency (coverage, volatility, spreads, and gaps)."
)


class SpreadStatistics(BaseModel):
    """Distributional metrics for observed spreads."""
    mean_spread_pips: float = 0.0
    median_spread_pips: float = 0.0
    min_spread_pips: float = 0.0
    max_spread_pips: float = 0.0
    std_spread_pips: float = 0.0


class FeedCharacteristics(BaseModel):
    """Summary profile of an individual market feed's observable characteristics."""
    provider: DataProvider
    row_count: int
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    spread_stats: SpreadStatistics = Field(default_factory=SpreadStatistics)
    mean_candle_range_pips: float = 0.0
    gap_count: int = 0
    total_missing_bars: int = 0
    estimated_daily_tick_count: float = 0.0


class CrossValidationReport(BaseModel):
    """Comparative structural audit between two independent provider feeds."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    primary_feed: FeedCharacteristics
    comparison_feed: FeedCharacteristics
    time_overlap_start: Optional[datetime] = None
    time_overlap_end: Optional[datetime] = None
    coverage_overlap_ratio: float = 0.0
    spread_ratio: float = 1.0  # comparison mean spread / primary mean spread
    volatility_ratio: float = 1.0
    tick_frequency_ratio: float = 1.0
    disclaimer: str = CROSS_VALIDATION_DISCLAIMER


class CrossValidationComparator:
    """Evaluates cross-provider consistency across statistical dimensions."""

    @staticmethod
    def _compute_spread_stats(records: Sequence[ValidatedCandleRecord]) -> SpreadStatistics:
        spreads = [float(r.spread) for r in records if r.spread is not None]
        if not spreads:
            return SpreadStatistics()

        spreads.sort()
        n = len(spreads)
        mean_s = sum(spreads) / n
        median_s = spreads[n // 2]
        min_s = spreads[0]
        max_s = spreads[-1]
        variance = sum((x - mean_s) ** 2 for x in spreads) / n if n > 1 else 0.0
        std_s = math.sqrt(variance)

        return SpreadStatistics(
            mean_spread_pips=round(mean_s, 2),
            median_spread_pips=round(median_s, 2),
            min_spread_pips=round(min_s, 2),
            max_spread_pips=round(max_s, 2),
            std_spread_pips=round(std_s, 2),
        )

    @classmethod
    def profile_feed(
        cls,
        provider: DataProvider,
        records: Sequence[ValidatedCandleRecord],
        timeframe_seconds: int = 300,
    ) -> FeedCharacteristics:
        """Extract statistical footprint from a collection of validated candles."""
        if not records:
            return FeedCharacteristics(provider=provider, row_count=0)

        first_ts = records[0].timestamp
        last_ts = records[-1].timestamp
        spread_stats = cls._compute_spread_stats(records)

        # Candle range in pips (EURUSD pip = 0.0001)
        ranges = [float(r.high - r.low) * 10000.0 for r in records]
        mean_range = sum(ranges) / len(ranges) if ranges else 0.0

        # Gap count
        gap_count = 0
        missing_bars = 0
        for i in range(1, len(records)):
            delta = (records[i].timestamp - records[i - 1].timestamp).total_seconds()
            if delta > timeframe_seconds:
                gap_count += 1
                missing_bars += int(round(delta / timeframe_seconds)) - 1

        total_days = max(1.0, (last_ts - first_ts).total_seconds() / 86400.0)
        total_vol = sum(float(r.volume) for r in records)
        daily_ticks = total_vol / total_days

        return FeedCharacteristics(
            provider=provider,
            row_count=len(records),
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            spread_stats=spread_stats,
            mean_candle_range_pips=round(mean_range, 2),
            gap_count=gap_count,
            total_missing_bars=missing_bars,
            estimated_daily_tick_count=round(daily_ticks, 1),
        )

    @classmethod
    def compare_feeds(
        cls,
        primary_provider: DataProvider,
        primary_records: Sequence[ValidatedCandleRecord],
        comparison_provider: DataProvider,
        comparison_records: Sequence[ValidatedCandleRecord],
        timeframe_seconds: int = 300,
    ) -> CrossValidationReport:
        """Compare primary feed against an independent cross-validation feed."""
        feed1 = cls.profile_feed(primary_provider, primary_records, timeframe_seconds)
        feed2 = cls.profile_feed(comparison_provider, comparison_records, timeframe_seconds)

        if not primary_records or not comparison_records:
            return CrossValidationReport(primary_feed=feed1, comparison_feed=feed2)

        # Calculate time overlap
        overlap_start = max(feed1.first_timestamp, feed2.first_timestamp)
        overlap_end = min(feed1.last_timestamp, feed2.last_timestamp)

        if overlap_start < overlap_end:
            overlap_duration = (overlap_end - overlap_start).total_seconds()
            total_duration = (max(feed1.last_timestamp, feed2.last_timestamp) - min(feed1.first_timestamp, feed2.first_timestamp)).total_seconds()
            coverage_ratio = round(overlap_duration / total_duration, 4) if total_duration > 0 else 0.0
        else:
            coverage_ratio = 0.0
            overlap_start = None
            overlap_end = None

        # Ratios
        spread_ratio = round(feed2.spread_stats.mean_spread_pips / feed1.spread_stats.mean_spread_pips, 2) if feed1.spread_stats.mean_spread_pips > 0 else 1.0
        vol_ratio = round(feed2.mean_candle_range_pips / feed1.mean_candle_range_pips, 2) if feed1.mean_candle_range_pips > 0 else 1.0
        tick_ratio = round(feed2.estimated_daily_tick_count / feed1.estimated_daily_tick_count, 2) if feed1.estimated_daily_tick_count > 0 else 1.0

        return CrossValidationReport(
            primary_feed=feed1,
            comparison_feed=feed2,
            time_overlap_start=overlap_start,
            time_overlap_end=overlap_end,
            coverage_overlap_ratio=coverage_ratio,
            spread_ratio=spread_ratio,
            volatility_ratio=vol_ratio,
            tick_frequency_ratio=tick_ratio,
        )
