"""Fractal swing detection with mandatory confirmation delay (Causality Enforcement)."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence
from core.structure.contract import ConfirmedSwing, SwingType

class SwingDetector:
    """Detects swing highs and swing lows based on left_bars and right_bars fractals."""

    def __init__(self, left_bars: int = 2, right_bars: int = 2):
        self.left_bars = left_bars
        self.right_bars = right_bars

    def _get_attr(self, obj: Any, attr: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(attr)
        return getattr(obj, attr, None)

    def detect_swings(self, candles: Sequence[Any]) -> list[ConfirmedSwing]:
        """
        Detects fractal swings across a sequence of closed candles.
        A swing at index t is ONLY confirmed at index t + right_bars.
        """
        candle_list = list(candles)
        n = len(candle_list)
        if n < self.left_bars + self.right_bars + 1:
            return []

        def get_ts(c: Any) -> datetime:
            t = self._get_attr(c, "timestamp")
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

        candle_list.sort(key=get_ts)

        swings: list[ConfirmedSwing] = []

        # Iterate from left_bars to n - 1 - right_bars
        for t in range(self.left_bars, n - self.right_bars):
            curr_c = candle_list[t]
            symbol = str(self._get_attr(curr_c, "symbol")).strip().upper()
            timeframe = str(self._get_attr(curr_c, "timeframe")).strip().upper()
            curr_ts = get_ts(curr_c)
            curr_high = Decimal(str(self._get_attr(curr_c, "high")))
            curr_low = Decimal(str(self._get_attr(curr_c, "low")))

            confirm_candle = candle_list[t + self.right_bars]
            confirmed_at = get_ts(confirm_candle)

            # 1. Swing High Check
            is_swing_high = True
            for offset in range(1, self.left_bars + 1):
                if Decimal(str(self._get_attr(candle_list[t - offset], "high"))) >= curr_high:
                    is_swing_high = False
                    break

            if is_swing_high:
                for offset in range(1, self.right_bars + 1):
                    if Decimal(str(self._get_attr(candle_list[t + offset], "high"))) >= curr_high:
                        is_swing_high = False
                        break

            if is_swing_high:
                ts_str = curr_ts.strftime("%Y%m%d%H%M%S")
                swing_id = f"SW_{symbol}_{timeframe}_H_{ts_str}"
                swings.append(ConfirmedSwing(
                    swing_id=swing_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    swing_type=SwingType.SWING_HIGH,
                    price=curr_high,
                    timestamp=curr_ts,
                    confirmed_at=confirmed_at,
                ))

            # 2. Swing Low Check
            is_swing_low = True
            for offset in range(1, self.left_bars + 1):
                if Decimal(str(self._get_attr(candle_list[t - offset], "low"))) <= curr_low:
                    is_swing_low = False
                    break

            if is_swing_low:
                for offset in range(1, self.right_bars + 1):
                    if Decimal(str(self._get_attr(candle_list[t + offset], "low"))) <= curr_low:
                        is_swing_low = False
                        break

            if is_swing_low:
                ts_str = curr_ts.strftime("%Y%m%d%H%M%S")
                swing_id = f"SW_{symbol}_{timeframe}_L_{ts_str}"
                swings.append(ConfirmedSwing(
                    swing_id=swing_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    swing_type=SwingType.SWING_LOW,
                    price=curr_low,
                    timestamp=curr_ts,
                    confirmed_at=confirmed_at,
                ))

        # Order strictly by confirmed_at ASC, timestamp ASC
        swings.sort(key=lambda s: (s.confirmed_at, s.timestamp))
        return swings
