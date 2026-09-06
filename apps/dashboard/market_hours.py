"""
Trader Machine — Forex Market Hours & Session Engine
Tracks market open/close times according to global Forex conventions.

Forex Market Trading Schedule:
- Global open: Sunday 21:00 UTC (Sydney open) / 17:00 EST
- Global close: Friday 22:00 UTC (New York close) / 17:00 EST
- Weekend closure: Friday 22:00 UTC to Sunday 21:00 UTC
"""

from datetime import datetime, timezone
from typing import Optional, Tuple


def is_forex_market_open(dt: Optional[datetime] = None) -> bool:
    """
    Returns True if the global Forex market is currently open for trading.
    Returns False during the weekend closure (Fri 22:00 UTC to Sun 21:00 UTC).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    weekday = dt.weekday()  # Monday is 0, Sunday is 6
    hour = dt.hour

    # Saturday: completely closed all 24 hours
    if weekday == 5:
        return False

    # Sunday: closed until 21:00 UTC
    if weekday == 6:
        return hour >= 21

    # Friday: open until 22:00 UTC
    if weekday == 4:
        return hour < 22

    # Monday through Thursday: open 24 hours
    return True


def get_market_status(dt: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Returns (is_open: bool, status_message: str).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    open_status = is_forex_market_open(dt)
    if open_status:
        hour = dt.hour
        if 0 <= hour < 8:
            session = "ASIAN (Tokyo/Sydney)"
        elif 8 <= hour < 16:
            session = "EUROPEAN (London)"
        elif 16 <= hour < 22:
            session = "US (New York)"
        else:
            session = "ASIAN/PACIFIC OPEN"
        return True, f"Market OPEN — {session} Session"
    else:
        weekday = dt.weekday()
        if weekday == 5:
            msg = "Market CLOSED (Saturday Weekend — Opens Sun 21:00 UTC)"
        elif weekday == 6:
            remaining_hours = max(0, 21 - dt.hour)
            msg = f"Market CLOSED (Sunday Weekend — Opens in ~{remaining_hours}h at 21:00 UTC)"
        else:
            msg = "Market CLOSED (Friday Weekend Close)"
        return False, msg
