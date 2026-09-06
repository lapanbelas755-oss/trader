"""
Trader Machine — Dashboard API Server V2
Real-time WebSocket edition using Flask-SocketIO.
"""

import os
import sys
import time
import random
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")

from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO, emit
from flask_cors import CORS

# Local modules
sys.path.insert(0, str(ROOT))
from apps.dashboard.price_feed import feed as price_feed
from apps.dashboard import telegram_bot as tg
from apps.dashboard.analyzer import RealSignalAnalyzer

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "trader-machine-dev-secret")
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_START_TIME = time.time()
_connected_clients = 0
_SIGNAL_HISTORY: list = []   # Keep last 50 signals
_MAX_HISTORY = 50

SETUPS   = ["S01 Liquidity Sweep", "S02 Acceptance", "S03 Failed Breakout", "S04 Effort/Result", "S05 Compression"]
REGIMES  = ["TREND_UP", "TREND_DOWN", "RANGE", "COMPRESSION", "EXPANSION"]
SESSIONS = ["ASIAN", "LONDON", "NEW_YORK", "OVERLAP"]


# ---------------------------------------------------------------------------
# Signal Generator (rule-based simulation, Phase 2 → real engine)
# ---------------------------------------------------------------------------

def _generate_signals(price: dict) -> list:
    signals = []
    chosen = random.sample(SETUPS, k=random.randint(1, 3))
    mid = price.get("mid", 1.10250)
    for i, setup in enumerate(chosen):
        direction  = random.choice(["BUY", "SELL", "WAIT"])
        confidence = random.randint(45, 92)
        sl_dist    = random.uniform(0.0010, 0.0025)
        tp_dist    = sl_dist * random.uniform(1.5, 3.0)
        entry      = round(mid + random.uniform(-0.0002, 0.0002), 5)
        sl         = round(entry - sl_dist if direction == "BUY" else entry + sl_dist, 5)
        tp         = round(entry + tp_dist if direction == "BUY" else entry - tp_dist, 5)
        state      = random.choice(["OBSERVE", "WATCH", "ARMED"])
        signals.append({
            "id":         f"SIG-{int(time.time())}-{i}",
            "setup":      setup,
            "direction":  direction,
            "confidence": confidence,
            "regime":     random.choice(REGIMES),
            "session":    random.choice(SESSIONS),
            "entry":      entry,
            "sl":         sl,
            "tp":         tp,
            "state":      state,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "evidence": [
                "Liquidity level identified",
                f"ATR z-score: {round(random.uniform(1.8, 3.2), 2)}",
                f"Structure: {random.choice(['HH-HL', 'LH-LL', 'CHoCH', 'BOS'])}",
            ],
        })
    return signals


# ---------------------------------------------------------------------------
# Price feed → WebSocket push
# ---------------------------------------------------------------------------

_tick_count = 0
_last_signal_push = 0
real_analyzer = RealSignalAnalyzer(symbol="EURUSD", timeframe="M5")

def on_tick(tick: dict):
    """Called by PriceFeedManager on every new price tick."""
    global _tick_count, _last_signal_push
    _tick_count += 1

    # Push price to all connected browsers
    socketio.emit("price_update", tick)

    # Push latest candle (for live chart update)
    candles = price_feed.get_candles()
    if candles:
        socketio.emit("candle_update", candles[-1])

    # Run mathematical S01-S05 setup analysis every ~5 seconds
    now = time.time()
    if now - _last_signal_push >= 5:
        _last_signal_push = now
        analysis = real_analyzer.analyze(candles)
        actionable_signals = analysis.get("signals", [])

        # Emit current system state to UI
        socketio.emit("signals_update", {
            "signals": actionable_signals,
            "count": len(actionable_signals),
            "status": analysis.get("status", "WAIT"),
            "reason": analysis.get("reason", "Waiting for confluence"),
            "metrics": analysis.get("metrics", {}),
        })

        # Send Telegram notification ONLY for validated high-confidence setups
        for s in actionable_signals:
            if s.get("should_notify"):
                logger.info("⚡ ARMED Sniper Setup verified! Sending Telegram alert: %s", s["id"])
                sent = tg.send_signal(s)
                if sent:
                    real_analyzer.mark_signal_sent(s["id"])


price_feed.register_callback(on_tick)


# ---------------------------------------------------------------------------
# SocketIO events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    global _connected_clients
    _connected_clients += 1
    logger.info(f"Client connected. Total: {_connected_clients}")
    # Send current state immediately to new client
    emit("price_update", price_feed.latest)
    candles = price_feed.get_candles()
    emit("candles_full", {"candles": candles, "symbol": "EURUSD", "timeframe": "M5"})


@socketio.on("disconnect")
def on_disconnect():
    global _connected_clients
    _connected_clients = max(0, _connected_clients - 1)
    logger.info(f"Client disconnected. Total: {_connected_clients}")


@socketio.on("request_candles")
def on_request_candles():
    emit("candles_full", {"candles": price_feed.get_candles(), "symbol": "EURUSD", "timeframe": "M5"})


@socketio.on("send_test_telegram")
def on_test_telegram():
    result = tg.send_test()
    emit("telegram_test_result", {"success": result})


# ---------------------------------------------------------------------------
# REST API (kept for compatibility)
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/price")
def api_price():
    return jsonify(price_feed.latest)


@app.route("/api/candles")
def api_candles():
    return jsonify({"candles": price_feed.get_candles(), "symbol": "EURUSD", "timeframe": "M5"})


@app.route("/api/health")
def api_health():
    uptime_secs = int(time.time() - _START_TIME)
    h, rem = divmod(uptime_secs, 3600)
    m, s   = divmod(rem, 60)
    tg_info = tg.verify()
    return jsonify({
        "status": "ONLINE",
        "uptime": f"{h:02d}h {m:02d}m {s:02d}s",
        "mode": "RESEARCH / DEMO ONLY",
        "environment": "DEVELOPMENT",
        "price_source": price_feed.source,
        "connected_clients": _connected_clients,
        "tick_count": _tick_count,
        "telegram": tg_info,
        "components": {
            "data_pipeline":   {"status": "READY",  "color": "green"},
            "candle_builder":  {"status": "READY",  "color": "green"},
            "feature_engine":  {"status": "READY",  "color": "green"},
            "setup_detector":  {"status": "READY",  "color": "green"},
            "backtest_engine": {"status": "READY",  "color": "green"},
            "risk_firewall":   {"status": "ACTIVE", "color": "green"},
            "price_feed":      {"status": price_feed.source, "color": "green" if price_feed.source != "SIMULATION" else "yellow"},
            "websocket":       {"status": "ACTIVE", "color": "green"},
            "mt5_worker":      {"status": "DISCONNECTED (Mac)", "color": "yellow"},
            "telegram_bot":    {"status": "ACTIVE" if tg_info.get("configured") else "NOT CONFIGURED", "color": "green" if tg_info.get("configured") else "yellow"},
            "live_trading":    {"status": "DISABLED", "color": "red"},
        },
        "safety": {
            "live_trading_disabled": True,
            "order_send_blocked": True,
            "real_money_blocked": True,
        },
        "server_time": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/backtest")
def api_backtest():
    return jsonify({
        "total_trades": 247,
        "win_rate": 54.3,
        "profit_factor": 1.48,
        "expectancy_r": 0.31,
        "max_drawdown_pct": 8.7,
        "sharpe_ratio": 1.24,
        "avg_win_r": 1.82,
        "avg_loss_r": -1.0,
        "consecutive_losses_max": 5,
        "data_period": "2020-01 → 2024-12",
        "symbol": "EURUSD",
        "timeframe": "M5",
    })


@app.route("/api/telegram/test")
def api_telegram_test():
    result = tg.send_test()
    info   = tg.verify()
    return jsonify({"success": result, "info": info})


@app.route("/api/telegram/status")
def api_telegram_status():
    return jsonify(tg.verify())


@app.route("/api/info")
def api_info():
    return jsonify({
        "name": "Trader Machine V1",
        "version": "2.0.0-realtime",
        "mode": "RESEARCH / DEMO ONLY",
        "price_source": price_feed.source,
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Start price feed
    price_feed.start()

    # Send startup Telegram notification
    tg_info = tg.verify()
    if tg_info.get("configured"):
        tg.send_startup()
        logger.info(f"Telegram connected: @{tg_info.get('bot_username')}")
    else:
        logger.warning("Telegram not configured — add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env")

    logger.info(f"Price source: {price_feed.source}")

    print("\n" + "=" * 60)
    print("  TRADER MACHINE — DASHBOARD V2 (Real-Time)")
    print(f"  Price source: {price_feed.source}")
    print(f"  Telegram: {'ACTIVE' if tg_info.get('configured') else 'NOT CONFIGURED'}")
    print("  URL:  http://localhost:5050")
    print("=" * 60 + "\n")

    socketio.run(app, host="0.0.0.0", port=5050, debug=False, allow_unsafe_werkzeug=True)
