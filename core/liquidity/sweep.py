"""
Deterministic liquidity sweep detection for Liquidity Engine V1.
Strictly checks penetration depth bounds [0.05 * ATR, 0.50 * ATR] and return across level within max 3 candles.
Does NOT interpret sweep as automatic reversal.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple, Any

from core.candles.contract import AggregatedCandle as Candle
from core.liquidity.contract import (
    LiquidityLevelRecord,
    LiquidityLevelType,
    LiquidityStatus,
    SweepEvent,
)


def _get_val(obj, key):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict) and key in obj:
        return obj[key]
    return getattr(obj, key)


class SweepDetector:
    """
    Evaluates whether candles produce a valid liquidity sweep against an active level.
    """

    def __init__(
        self,
        min_sweep_atr_mult: Decimal = Decimal("0.05"),
        max_sweep_atr_mult: Decimal = Decimal("0.50"),
        fallback_atr: Decimal = Decimal("0.00100"),
        max_return_bars: int = 3,
    ):
        self.min_sweep_atr_mult = min_sweep_atr_mult
        self.max_sweep_atr_mult = max_sweep_atr_mult
        self.fallback_atr = fallback_atr
        self.max_return_bars = max_return_bars

    def is_high_type(self, level_type: LiquidityLevelType) -> bool:
        return level_type in (
            LiquidityLevelType.PREVIOUS_DAY_HIGH,
            LiquidityLevelType.PREVIOUS_WEEK_HIGH,
            LiquidityLevelType.SESSION_HIGH,
            LiquidityLevelType.EQUAL_HIGH,
            LiquidityLevelType.SIGNIFICANT_SWING_HIGH,
        )

    def evaluate_sweep(
        self,
        level: LiquidityLevelRecord,
        candles: List[Any],
        start_index: int,
        atr_value: Optional[Decimal] = None,
    ) -> Optional[SweepEvent]:
        """
        Evaluate candles starting at start_index (the candle that penetrates the level).
        Checks if penetration depth is within [0.05 * ATR, 0.50 * ATR] and price returns
        across the level within max_return_bars.
        """
        atr = atr_value if atr_value is not None and atr_value > Decimal("0") else self.fallback_atr
        min_depth = self.min_sweep_atr_mult * atr
        max_depth = self.max_sweep_atr_mult * atr

        level_price = level.price
        is_high = self.is_high_type(level.level_type)

        first_candle = candles[start_index]

        if is_high:
            # Must penetrate high level
            first_high = Decimal(str(_get_val(first_candle, "high")))
            penetration = first_high - level_price
            if penetration < min_depth or penetration > max_depth:
                return None

            sweep_extreme = first_high
            sweep_depth = penetration
            sweep_ts = _get_val(first_candle, "timestamp")

            # Check for return across level (price closes or trades back below level_price)
            # within max_return_bars (starting from start_index)
            end_idx = min(start_index + self.max_return_bars + 1, len(candles))
            for i in range(start_index, end_idx):
                c = candles[i]
                c_high = Decimal(str(_get_val(c, "high")))
                if c_high > sweep_extreme:
                    sweep_extreme = c_high
                    sweep_depth = sweep_extreme - level_price
                    # If deeper than max allowed depth, invalidated as a clean sweep
                    if sweep_depth > max_depth:
                        return None

                # Return condition: candle closes back below level_price
                if Decimal(str(_get_val(c, "close"))) < level_price:
                    return SweepEvent(
                        symbol=level.symbol,
                        level_id=level.id,
                        level_type=level.level_type,
                        level_price=level_price,
                        sweep_direction="HIGH_SWEPT",
                        sweep_timestamp=sweep_ts,
                        sweep_extreme=sweep_extreme,
                        sweep_depth=sweep_depth,
                        return_timestamp=_get_val(c, "timestamp"),
                    )

        else:
            # Must penetrate low level
            first_low = Decimal(str(_get_val(first_candle, "low")))
            penetration = level_price - first_low
            if penetration < min_depth or penetration > max_depth:
                return None

            sweep_extreme = first_low
            sweep_depth = penetration
            sweep_ts = _get_val(first_candle, "timestamp")

            end_idx = min(start_index + self.max_return_bars + 1, len(candles))
            for i in range(start_index, end_idx):
                c = candles[i]
                c_low = Decimal(str(_get_val(c, "low")))
                if c_low < sweep_extreme:
                    sweep_extreme = c_low
                    sweep_depth = level_price - sweep_extreme
                    if sweep_depth > max_depth:
                        return None

                # Return condition: candle closes back above level_price
                if Decimal(str(_get_val(c, "close"))) > level_price:
                    return SweepEvent(
                        symbol=level.symbol,
                        level_id=level.id,
                        level_type=level.level_type,
                        level_price=level_price,
                        sweep_direction="LOW_SWEPT",
                        sweep_timestamp=sweep_ts,
                        sweep_extreme=sweep_extreme,
                        sweep_depth=sweep_depth,
                        return_timestamp=_get_val(c, "timestamp"),
                    )

        return None
