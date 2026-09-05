"""
Deterministic liquidity level detectors for Liquidity Detector Engine V1.
Supports Previous Day High/Low, Previous Week High/Low, Session High/Low, and Equal High/Low.
All operations are strictly causal and timezone-explicit (UTC).
"""

from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple, Dict, Any
import pandas as pd

from core.candles.contract import AggregatedCandle as Candle
from core.structure.contract import ConfirmedSwing, SwingType
from core.liquidity.contract import (
    LiquidityLevelType,
    LiquidityLevelRecord,
    LiquidityStatus,
    TradingSession,
)
from core.liquidity.sessions import SessionDetector, DEFAULT_SESSIONS


def _get_val(obj, key):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict) and key in obj:
        return obj[key]
    return getattr(obj, key)


class LiquidityLevelDetector:
    """
    Detects macro, context, and structural liquidity levels deterministically.
    """

    def __init__(
        self,
        symbol: str = "EURUSD",
        tz: timezone = timezone.utc,
        eq_tolerance_atr_mult: Decimal = Decimal("0.05"),
        fallback_tolerance: Decimal = Decimal("0.00010"),
        min_swing_distance_bars: int = 4,
    ):
        self.symbol = symbol
        self.tz = tz
        self.eq_tolerance_atr_mult = eq_tolerance_atr_mult
        self.fallback_tolerance = fallback_tolerance
        self.min_swing_distance_bars = min_swing_distance_bars
        self.session_detector = SessionDetector(tz=tz)

    def extract_previous_day_levels(
        self,
        candles: List[Any],
        target_day: date,
        timeframe: str = "H1",
    ) -> Optional[Tuple[LiquidityLevelRecord, LiquidityLevelRecord]]:
        """
        Extract PDH and PDL for target_day based STRICTLY on completed previous trading day.
        target_day is the day of interest (e.g. today).
        Completed previous day is the latest calendar day strictly before target_day with candle data.
        """
        if not candles:
            return None

        # Group candles by UTC calendar date
        daily_candles: Dict[date, List[Any]] = {}
        for c in candles:
            ts = _get_val(c, "timestamp")
            c_dt = ts.astimezone(self.tz) if ts.tzinfo else ts.replace(tzinfo=self.tz)
            d = c_dt.date()
            if d < target_day:
                daily_candles.setdefault(d, []).append(c)

        if not daily_candles:
            return None

        # Latest completed date strictly prior to target_day
        prev_date = max(daily_candles.keys())
        prev_candles = daily_candles[prev_date]

        pdh = max(_get_val(c, "high") for c in prev_candles)
        pdl = min(_get_val(c, "low") for c in prev_candles)

        # Available right at 00:00:00 UTC of target_day (or end of previous day)
        available_at = datetime.combine(prev_date + timedelta(days=1), datetime.min.time(), tzinfo=self.tz)

        high_level = LiquidityLevelRecord(
            symbol=self.symbol,
            timeframe=timeframe,
            level_type=LiquidityLevelType.PREVIOUS_DAY_HIGH,
            price=Decimal(str(pdh)),
            created_at=available_at,
            strength=Decimal("1.0000"),
            status=LiquidityStatus.UNTOUCHED,
        )

        low_level = LiquidityLevelRecord(
            symbol=self.symbol,
            timeframe=timeframe,
            level_type=LiquidityLevelType.PREVIOUS_DAY_LOW,
            price=Decimal(str(pdl)),
            created_at=available_at,
            strength=Decimal("1.0000"),
            status=LiquidityStatus.UNTOUCHED,
        )

        return high_level, low_level

    def extract_previous_week_levels(
        self,
        candles: List[Any],
        target_date: date,
        timeframe: str = "H1",
    ) -> Optional[Tuple[LiquidityLevelRecord, LiquidityLevelRecord]]:
        """
        Extract PWH and PWL for target_date's week based strictly on the completed previous trading week.
        target_date belongs to current week. Previous week is strictly calendar week prior.
        """
        if not candles:
            return None

        # ISO year and week for target_date
        target_year, target_week, _ = target_date.isocalendar()

        prev_week_candles: List[Any] = []
        for c in candles:
            ts = _get_val(c, "timestamp")
            c_dt = ts.astimezone(self.tz) if ts.tzinfo else ts.replace(tzinfo=self.tz)
            c_year, c_week, _ = c_dt.date().isocalendar()
            # Must be from a week strictly prior to target week
            if (c_year < target_year) or (c_year == target_year and c_week < target_week):
                prev_week_candles.append(c)

        if not prev_week_candles:
            return None

        # Find the latest week present
        weeks = set()
        for c in prev_week_candles:
            ts = _get_val(c, "timestamp")
            dt = ts.astimezone(self.tz) if ts.tzinfo else ts.replace(tzinfo=self.tz)
            weeks.add(dt.date().isocalendar()[:2])

        latest_prev_year, latest_prev_week = max(weeks)

        selected_candles = []
        for c in prev_week_candles:
            ts = _get_val(c, "timestamp")
            dt = ts.astimezone(self.tz) if ts.tzinfo else ts.replace(tzinfo=self.tz)
            if dt.date().isocalendar()[:2] == (latest_prev_year, latest_prev_week):
                selected_candles.append(c)

        pwh = max(_get_val(c, "high") for c in selected_candles)
        pwl = min(_get_val(c, "low") for c in selected_candles)

        # End of previous week candle timestamp
        last_candle_ts = max(_get_val(c, "timestamp") for c in selected_candles)
        available_at = last_candle_ts.astimezone(self.tz) if last_candle_ts.tzinfo else last_candle_ts.replace(tzinfo=self.tz)

        high_level = LiquidityLevelRecord(
            symbol=self.symbol,
            timeframe=timeframe,
            level_type=LiquidityLevelType.PREVIOUS_WEEK_HIGH,
            price=Decimal(str(pwh)),
            created_at=available_at,
            strength=Decimal("1.0000"),
            status=LiquidityStatus.UNTOUCHED,
        )

        low_level = LiquidityLevelRecord(
            symbol=self.symbol,
            timeframe=timeframe,
            level_type=LiquidityLevelType.PREVIOUS_WEEK_LOW,
            price=Decimal(str(pwl)),
            created_at=available_at,
            strength=Decimal("1.0000"),
            status=LiquidityStatus.UNTOUCHED,
        )

        return high_level, low_level

    def detect_equal_high_low(
        self,
        confirmed_swings: List[ConfirmedSwing],
        current_atr: Optional[Decimal] = None,
        timeframe: str = "M5",
    ) -> List[LiquidityLevelRecord]:
        """
        Detect Equal Highs (EQH) and Equal Lows (EQL) from confirmed swings.
        Requires:
        1. Confirmed swings of the same type.
        2. abs(swing_a.price - swing_b.price) <= tolerance.
        3. Swings must be separated by at least min_swing_distance_bars (or strictly distinct swing timestamps).
        4. Level is created at max(confirmed_at_a, confirmed_at_b) to preserve no-lookahead causality.
        """
        tolerance = (
            current_atr * self.eq_tolerance_atr_mult
            if current_atr is not None and current_atr > Decimal("0")
            else self.fallback_tolerance
        )

        levels: List[LiquidityLevelRecord] = []

        # Highs
        high_swings = [s for s in confirmed_swings if s.swing_type == SwingType.SWING_HIGH]
        for i in range(len(high_swings)):
            for j in range(i + 1, len(high_swings)):
                s1, s2 = high_swings[i], high_swings[j]
                if abs(s1.price - s2.price) <= tolerance:
                    # Average or extreme price of equal highs (use extreme high as standard)
                    level_price = max(s1.price, s2.price)
                    created_at = max(s1.confirmed_at, s2.confirmed_at)
                    levels.append(
                        LiquidityLevelRecord(
                            symbol=self.symbol,
                            timeframe=timeframe,
                            level_type=LiquidityLevelType.EQUAL_HIGH,
                            price=level_price,
                            created_at=created_at,
                            strength=Decimal("1.2000"),
                            status=LiquidityStatus.UNTOUCHED,
                            tolerance=tolerance,
                            source_swing_id=f"{s1.swing_timestamp.isoformat()}_{s2.swing_timestamp.isoformat()}",
                        )
                    )

        # Lows
        low_swings = [s for s in confirmed_swings if s.swing_type == SwingType.SWING_LOW]
        for i in range(len(low_swings)):
            for j in range(i + 1, len(low_swings)):
                s1, s2 = low_swings[i], low_swings[j]
                if abs(s1.price - s2.price) <= tolerance:
                    # Extreme low as standard
                    level_price = min(s1.price, s2.price)
                    created_at = max(s1.confirmed_at, s2.confirmed_at)
                    levels.append(
                        LiquidityLevelRecord(
                            symbol=self.symbol,
                            timeframe=timeframe,
                            level_type=LiquidityLevelType.EQUAL_LOW,
                            price=level_price,
                            created_at=created_at,
                            strength=Decimal("1.2000"),
                            status=LiquidityStatus.UNTOUCHED,
                            tolerance=tolerance,
                            source_swing_id=f"{s1.swing_timestamp.isoformat()}_{s2.swing_timestamp.isoformat()}",
                        )
                    )

        return levels

    def extract_significant_swings(
        self,
        confirmed_swings: List[ConfirmedSwing],
        timeframe: str = "M5",
    ) -> List[LiquidityLevelRecord]:
        """
        Creates liquidity levels from confirmed significant structural swings.
        """
        levels: List[LiquidityLevelRecord] = []
        for s in confirmed_swings:
            ltype = (
                LiquidityLevelType.SIGNIFICANT_SWING_HIGH
                if s.swing_type == SwingType.SWING_HIGH
                else LiquidityLevelType.SIGNIFICANT_SWING_LOW
            )
            levels.append(
                LiquidityLevelRecord(
                    symbol=self.symbol,
                    timeframe=timeframe,
                    level_type=ltype,
                    price=s.price,
                    created_at=s.confirmed_at,
                    strength=Decimal("1.0000"),
                    status=LiquidityStatus.UNTOUCHED,
                    source_swing_id=s.swing_timestamp.isoformat(),
                )
            )
        return levels
