"""
Unit tests for market_hours.py to verify market open/close detection.
"""

from datetime import datetime, timezone
import pytest
from apps.dashboard.market_hours import is_forex_market_open, get_market_status


def test_market_hours_saturday():
    # Saturday 12:00 UTC -> Closed
    sat_dt = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    assert not is_forex_market_open(sat_dt)
    is_open, msg = get_market_status(sat_dt)
    assert not is_open
    assert "Saturday" in msg


def test_market_hours_sunday_morning():
    # Sunday 07:18 UTC (user's alert time) -> Closed
    sun_morning = datetime(2026, 9, 6, 7, 18, 0, tzinfo=timezone.utc)
    assert not is_forex_market_open(sun_morning)
    is_open, msg = get_market_status(sun_morning)
    assert not is_open
    assert "Sunday" in msg


def test_market_hours_sunday_evening():
    # Sunday 21:05 UTC -> Open
    sun_evening = datetime(2026, 9, 6, 21, 5, 0, tzinfo=timezone.utc)
    assert is_forex_market_open(sun_evening)
    is_open, msg = get_market_status(sun_evening)
    assert is_open
    assert "OPEN" in msg


def test_market_hours_weekday():
    # Wednesday 14:30 UTC -> Open
    wed = datetime(2026, 9, 2, 14, 30, 0, tzinfo=timezone.utc)
    assert is_forex_market_open(wed)
    is_open, msg = get_market_status(wed)
    assert is_open
    assert "EUROPEAN" in msg


def test_market_hours_friday_night():
    # Friday 21:30 UTC -> Open
    fri_open = datetime(2026, 9, 4, 21, 30, 0, tzinfo=timezone.utc)
    assert is_forex_market_open(fri_open)

    # Friday 22:30 UTC -> Closed
    fri_closed = datetime(2026, 9, 4, 22, 30, 0, tzinfo=timezone.utc)
    assert not is_forex_market_open(fri_closed)
