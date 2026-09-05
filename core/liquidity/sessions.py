"""
Deterministic trading session boundaries and level extractor for Liquidity Detector V1.
Strictly timezone-aware (UTC default), DST-safe, with no dependence on local machine timezone.
"""

from datetime import datetime, time, timezone, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass

from core.candles.contract import AggregatedCandle as Candle
from core.liquidity.contract import TradingSession, LiquidityLevelType, LiquidityLevelRecord, LiquidityStatus


@dataclass(frozen=True)
class SessionWindow:
    name: TradingSession
    start_time: time  # UTC
    end_time: time    # UTC


DEFAULT_SESSIONS: Dict[TradingSession, SessionWindow] = {
    TradingSession.ASIA: SessionWindow(TradingSession.ASIA, time(0, 0), time(8, 0)),
    TradingSession.LONDON: SessionWindow(TradingSession.LONDON, time(7, 0), time(15, 30)),
    TradingSession.NEW_YORK: SessionWindow(TradingSession.NEW_YORK, time(12, 0), time(20, 30)),
}


def _get_val(obj, key):
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict) and key in obj:
        return obj[key]
    return getattr(obj, key)


class SessionDetector:
    """
    Identifies sessions and calculates session High/Low levels from candle sequences.
    """

    def __init__(self, sessions: Optional[Dict[TradingSession, SessionWindow]] = None, tz: timezone = timezone.utc):
        self.sessions = sessions or DEFAULT_SESSIONS
        self.tz = tz

    def is_in_session(self, dt: datetime, session: TradingSession) -> bool:
        """
        Check if datetime dt falls within the session window (in UTC).
        Handles windows that do not cross midnight (all defaults here) and windows crossing midnight.
        """
        dt_utc = dt.astimezone(self.tz) if dt.tzinfo else dt.replace(tzinfo=self.tz)
        current_time = dt_utc.time()
        window = self.sessions[session]

        if window.start_time <= window.end_time:
            return window.start_time <= current_time < window.end_time
        else:
            # Over midnight
            return current_time >= window.start_time or current_time < window.end_time

    def extract_session_levels(
        self,
        candles: List[Any],
        session: TradingSession,
        reference_date: datetime.date,
        symbol: str = "EURUSD",
        timeframe: str = "M5",
    ) -> Optional[Tuple[LiquidityLevelRecord, LiquidityLevelRecord]]:
        """
        Extract completed session high and low for a specific session on a given calendar day (UTC).
        Returns None if no candles belong to this session or session is not complete.
        """
        window = self.sessions[session]
        session_candles: List[Any] = []

        for c in candles:
            ts = _get_val(c, "timestamp")
            c_dt = ts.astimezone(self.tz) if ts.tzinfo else ts.replace(tzinfo=self.tz)
            if c_dt.date() == reference_date and self.is_in_session(c_dt, session):
                session_candles.append(c)

        if not session_candles:
            return None

        # Determine highest and lowest
        high_price = max(_get_val(c, "high") for c in session_candles)
        low_price = min(_get_val(c, "low") for c in session_candles)

        # End time of session on reference_date
        session_end_dt = datetime.combine(reference_date, window.end_time, tzinfo=self.tz)

        high_level = LiquidityLevelRecord(
            symbol=symbol,
            timeframe=timeframe,
            level_type=LiquidityLevelType.SESSION_HIGH,
            price=Decimal(str(high_price)),
            created_at=session_end_dt,
            strength=Decimal("1.0000"),
            status=LiquidityStatus.UNTOUCHED,
            session=session.value,
        )

        low_level = LiquidityLevelRecord(
            symbol=symbol,
            timeframe=timeframe,
            level_type=LiquidityLevelType.SESSION_LOW,
            price=Decimal(str(low_price)),
            created_at=session_end_dt,
            strength=Decimal("1.0000"),
            status=LiquidityStatus.UNTOUCHED,
            session=session.value,
        )

        return high_level, low_level
