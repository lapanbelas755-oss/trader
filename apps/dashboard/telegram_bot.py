"""
Trader Machine — Telegram Notification Bot
Sends trading signals and system alerts to a Telegram chat.

Configuration (via .env):
  TELEGRAM_BOT_TOKEN  = 123456789:ABCdef...
  TELEGRAM_CHAT_ID    = -100123456789   (group) or 123456789 (private)
"""

import os
import logging
import threading
from datetime import datetime, timezone
from typing import Optional
import requests

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

_BASE_URL = f"https://api.telegram.org/bot{{}}/sendMessage"
_lock = threading.Lock()


def _is_configured() -> bool:
    return bool(BOT_TOKEN and CHAT_ID)


def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message to the configured Telegram chat."""
    if not _is_configured():
        logger.warning("Telegram not configured — skipping notification")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        with _lock:
            resp = requests.post(
                url,
                json={
                    "chat_id": CHAT_ID,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=8,
            )
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Telegram API error: {data}")
            return False
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def send_signal(signal: dict) -> bool:
    """Send a formatted trading signal notification."""
    direction = signal.get("direction", "WAIT")
    setup     = signal.get("setup", "Unknown")
    confidence= signal.get("confidence", 0)
    regime    = signal.get("regime", "UNKNOWN")
    session   = signal.get("session", "UNKNOWN")
    state     = signal.get("state", "WATCH")
    entry     = signal.get("entry", 0)
    sl        = signal.get("sl", 0)
    tp        = signal.get("tp", 0)

    dir_emoji = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡"}.get(direction, "⚪")
    state_emoji = {"ARMED": "🎯", "WATCH": "👁", "OBSERVE": "🔍", "FIRE": "🔥"}.get(state, "⏳")

    sl_pips  = round(abs(entry - sl) * 10000, 1) if entry and sl else 0
    tp_pips  = round(abs(tp - entry) * 10000, 1) if entry and tp else 0

    text = (
        f"<b>⚡ TRADER MACHINE SIGNAL</b>\n"
        f"{'─' * 28}\n"
        f"📊 <b>EUR/USD</b>\n"
        f"{dir_emoji} <b>Direction: {direction}</b>\n"
        f"{state_emoji} State: <code>{state}</code>\n"
        f"\n"
        f"📍 Entry:  <code>{entry:.5f}</code>\n"
        f"🛑 SL:     <code>{sl:.5f}</code> ({sl_pips} pips)\n"
        f"🎯 TP:     <code>{tp:.5f}</code> ({tp_pips} pips)\n"
        f"\n"
        f"📈 Setup:      {setup}\n"
        f"🌍 Regime:     <code>{regime}</code>\n"
        f"⏰ Session:    <code>{session}</code>\n"
        f"🔥 Confidence: <b>{confidence}%</b>\n"
        f"\n"
        f"{'─' * 28}\n"
        f"⚠️ <i>RESEARCH MODE ONLY — No real execution</i>\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )
    return _send(text)


def send_alert(level: str, message: str) -> bool:
    """Send a system alert."""
    emoji = {"INFO": "ℹ️", "WARN": "⚠️", "ERROR": "🚨", "SIGNAL": "🎯"}.get(level, "📢")
    text = (
        f"{emoji} <b>TRADER MACHINE — {level}</b>\n"
        f"{'─' * 28}\n"
        f"{message}\n"
        f"{'─' * 28}\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
    )
    return _send(text)


def send_startup() -> bool:
    """Send a startup notification."""
    text = (
        f"🚀 <b>TRADER MACHINE ONLINE</b>\n"
        f"{'─' * 28}\n"
        f"📊 Symbol:  <code>EURUSD</code>\n"
        f"⏰ TF:      <code>M5</code>\n"
        f"🔬 Mode:    <code>RESEARCH / DEMO ONLY</code>\n"
        f"🛡️ Trading: <code>DISABLED</code>\n"
        f"{'─' * 28}\n"
        f"✅ All systems operational\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )
    return _send(text)


def send_test() -> bool:
    """Send a test message to verify connectivity."""
    text = (
        f"✅ <b>TRADER MACHINE — Connection Test</b>\n\n"
        f"Telegram bot is working correctly!\n"
        f"You will receive signal notifications here.\n\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC"
    )
    return _send(text)


def verify() -> dict:
    """Verify Telegram configuration and connectivity."""
    if not _is_configured():
        return {
            "configured": False,
            "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env",
        }
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if data.get("ok"):
            bot = data["result"]
            return {
                "configured": True,
                "bot_username": bot.get("username"),
                "bot_name": bot.get("first_name"),
                "chat_id": CHAT_ID,
            }
        return {"configured": False, "error": data.get("description", "Unknown")}
    except Exception as e:
        return {"configured": False, "error": str(e)}
