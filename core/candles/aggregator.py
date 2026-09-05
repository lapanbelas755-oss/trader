"""Deterministic candle aggregation engine from raw market ticks."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Sequence
from core.candles.boundary import get_candle_bucket
from core.candles.contract import AggregatedCandle, Timeframe

class CandleAggregator:
    """Aggregates sorted market ticks into discrete, invariant-verified OHLCV candles."""

    def __init__(self, timeframe: Timeframe, only_closed: bool = True, spread_unit: str = "pips"):
        self.timeframe = timeframe
        self.only_closed = only_closed
        self.spread_unit = spread_unit

    def _extract_tick_attr(self, tick: Any, attr: str) -> Any:
        """Helper to extract attribute from dict or object uniformly."""
        if isinstance(tick, dict):
            return tick.get(attr)
        return getattr(tick, attr, None)

    def _get_tick_price(self, tick: Any) -> Decimal:
        """
        Deterministic price extraction hierarchy:
        1. 'last' if provided and positive
        2. Fallback to 'bid'
        """
        last_val = self._extract_tick_attr(tick, "last")
        if last_val is not None:
            dec_last = Decimal(str(last_val))
            if dec_last > Decimal("0"):
                return dec_last

        bid_val = self._extract_tick_attr(tick, "bid")
        if bid_val is None:
            raise ValueError(f"Tick missing both 'last' and 'bid': {tick}")
        return Decimal(str(bid_val))

    def _get_tick_spread(self, tick: Any) -> Decimal:
        """Calculate tick spread: ask - bid."""
        ask_val = Decimal(str(self._extract_tick_attr(tick, "ask")))
        bid_val = Decimal(str(self._extract_tick_attr(tick, "bid")))
        spread = ask_val - bid_val
        if spread < Decimal("0"):
            raise ValueError(f"Negative tick spread: ask ({ask_val}) < bid ({bid_val})")
        return spread

    def aggregate_ticks(
        self,
        ticks: Iterable[Any],
        data_end_time: datetime | None = None,
    ) -> list[AggregatedCandle]:
        """
        Group and aggregate raw ticks into closed candles.
        Args:
            ticks: Stream or list of raw tick dictionaries or models.
            data_end_time: Optional explicit timestamp marking the end of historical data.
                           If None, inferred from the last tick timestamp.
        """
        # 1. Collect and normalize ticks
        tick_list = list(ticks)
        if not tick_list:
            return []

        # 2. Sort deterministically by (timestamp ASC, id ASC)
        def sort_key(t: Any) -> tuple[datetime, int]:
            ts = self._extract_tick_attr(t, "timestamp")
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            t_id = self._extract_tick_attr(t, "id") or 0
            return (ts, int(t_id) if isinstance(t_id, (int, str)) and str(t_id).isdigit() else 0)

        tick_list.sort(key=sort_key)

        # Incur boundary cutoff
        if data_end_time is None:
            last_ts = self._extract_tick_attr(tick_list[-1], "timestamp")
            data_end_time = last_ts if last_ts.tzinfo else last_ts.replace(tzinfo=timezone.utc)
        elif data_end_time.tzinfo is None:
            data_end_time = data_end_time.replace(tzinfo=timezone.utc)

        # 3. Partition ticks into time buckets [bucket_start, bucket_end)
        # Dict mapping: (symbol, bucket_start, bucket_end) -> list of ticks
        buckets: dict[tuple[str, datetime, datetime], list[Any]] = defaultdict(list)

        for tick in tick_list:
            symbol = str(self._extract_tick_attr(tick, "symbol")).strip().upper()
            ts = self._extract_tick_attr(tick, "timestamp")
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)

            b_start, b_end = get_candle_bucket(ts, self.timeframe)
            buckets[(symbol, b_start, b_end)].append(tick)

        # 4. Generate candles for each bucket
        candles: list[AggregatedCandle] = []

        for (symbol, b_start, b_end), bucket_ticks in sorted(buckets.items(), key=lambda x: x[0][1]):
            # Check closed candle status (Phase 9 & 10)
            # A candle is complete only if the data stream extends to or beyond bucket_end
            is_closed = data_end_time >= b_end

            if self.only_closed and not is_closed:
                # Discard partial uncompleted candle in batch historical mode
                continue

            # Extract OHLC
            prices = [self._get_tick_price(t) for t in bucket_ticks]
            open_price = prices[0]
            close_price = prices[-1]
            high_price = max(prices)
            low_price = min(prices)

            # Volume
            tick_volume = len(bucket_ticks)
            real_vol_sum = 0
            for t in bucket_ticks:
                r_vol = self._extract_tick_attr(t, "real_volume") or self._extract_tick_attr(t, "volume") or 0
                try:
                    real_vol_sum += int(Decimal(str(r_vol)))
                except Exception:
                    pass

            # Spread: arithmetic mean of valid tick spreads
            spreads = [self._get_tick_spread(t) for t in bucket_ticks]
            avg_spread = sum(spreads) / Decimal(len(spreads))

            if self.spread_unit == "pips":
                multiplier = Decimal("100") if symbol.endswith("JPY") else Decimal("10000")
                spread_val = (avg_spread * multiplier).quantize(Decimal("0.01")) if avg_spread < Decimal("1.0") else avg_spread.quantize(Decimal("0.01"))
            else:
                spread_val = avg_spread.quantize(Decimal("0.00001"))

            candle = AggregatedCandle(
                symbol=symbol,
                timeframe=self.timeframe,
                timestamp=b_start,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                tick_volume=tick_volume,
                real_volume=real_vol_sum,
                spread=spread_val,
                is_closed=is_closed,
            )
            candles.append(candle)

        return candles
