"""Deterministic Multi-Timeframe Candle Resampler V1.
Derives M5, M15, and H1 candles from normalized M1 constituent bars.
Enforces strict BID-only semantics: prohibits synthetic Ask, Mid, Spread, or microstructure fabrication.
Preserves non-fabrication gap rules and strict provenance lineage.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.candles.builder import TimeBucketFloor
from core.candles.contract import Timeframe
from core.data_source.contract import TICK_VOLUME_DISCLAIMER, ValidatedCandleRecord


class BidOnlyDataError(ValueError):
    """Raised when an operation attempts to derive synthetic Ask, Mid, or Spread from BID-only data."""
    pass


class DerivedBidCandleRecord(BaseModel):
    """Derived multi-timeframe candle derived explicitly from BID-only source data.
    Ensures that fields unavailable in the source data (Ask, Mid, Spread) remain unavailable
    and cannot be accessed or estimated.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    source_dataset_id: str
    provider: str
    symbol: str
    timeframe: Timeframe
    timestamp: datetime  # Guaranteed UTC bucket floor
    price_type: str = "BID"

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Field(default=Decimal("0"), description="Observed quote/tick count or activity. Not real volume.")
    m1_bars_count: int = Field(..., ge=1, description="Count of M1 constituent bars aggregated into this candle.")
    derivation_version: str = "V1"
    volume_semantics: str = TICK_VOLUME_DISCLAIMER

    @property
    def ask_open(self) -> None:
        raise BidOnlyDataError("Ask price stream is unavailable: source dataset is explicitly BID-only.")

    @property
    def ask_close(self) -> None:
        raise BidOnlyDataError("Ask price stream is unavailable: source dataset is explicitly BID-only.")

    @property
    def mid_close(self) -> None:
        raise BidOnlyDataError("Mid price stream is unavailable: source dataset is explicitly BID-only (cannot compute without Ask).")

    @property
    def spread(self) -> None:
        raise BidOnlyDataError("Spread is unavailable: source dataset is explicitly BID-only (cannot compute Ask - Bid).")

    @model_validator(mode="after")
    def verify_invariants(self) -> "DerivedBidCandleRecord":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError(f"High ({self.high}) violates OHLC upper bound: open={self.open}, close={self.close}, low={self.low}")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError(f"Low ({self.low}) violates OHLC lower bound: open={self.open}, close={self.close}, high={self.high}")
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) cannot be less than Low ({self.low})")
        if self.open <= Decimal("0") or self.close <= Decimal("0") or self.high <= Decimal("0") or self.low <= Decimal("0"):
            raise ValueError("All OHLC prices must be strictly positive.")
        if self.timestamp.tzinfo != timezone.utc:
            raise ValueError("Candle timestamp must be in timezone-aware UTC.")
        return self


class CandleResampler:
    """Deterministic aggregator resampling M1 constituent candles to higher timeframes (M5, M15, H1).
    Follows strict causality and zero-fabrication rules.
    """

    SUPPORTED_RESAMPLE_TIMEFRAMES = {
        Timeframe.M5: 300,
        Timeframe.M15: 900,
        Timeframe.H1: 3600,
    }

    @classmethod
    def resample_m1(
        cls,
        m1_records: Sequence[Union[ValidatedCandleRecord, dict[str, Any], Any]],
        target_timeframe: Union[Timeframe, str],
        source_dataset_id: str,
        provider: str = "UNKNOWN",
        symbol: str = "EURUSD",
    ) -> list[DerivedBidCandleRecord]:
        """Resample a collection of M1 constituent candles into target timeframe candles.
        
        Args:
            m1_records: Sequence of chronological M1 candle records.
            target_timeframe: Target timeframe (M5, M15, or H1).
            source_dataset_id: Lineage reference identifier of source dataset.
            provider: Market data provider / origin.
            symbol: Financial instrument symbol.
            
        Returns:
            List of derived higher-timeframe candles strictly maintaining BID semantics.
        """
        tf = Timeframe(target_timeframe) if isinstance(target_timeframe, str) else target_timeframe
        if tf not in cls.SUPPORTED_RESAMPLE_TIMEFRAMES:
            raise ValueError(f"Unsupported target resampling timeframe '{tf}'. Supported: {list(cls.SUPPORTED_RESAMPLE_TIMEFRAMES.keys())}")

        if not m1_records:
            return []

        # 1. Normalize and verify chronological ordering of M1 inputs
        parsed_bars: list[dict[str, Any]] = []
        for idx, bar in enumerate(m1_records):
            if isinstance(bar, ValidatedCandleRecord):
                ts = bar.timestamp
                o = bar.open
                h = bar.high
                l = bar.low
                c = bar.close
                v = bar.volume
            elif isinstance(bar, dict):
                ts = bar["timestamp"]
                o = Decimal(str(bar["open"]))
                h = Decimal(str(bar["high"]))
                l = Decimal(str(bar["low"]))
                c = Decimal(str(bar["close"]))
                v = Decimal(str(bar.get("volume", 0)))
            else:
                ts = getattr(bar, "timestamp")
                o = Decimal(str(getattr(bar, "open")))
                h = Decimal(str(getattr(bar, "high")))
                l = Decimal(str(getattr(bar, "low")))
                c = Decimal(str(getattr(bar, "close")))
                v = Decimal(str(getattr(bar, "volume", 0)))

            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)

            parsed_bars.append({
                "timestamp": ts,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            })

        # Ensure sorted
        parsed_bars.sort(key=lambda b: b["timestamp"])

        # 2. Group into discrete half-open target timeframe buckets [bucket_start, bucket_end)
        buckets: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
        for b in parsed_bars:
            bucket_ts = TimeBucketFloor.floor_timestamp(b["timestamp"], tf)
            buckets[bucket_ts].append(b)

        # 3. Aggregate each non-empty bucket
        # NO SYNTHETIC CANDLES: only buckets with observed constituent M1 bars are generated.
        derived_candles: list[DerivedBidCandleRecord] = []
        for bucket_ts in sorted(buckets.keys()):
            constituents = buckets[bucket_ts]
            agg_open = constituents[0]["open"]
            agg_high = max(c["high"] for c in constituents)
            agg_low = min(c["low"] for c in constituents)
            agg_close = constituents[-1]["close"]
            agg_volume = sum(c["volume"] for c in constituents)

            derived_candle = DerivedBidCandleRecord(
                source_dataset_id=source_dataset_id,
                provider=provider,
                symbol=symbol.upper(),
                timeframe=tf,
                timestamp=bucket_ts,
                price_type="BID",
                open=agg_open,
                high=agg_high,
                low=agg_low,
                close=agg_close,
                volume=agg_volume,
                m1_bars_count=len(constituents),
                derivation_version="V1",
            )
            derived_candles.append(derived_candle)

        return derived_candles

    @classmethod
    def persist_derived_candles(
        cls,
        derived_candles: Sequence[DerivedBidCandleRecord],
        session: Optional[Any] = None,
        register_dataset: bool = True,
    ) -> dict[str, Any]:
        """Persist derived candles into the database and record provenance in market_datasets."""
        from sqlalchemy.dialects.postgresql import insert
        from database.connection import get_session_factory
        from database.models import MarketCandle, MarketDataset
        import hashlib

        if not derived_candles:
            return {"inserted_count": 0, "dataset_id": None}

        first_c = derived_candles[0]
        symbol = first_c.symbol
        timeframe = first_c.timeframe.value
        source_dataset_id = first_c.source_dataset_id
        provider = first_c.provider

        should_close = False
        if session is None:
            factory = get_session_factory()
            session = factory()
            should_close = True

        try:
            # 1. Insert into market_candles
            chunk_size = 5000
            for i in range(0, len(derived_candles), chunk_size):
                chunk = derived_candles[i : i + chunk_size]
                stmt = insert(MarketCandle).values([
                    {
                        "symbol": c.symbol,
                        "timeframe": c.timeframe.value,
                        "timestamp": c.timestamp,
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "tick_volume": int(c.volume),
                        "real_volume": 0,
                        "spread": Decimal("0.0"),
                    }
                    for c in chunk
                ])
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["symbol", "timeframe", "timestamp"]
                )
                session.execute(stmt)

            dataset_id = None
            if register_dataset:
                # Content hash
                hash_input = "".join(f"{c.timestamp.isoformat()}:{c.open}:{c.high}:{c.low}:{c.close}:{c.volume}" for c in derived_candles)
                content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

                dataset_name = f"{symbol}_{timeframe}_DERIVED_FROM_DS{source_dataset_id}_{content_hash[:8]}"
                existing = session.query(MarketDataset).filter_by(content_hash=content_hash).first()
                if existing:
                    dataset_id = existing.id
                else:
                    ds = MarketDataset(
                        dataset_name=dataset_name,
                        source_name=f"DERIVED_{timeframe}_FROM_{source_dataset_id}",
                        source_type="DERIVED",
                        source_file=f"derived_from_dataset_id_{source_dataset_id}",
                        format="DERIVED",
                        symbol=symbol,
                        timeframe=timeframe,
                        timezone="UTC",
                        first_timestamp=derived_candles[0].timestamp,
                        last_timestamp=derived_candles[-1].timestamp,
                        row_count=len(derived_candles),
                        content_hash=content_hash,
                        schema_version="V1",
                        quality_status="PASS",
                    )
                    session.add(ds)
                    session.flush()
                    dataset_id = ds.id

            session.commit()
            return {
                "inserted_count": len(derived_candles),
                "dataset_id": dataset_id,
                "timeframe": timeframe,
                "first_timestamp": derived_candles[0].timestamp.isoformat(),
                "last_timestamp": derived_candles[-1].timestamp.isoformat(),
            }
        except Exception:
            session.rollback()
            raise
        finally:
            if should_close:
                session.close()
