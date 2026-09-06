"""
Trader Machine — Dashboard API Server V3
Real-time WebSocket edition with multi-symbol support.
All signals are mathematically derived — zero random/simulated outputs.
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS

# Local modules
sys.path.insert(0, str(ROOT))
from apps.dashboard.price_feed import feed as price_feed, TRACKED_SYMBOLS
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
_START_TIME       = time.time()
_connected_clients = 0
_tick_counts: dict = {sym: 0 for sym in TRACKED_SYMBOLS}
_last_signal_push: dict = {sym: 0.0 for sym in TRACKED_SYMBOLS}
_last_signal_push_lock = threading.Lock()

# Per-symbol RealSignalAnalyzer — ZERO random signals, purely mathematical
_analyzers: dict = {
    sym: RealSignalAnalyzer(symbol=sym, timeframe="M5")
    for sym in TRACKED_SYMBOLS
}


# ---------------------------------------------------------------------------
# Per-symbol tick handler
# ---------------------------------------------------------------------------

def _make_on_tick(symbol: str):
    """Factory that returns a tick callback bound to a specific symbol."""
    analyzer = _analyzers[symbol]

    def on_tick(tick: dict):
        global _tick_counts
        _tick_counts[symbol] = _tick_counts.get(symbol, 0) + 1

        # Push price tick to all connected browsers
        socketio.emit("price_update", tick)

        # Push latest candle for live chart update
        sym_feed = price_feed.get_feed(symbol)
        if sym_feed:
            candles = sym_feed.get_candles()
            if candles:
                socketio.emit("candle_update", {
                    "symbol": symbol,
                    "candle": candles[-1],
                })

        # Run S01-S05 analysis every ~5 seconds per symbol
        now = time.time()
        with _last_signal_push_lock:
            last = _last_signal_push.get(symbol, 0.0)
            if now - last < 5.0:
                return
            _last_signal_push[symbol] = now

        candles = sym_feed.get_candles() if sym_feed else []
        analysis = analyzer.analyze(candles)
        actionable_signals = analysis.get("signals", [])

        # Emit current system state to UI
        socketio.emit("signals_update", {
            "symbol":  symbol,
            "signals": actionable_signals,
            "count":   len(actionable_signals),
            "status":  analysis.get("status", "WAIT"),
            "reason":  analysis.get("reason", "Waiting for confluence"),
            "metrics": analysis.get("metrics", {}),
        })

        # Send Telegram ONLY for validated high-confidence ARMED/FIRE setups on REAL OBSERVED data
        feed_source = sym_feed.source if sym_feed else "UNKNOWN"
        for s in actionable_signals:
            # STRICT SAFETY FIREWALL (AGENTS.MD Law #2, Law #10, Law #20):
            # Absolutely block Telegram notifications if underlying price feed is SIMULATION!
            if feed_source == "SIMULATION":
                logger.debug("🛡️ Telegram alert BLOCKED for %s: Source is SIMULATION (real data required)", s["id"])
                continue

            if s.get("should_notify"):
                logger.info("⚡ ARMED/FIRE setup verified on REAL market data (%s)! Sending Telegram: %s", feed_source, s["id"])
                sent = tg.send_signal(s)
                if sent:
                    analyzer.mark_signal_sent(s["id"])

    return on_tick


# Register per-symbol callbacks
for _sym in TRACKED_SYMBOLS:
    price_feed.register_callback(_sym, _make_on_tick(_sym))


# ---------------------------------------------------------------------------
# SocketIO events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    global _connected_clients
    _connected_clients += 1
    logger.info(f"Client connected. Total: {_connected_clients}")
    # Send current state for default symbol immediately
    emit("price_update", price_feed.latest)
    default_feed = price_feed.get_feed(TRACKED_SYMBOLS[0])
    if default_feed:
        candles = default_feed.get_candles()
        emit("candles_full", {
            "candles":   candles,
            "symbol":    TRACKED_SYMBOLS[0],
            "timeframe": "M5",
        })


@socketio.on("disconnect")
def on_disconnect():
    global _connected_clients
    _connected_clients = max(0, _connected_clients - 1)
    logger.info(f"Client disconnected. Total: {_connected_clients}")


@socketio.on("request_candles")
def on_request_candles(data=None):
    symbol = (data or {}).get("symbol", TRACKED_SYMBOLS[0])
    sym_feed = price_feed.get_feed(symbol)
    candles  = sym_feed.get_candles() if sym_feed else []
    emit("candles_full", {"candles": candles, "symbol": symbol, "timeframe": "M5"})


@socketio.on("send_test_telegram")
def on_test_telegram():
    result = tg.send_test()
    emit("telegram_test_result", {"success": result})


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/price")
def api_price():
    symbol   = request.args.get("symbol", TRACKED_SYMBOLS[0]).upper()
    sym_feed = price_feed.get_feed(symbol)
    return jsonify(sym_feed.latest if sym_feed else {})


@app.route("/api/symbols")
def api_symbols():
    """Return list of all tracked symbols with their latest price."""
    result = {}
    for sym in TRACKED_SYMBOLS:
        f = price_feed.get_feed(sym)
        if f:
            result[sym] = {
                "latest": f.latest,
                "source": f.source,
            }
    return jsonify({"symbols": TRACKED_SYMBOLS, "feeds": result})


@app.route("/api/candles")
def api_candles():
    symbol   = request.args.get("symbol", TRACKED_SYMBOLS[0]).upper()
    sym_feed = price_feed.get_feed(symbol)
    candles  = sym_feed.get_candles() if sym_feed else []
    return jsonify({"candles": candles, "symbol": symbol, "timeframe": "M5"})


@app.route("/api/health")
def api_health():
    uptime_secs = int(time.time() - _START_TIME)
    h, rem = divmod(uptime_secs, 3600)
    m, s   = divmod(rem, 60)
    tg_info = tg.verify()
    total_ticks = sum(_tick_counts.values())

    # Per-symbol feed status
    symbol_status = {}
    for sym in TRACKED_SYMBOLS:
        f = price_feed.get_feed(sym)
        symbol_status[sym] = {
            "source":     f.source if f else "UNKNOWN",
            "tick_count": _tick_counts.get(sym, 0),
            "latest_bid": f.latest.get("bid") if f else None,
        }

    return jsonify({
        "status":      "ONLINE",
        "uptime":      f"{h:02d}h {m:02d}m {s:02d}s",
        "mode":        "RESEARCH / DEMO ONLY",
        "environment": os.getenv("ENVIRONMENT", "RESEARCH"),
        "price_source": price_feed.source,
        "tracked_symbols": TRACKED_SYMBOLS,
        "symbol_status":   symbol_status,
        "connected_clients": _connected_clients,
        "tick_count":    total_ticks,
        "telegram":      tg_info,
        "components": {
            "data_pipeline":   {"status": "READY",  "color": "green"},
            "candle_builder":  {"status": "READY",  "color": "green"},
            "feature_engine":  {"status": "READY",  "color": "green"},
            "setup_detector":  {"status": f"ACTIVE ({len(TRACKED_SYMBOLS)} symbols)", "color": "green"},
            "risk_firewall":   {"status": "ACTIVE", "color": "green"},
            "price_feed":      {"status": price_feed.source, "color": "green" if price_feed.source != "SIMULATION" else "yellow"},
            "websocket":       {"status": "ACTIVE", "color": "green"},
            "telegram_bot":    {"status": "ACTIVE" if tg_info.get("configured") else "NOT CONFIGURED", "color": "green" if tg_info.get("configured") else "yellow"},
            "live_trading":    {"status": "DISABLED", "color": "red"},
        },
        "safety": {
            "live_trading_disabled": True,
            "order_send_blocked":    True,
            "real_money_blocked":    True,
        },
        "server_time": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/backtest")
def api_backtest():
    """
    Read real research and backtest results from PostgreSQL.
    Falls back to clearly-labeled placeholder data if DB is not reachable.
    """
    symbol = request.args.get("symbol", TRACKED_SYMBOLS[0]).upper()
    db_url = os.getenv("DATABASE_URL", "")

    if db_url:
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(db_url, connect_args={"connect_timeout": 3})
            with engine.connect() as conn:
                # 1. Query latest research run for this symbol
                r_row = conn.execute(text("""
                    SELECT
                        r.id AS run_id,
                        d.symbol,
                        d.timeframe,
                        d.start_time,
                        d.end_time,
                        d.row_count,
                        COUNT(o.id)                                   AS total_setups,
                        SUM(CASE WHEN o.direction = 'BULLISH' THEN 1 ELSE 0 END) AS bullish_count,
                        SUM(CASE WHEN o.direction = 'BEARISH' THEN 1 ELSE 0 END) AS bearish_count,
                        r.created_at                                  AS run_at
                    FROM research_runs r
                    JOIN research_datasets d ON d.id = r.dataset_id
                    LEFT JOIN research_setup_occurrences o ON o.research_run_id = r.id
                    WHERE d.symbol = :symbol
                    GROUP BY r.id, d.symbol, d.timeframe, d.start_time, d.end_time, d.row_count, r.created_at
                    ORDER BY r.created_at DESC
                    LIMIT 1
                """), {"symbol": symbol}).fetchone()

                # 2. Query latest backtest_run with metrics if available
                bt_row = conn.execute(text("""
                    SELECT
                        b.id,
                        b.trade_count,
                        b.wins,
                        b.losses,
                        b.total_r,
                        b.metrics
                    FROM backtest_runs b
                    ORDER BY b.id DESC
                    LIMIT 1
                """)).fetchone()

                bt_data = {}
                if bt_row:
                    import json
                    raw_m = bt_row.metrics
                    if isinstance(raw_m, str):
                        try:
                            raw_m = json.loads(raw_m)
                        except Exception:
                            raw_m = {}
                    overall = (raw_m or {}).get("overall", {})
                    trade_cnt = bt_row.trade_count or 0
                    wins      = bt_row.wins or 0
                    losses    = bt_row.losses or 0
                    win_rate  = round((wins / trade_cnt * 100), 1) if trade_cnt > 0 else (
                        float(overall.get("win_rate", 0)) * 100 if overall.get("win_rate") else 0.0
                    )
                    bt_data = {
                        "total_trades":           trade_cnt or overall.get("sample_size", 0),
                        "wins":                   wins,
                        "losses":                 losses,
                        "win_rate":               win_rate,
                        "total_r":                float(bt_row.total_r or 0),
                        "expectancy_r":           float(overall.get("expectancy_r") or 0),
                        "profit_factor":          overall.get("profit_factor") or "—",
                        "avg_win_r":              float(overall.get("average_win_r") or 0),
                        "max_drawdown_pct":       float(overall.get("max_drawdown_r") or 0),
                        "consecutive_losses_max": int(overall.get("max_consecutive_losses") or 0),
                    }

                if r_row:
                    return jsonify({
                        "symbol":                 r_row.symbol,
                        "timeframe":              r_row.timeframe,
                        "total_setups":           r_row.total_setups,
                        "bullish_count":          r_row.bullish_count,
                        "bearish_count":          r_row.bearish_count,
                        "data_period":            f"{r_row.start_time} → {r_row.end_time}",
                        "row_count":              r_row.row_count,
                        "run_at":                 str(r_row.run_at),
                        "source":                 "POSTGRESQL_REAL",
                        "total_trades":           bt_data.get("total_trades", r_row.total_setups),
                        "win_rate":               bt_data.get("win_rate", 0.0),
                        "profit_factor":          bt_data.get("profit_factor", "—"),
                        "expectancy_r":           bt_data.get("expectancy_r", 0.0),
                        "max_drawdown_pct":       bt_data.get("max_drawdown_pct", 0.0),
                        "sharpe_ratio":           "—",
                        "avg_win_r":              bt_data.get("avg_win_r", 0.0),
                        "consecutive_losses_max": bt_data.get("consecutive_losses_max", 0),
                        "note":                   "Verified research & backtest results from PostgreSQL",
                    })
        except Exception as e:
            logger.warning(f"DB backtest query failed: {e}")

    # Clearly labeled placeholder when DB has no records for this symbol
    return jsonify({
        "symbol":                 symbol,
        "timeframe":              "M5",
        "source":                 "PLACEHOLDER",
        "note":                   f"No research records for {symbol} yet. Run `python scripts/run_research.py`.",
        "total_trades":           0,
        "win_rate":               0,
        "profit_factor":          "—",
        "expectancy_r":           0,
        "max_drawdown_pct":       0,
        "sharpe_ratio":           "—",
        "avg_win_r":              0,
        "consecutive_losses_max": 0,
        "total_setups":           0,
        "data_period":            "Awaiting research run",
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
        "name":            "Trader Machine V1",
        "version":         "3.0.0-multisymbol",
        "mode":            "RESEARCH / DEMO ONLY",
        "price_source":    price_feed.source,
        "tracked_symbols": TRACKED_SYMBOLS,
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    price_feed.start()

    tg_info = tg.verify()
    if tg_info.get("configured"):
        tg.send_startup(tracked_symbols=TRACKED_SYMBOLS)
        logger.info(f"Telegram connected: @{tg_info.get('bot_username')}")
    else:
        logger.warning("Telegram not configured — add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env")

    logger.info(f"Price source: {price_feed.source}")
    logger.info(f"Tracked symbols: {TRACKED_SYMBOLS}")

    print("\n" + "=" * 65)
    print("  TRADER MACHINE — DASHBOARD V3 (Multi-Symbol Real-Time)")
    print(f"  Symbols:      {', '.join(TRACKED_SYMBOLS)}")
    print(f"  Price source: {price_feed.source}")
    print(f"  Telegram:     {'ACTIVE' if tg_info.get('configured') else 'NOT CONFIGURED'}")
    print(f"  Fake signals: NONE — all outputs are mathematically derived")
    print("  URL:  http://localhost:5050")
    print("=" * 65 + "\n")

    socketio.run(app, host="0.0.0.0", port=5050, debug=False, allow_unsafe_werkzeug=True)


