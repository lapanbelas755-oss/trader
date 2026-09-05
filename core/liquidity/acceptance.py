"""
Deterministic Rejection and Acceptance detectors for Liquidity Engine V1.
Rejection: price sweeps, returns, and displaces >= 0.30 * ATR away from level.
Acceptance: min 2 closed candles beyond level AND follow-through displacement >= 0.30 * ATR.
Immediate return through level invalidates acceptance.
"""

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


class AcceptanceRejectionDetector:
    """
    Evaluates whether an approached/touched/swept level achieves REJECTION, ACCEPTANCE, or INVALIDATION.
    """

    def __init__(
        self,
        rejection_atr_mult: Decimal = Decimal("0.30"),
        acceptance_atr_mult: Decimal = Decimal("0.30"),
        acceptance_min_candles: int = 2,
        fallback_atr: Decimal = Decimal("0.00100"),
    ):
        self.rejection_atr_mult = rejection_atr_mult
        self.acceptance_atr_mult = acceptance_atr_mult
        self.acceptance_min_candles = acceptance_min_candles
        self.fallback_atr = fallback_atr

    def is_high_type(self, level_type: LiquidityLevelType) -> bool:
        return level_type in (
            LiquidityLevelType.PREVIOUS_DAY_HIGH,
            LiquidityLevelType.PREVIOUS_WEEK_HIGH,
            LiquidityLevelType.SESSION_HIGH,
            LiquidityLevelType.EQUAL_HIGH,
            LiquidityLevelType.SIGNIFICANT_SWING_HIGH,
        )

    def evaluate_rejection(
        self,
        level: LiquidityLevelRecord,
        sweep_event: SweepEvent,
        subsequent_candles: List[Any],
        atr_value: Optional[Decimal] = None,
    ) -> Tuple[bool, Optional[Decimal], Optional[Any]]:
        """
        After sweep return, check if price demonstrates meaningful displacement away from the level.
        Displacement >= 0.30 * ATR.
        Returns (is_rejected, displacement, rejecting_candle).
        """
        atr = atr_value if atr_value is not None and atr_value > Decimal("0") else self.fallback_atr
        threshold = self.rejection_atr_mult * atr
        level_price = level.price
        is_high = self.is_high_type(level.level_type)

        for c in subsequent_candles:
            close_price = Decimal(str(_get_val(c, "close")))
            if is_high:
                # Displacing downwards away from high level
                displacement = level_price - close_price
                if displacement >= threshold:
                    return True, displacement, c
            else:
                # Displacing upwards away from low level
                displacement = close_price - level_price
                if displacement >= threshold:
                    return True, displacement, c

        return False, None, None

    def evaluate_acceptance(
        self,
        level: LiquidityLevelRecord,
        candles_from_breakout: List[Any],
        atr_value: Optional[Decimal] = None,
    ) -> Tuple[bool, Optional[Decimal], Optional[Any]]:
        """
        Check for acceptance beyond a broken level:
        1. Minimum 2 closed candles maintaining the breakout side.
        2. Follow-through displacement >= 0.30 * ATR beyond the level.
        3. If any candle closes back across the level, acceptance is invalidated.
        Returns (is_accepted, displacement, accepting_candle).
        """
        if len(candles_from_breakout) < self.acceptance_min_candles:
            return False, None, None

        atr = atr_value if atr_value is not None and atr_value > Decimal("0") else self.fallback_atr
        threshold = self.acceptance_atr_mult * atr
        level_price = level.price
        is_high = self.is_high_type(level.level_type)

        consecutive_outside = 0
        max_displacement = Decimal("0")

        for c in candles_from_breakout:
            c_close = Decimal(str(_get_val(c, "close")))

            if is_high:
                if c_close <= level_price:
                    # Immediate return across level invalidates acceptance
                    return False, None, None
                consecutive_outside += 1
                disp = c_close - level_price
                if disp > max_displacement:
                    max_displacement = disp

                if consecutive_outside >= self.acceptance_min_candles and max_displacement >= threshold:
                    return True, max_displacement, c
            else:
                if c_close >= level_price:
                    # Immediate return across level invalidates acceptance
                    return False, None, None
                consecutive_outside += 1
                disp = level_price - c_close
                if disp > max_displacement:
                    max_displacement = disp

                if consecutive_outside >= self.acceptance_min_candles and max_displacement >= threshold:
                    return True, max_displacement, c

        return False, None, None
