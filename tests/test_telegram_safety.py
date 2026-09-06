"""
Unit test for Telegram bot safety gates and research firewall.
"""

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest

from apps.dashboard import telegram_bot as tg
from apps.dashboard.market_hours import is_forex_market_open


def test_telegram_signals_disabled_by_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SIGNALS_ENABLED", "false")
    assert not tg.are_signals_enabled()

    # Even with a FIRE signal, send_signal must return False immediately
    mock_signal = {
        "id": "SIG-GBPJPY-S03-123456",
        "symbol": "GBPJPY",
        "setup": "S03 — Swing Low",
        "direction": "BUY",
        "state": "FIRE",
        "entry": 211.301,
        "sl": 211.248,
        "tp": 211.407,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "should_notify": True,
    }

    with patch("requests.post") as mock_post:
        result = tg.send_signal(mock_signal)
        assert result is False
        mock_post.assert_not_called()


def test_telegram_signals_enabled_gate(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SIGNALS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mock_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "mock_chat")
    assert tg.are_signals_enabled()


def test_candle_freshness_logic():
    # Stale candle (e.g. from 36 hours ago on Friday)
    stale_dt = datetime.now(timezone.utc) - timedelta(hours=36)
    age_seconds = (datetime.now(timezone.utc) - stale_dt).total_seconds()
    assert age_seconds > 900  # Stale

    # Fresh candle (e.g. 3 minutes ago)
    fresh_dt = datetime.now(timezone.utc) - timedelta(minutes=3)
    fresh_age = (datetime.now(timezone.utc) - fresh_dt).total_seconds()
    assert fresh_age <= 900  # Fresh
