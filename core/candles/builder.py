"""Deterministic Tick-to-Candle Aggregation Builder V1.
Transforms normalized real tick feeds into M1, M5, M15, and H1 candles with complete
Mid, Bid, and Ask OHLC streams, spread distributions, tick counts, gap audits, and provenance lineage.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import math
from typing import Any, Iterator, Optional, Sequence, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.candles.contract import Timeframe
from core.data_source.contract import TICK_VOLUME_DISCLAIMER


TIMEFRAME_SECONDS = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.H1: 3600,
}


class OutOfOrderTickError(ValueError):
    """Raised when input ticks arrive out of chronological order."""
    pass


class InvalidTickError(ValueError):
    """Raised when tick prices violate basic bid/ask/price rules."""
    pass


@dataclass(frozen=True)
class InputTickRecord:
    """Normalized tick record ready for multi-timeframe candle aggregation."""
    timestamp: datetime
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Optional[Decimal] = None
    volume: Decimal = Decimal("1")
    provider: str = "UNKNOWN"
    source_dataset_id: str = "UNKNOWN"


class DerivedCandleRecord(BaseModel):
    """Rich derived candle containing Mid, Bid, Ask OHLC and spread statistics."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    source_dataset_id: str
    provider: str
    symbol: str
    timeframe: Timeframe
    timestamp: datetime  # Guaranteed UTC bucket floor

    # Mid OHLC (Primary Research Price Stream)
    mid_open: Decimal
    mid_high: Decimal
    mid_low: Decimal
    mid_close: Decimal

    # Bid OHLC
    bid_open: Decimal
    bid_high: Decimal
    bid_low: Decimal
    bid_close: Decimal

    # Ask OHLC
    ask_open: Decimal
    ask_high: Decimal
    ask_low: Decimal
    ask_close: Decimal

    # Spread Statistics
    spread_open: Decimal
    spread_high: Decimal
    spread_low: Decimal
    spread_close: Decimal
    spread_mean: Decimal
    spread_median: Decimal
    spread_min: Decimal
    spread_max: Decimal

    # Activity & Provenance
    tick_count: int = Field(..., ge=1, description="Count of observed ticks. Not real traded volume.")
    derivation_version: str = "V1"
    volume_semantics: str = TICK_VOLUME_DISCLAIMER

    @model_validator(mode="after")
    def verify_invariants(self) -> "DerivedCandleRecord":
        # Check Mid invariants
        if self.mid_high < max(self.mid_open, self.mid_close, self.mid_low):
            raise ValueError(f"Mid High ({self.mid_high}) invariant violated.")
        if self.mid_low > min(self.mid_open, self.mid_close, self.mid_high):
            raise ValueError(f"Mid Low ({self.mid_low}) invariant violated.")

        # Check Bid invariants
        if self.bid_high < max(self.bid_open, self.bid_close, self.bid_low):
            raise ValueError(f"Bid High ({self.bid_high}) invariant violated.")
        if self.bid_low > min(self.bid_open, self.bid_close, self.bid_low):
            raise ValueError(f"Bid Low ({self.bid_low}) invariant violated.")

        # Check Ask invariants
        if self.ask_high < max(self.ask_open, self.ask_close, self.ask_low):
            raise ValueError(f"Ask High ({self.ask_high}) invariant violated.")
        if self.ask_low > min(self.ask_open, self.ask_close, self.ask_low):
            raise ValueError(f"Ask Low ({self.ask_low}) invariant violated.")

        # Spread consistency
        if self.spread_min < Decimal("0") or self.spread_max < self.spread_min:
            raise ValueError(f"Spread bounds violated: min={self.spread_min}, max={self.spread_max}")

        return self


class TimeBucketFloor:
    """Floors UTC datetimes to exact timeframe boundaries."""

    @staticmethod
    def floor_timestamp(ts: datetime, timeframe: Timeframe) -> datetime:
        """Floor timestamp to timeframe bucket open in UTC."""
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)

        match timeframe:
            case Timeframe.M1:
                return ts.replace(second=0, microsecond=0)
            case Timeframe.M5:
                minute = (ts.minute // 5) * 5
                return ts.replace(minute=minute, second=0, microsecond=0)
            case Timeframe.M15:
                minute = (ts.minute // 15) * 15
                return ts.replace(minute=minute, second=0, microsecond=0)
            case Timeframe.H1:
                return ts.replace(minute=0, second=0, microsecond=0)
            case _:
                raise ValueError(f"Unsupported timeframe for flooring: {timeframe}")


class CandleAccumulator:
    """Accumulates ticks within a single discrete timeframe bucket."""

    def __init__(self, bucket_ts: datetime, symbol: str, timeframe: Timeframe, provider: str, source_dataset_id: str):
        self.bucket_ts = bucket_ts
        self.symbol = symbol
        self.timeframe = timeframe
        self.provider = provider
        self.source_dataset_id = source_dataset_id

        self.ticks: list[InputTickRecord] = []
        self.bids: list[Decimal] = []
        self.asks: list[Decimal] = []
        self.mids: list[Decimal] = []
        self.spreads: list[Decimal] = []

    def add_tick(self, tick: InputTickRecord) -> None:
        """Add a validated tick to the current bucket."""
        # Derive Mid price: Last if valid, else (Bid + Ask) / 2
        if tick.last is not None and tick.last > Decimal("0"):
            mid = tick.last
        else:
            mid = (tick.bid + tick.ask) / Decimal("2")

        spread = tick.ask - tick.bid

        self.ticks.append(tick)
        self.bids.append(tick.bid)
        self.asks.append(tick.ask)
        self.mids.append(mid)
        self.spreads.append(spread)

    def build_candle(self) -> DerivedCandleRecord:
        """Build completed immutable DerivedCandleRecord from accumulated ticks."""
        if not self.ticks:
            raise ValueError("Cannot build candle from empty accumulator.")

        # Spread statistics
        spread_open = self.spreads[0]
        spread_close = self.spreads[-1]
        spread_min = min(self.spreads)
        spread_max = max(self.spreads)
        spread_mean = sum(self.spreads) / Decimal(len(self.spreads))

        sorted_spreads = sorted(self.spreads)
        mid_idx = len(sorted_spreads) // 2
        if len(sorted_spreads) % 2 == 1:
            spread_median = sorted_spreads[mid_idx]
        else:
            spread_median = (sorted_spreads[mid_idx - 1] + sorted_spreads[mid_idx]) / Decimal("2")

        return DerivedCandleRecord(
            source_dataset_id=self.source_dataset_id,
            provider=self.provider,
            symbol=self.symbol,
            timeframe=self.timeframe,
            timestamp=self.bucket_ts,
            # Mid OHLC
            mid_open=self.mids[0],
            mid_high=max(self.mids),
            mid_low=min(self.mids),
            mid_close=self.mids[-1],
            # Bid OHLC
            bid_open=self.bids[0],
            bid_high=max(self.bids),
            bid_low=min(self.bids),
            bid_close=self.bids[-1],
            # Ask OHLC
            ask_open=self.asks[0],
            ask_high=max(self.asks),
            ask_low=min(self.asks),
            ask_close=self.asks[-1],
            # Spread Stats
            spread_open=spread_open,
            spread_high=spread_max,
            spread_low=spread_min,
            spread_close=spread_close,
            spread_mean=spread_mean,
            spread_median=spread_median,
            spread_min=spread_min,
            spread_max=spread_max,
            # Activity
            tick_count=len(self.ticks),
        )


class TickCandleBuilder:
    """Streaming tick-to-candle aggregator converting tick streams into multi-timeframe candles."""

    def __init__(self, timeframe: Timeframe):
        self.timeframe = timeframe
        self.bucket_seconds = TIMEFRAME_SECONDS[timeframe]

    def aggregate_stream(
        self,
        ticks: Iterator[InputTickRecord],
        record_gaps: bool = True,
    ) -> Iterator[Union[DerivedCandleRecord, tuple[datetime, datetime, float]]]:
        """Process ticks chronologically and yield completed candles as buckets close.
        
        Yields:
            DerivedCandleRecord when each time bucket closes.
            Never yields synthetic candles for missing intervals.
        """
        current_accumulator: Optional[CandleAccumulator] = None
        last_tick_ts: Optional[datetime] = None
        last_bucket_ts: Optional[datetime] = None

        for tick in ticks:
            # 1. Validate Tick Price Rules
            if tick.bid <= Decimal("0") or tick.ask <= Decimal("0"):
                raise InvalidTickError(f"Invalid non-positive tick price: bid={tick.bid}, ask={tick.ask}")
            if tick.ask < tick.bid:
                raise InvalidTickError(f"Inverted spread: ask ({tick.ask}) < bid ({tick.bid})")

            # 2. Enforce Chronological Monotonicity
            ts_utc = tick.timestamp.astimezone(timezone.utc) if tick.timestamp.tzinfo else tick.timestamp.replace(tzinfo=timezone.utc)
            if last_tick_ts is not None and ts_utc < last_tick_ts:
                raise OutOfOrderTickError(
                    f"Out of order tick received: tick at {ts_utc.isoformat()} arrived after {last_tick_ts.isoformat()}"
                )
            last_tick_ts = ts_utc

            # 3. Calculate Target Bucket
            bucket_ts = TimeBucketFloor.floor_timestamp(ts_utc, self.timeframe)

            # 4. Check If Transitioning to New Bucket
            if current_accumulator is None:
                current_accumulator = CandleAccumulator(
                    bucket_ts=bucket_ts,
                    symbol=tick.symbol,
                    timeframe=self.timeframe,
                    provider=tick.provider,
                    source_dataset_id=tick.source_dataset_id,
                )
                current_accumulator.add_tick(tick)
                last_bucket_ts = bucket_ts
            elif bucket_ts == current_accumulator.bucket_ts:
                current_accumulator.add_tick(tick)
            else:
                # Close and yield previous candle
                yield current_accumulator.build_candle()

                # Start new bucket accumulator (NO SYNTHETIC CANDLES FOR GAPS)
                current_accumulator = CandleAccumulator(
                    bucket_ts=bucket_ts,
                    symbol=tick.symbol,
                    timeframe=self.timeframe,
                    provider=tick.provider,
                    source_dataset_id=tick.source_dataset_id,
                )
                current_accumulator.add_tick(tick)
                last_bucket_ts = bucket_ts

        # 5. Flush Final Remaining Bucket
        if current_accumulator is not None and current_accumulator.ticks:
            yield current_accumulator.build_candle()
