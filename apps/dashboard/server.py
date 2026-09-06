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
from apps.dashboard.market_hours import is_forex_market_open, get_market_status

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
        is_open, market_msg = get_market_status()
        spread_val = 0.20
        if sym_feed and sym_feed.latest:
            spread_val = float(sym_feed.latest.get("spread", 0.20))

        analysis = analyzer.analyze(candles, current_spread=spread_val, is_market_open=is_open)
        actionable_signals = analysis.get("signals", [])

        # Check Forex market open/close status
        system_status = analysis.get("status", "WAIT")
        system_reason = analysis.get("reason", "Waiting for confluence")
        if not is_open:
            if system_status in ("WAIT", "WATCH"):
                system_status = "MARKET_CLOSED"
                system_reason = market_msg

        # Emit current system state to UI
        socketio.emit("signals_update", {
            "symbol":          symbol,
            "signals":         actionable_signals,
            "count":           len(actionable_signals),
            "status":          system_status,
            "reason":          system_reason,
            "metrics":         analysis.get("metrics", {}),
            "smc":             analysis.get("smc", {}),
            "xauusd_breakout": analysis.get("xauusd_breakout"),
            "market_open":     is_open,
            "market_status":   market_msg,
        })

        # STRICT MULTI-LAYER SAFETY FIREWALL FOR TELEGRAM ALERTS (AGENTS.MD Law #2, #10, #20):
        # Prevent unwanted alerts during research, weekend closures, or on stale candles
        feed_source = sym_feed.source if sym_feed else "UNKNOWN"
        for s in actionable_signals:
            # GATE 1: Environment Switch — Are Telegram signal broadcasts enabled?
            if not tg.are_signals_enabled():
                logger.debug("🛡️ Telegram alert BLOCKED for %s: TELEGRAM_SIGNALS_ENABLED is false (Research Mode)", s["id"])
                continue

            # GATE 2: Market Hours Guard — Never send live signals when Forex market is closed
            if not is_open:
                logger.info("🛡️ Telegram alert BLOCKED for %s: Forex market is closed (Weekend)", s["id"])
                continue

            # GATE 3: Data Source Guard — Never send signals on simulated feeds
            if feed_source == "SIMULATION":
                logger.debug("🛡️ Telegram alert BLOCKED for %s: Source is SIMULATION (real data required)", s["id"])
                continue

            # GATE 4: Candle Freshness Guard — Never send signals on historical or stale candles
            sig_ts_str = s.get("timestamp")
            is_fresh = False
            if sig_ts_str:
                try:
                    sig_dt = datetime.fromisoformat(sig_ts_str)
                    if sig_dt.tzinfo is None:
                        sig_dt = sig_dt.replace(tzinfo=timezone.utc)
                    age_seconds = abs((datetime.now(timezone.utc) - sig_dt).total_seconds())
                    # M5 candle: must have closed within last 15 minutes (900 seconds)
                    if age_seconds <= 900:
                        is_fresh = True
                    else:
                        logger.info("🛡️ Telegram alert BLOCKED for %s: Candle is stale (age: %.1f hours)", s["id"], age_seconds / 3600.0)
                except Exception as ex:
                    logger.warning("Could not parse signal timestamp %s: %s", sig_ts_str, ex)

            if not is_fresh:
                continue

            # GATE 5: Sniper Cooldown & Setup State verification
            if s.get("should_notify"):
                logger.info("⚡ ARMED/FIRE setup verified on LIVE market data (%s)! Sending Telegram: %s", feed_source, s["id"])
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
        sym = TRACKED_SYMBOLS[0]
        analyzer = _analyzers.get(sym)
        is_open, _ = get_market_status()
        spread_val = float(default_feed.latest.get("spread", 0.20)) if default_feed.latest else 0.20
        analysis_res = analyzer.analyze(candles, current_spread=spread_val, is_market_open=is_open) if (analyzer and candles) else {}
        emit("candles_full", {
            "candles":         candles,
            "symbol":          sym,
            "timeframe":       "M5",
            "smc":             analysis_res.get("smc", {}),
            "xauusd_breakout": analysis_res.get("xauusd_breakout"),
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
    analyzer = _analyzers.get(symbol)
    is_open, _ = get_market_status()
    spread_val = float(sym_feed.latest.get("spread", 0.20)) if (sym_feed and sym_feed.latest) else 0.20
    analysis_res = analyzer.analyze(candles, current_spread=spread_val, is_market_open=is_open) if (analyzer and candles) else {}
    emit("candles_full", {
        "candles":         candles,
        "symbol":          symbol,
        "timeframe":       "M5",
        "smc":             analysis_res.get("smc", {}),
        "xauusd_breakout": analysis_res.get("xauusd_breakout"),
    })


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


@app.route("/api/breakout/xauusd")
def api_breakout_xauusd():
    """Return latest evaluation of XAUUSD Breakout Engine V1."""
    analyzer = _analyzers.get("XAUUSD")
    sym_feed = price_feed.get_feed("XAUUSD")
    candles = sym_feed.get_candles() if sym_feed else []
    is_open, _ = get_market_status()
    spread_val = 0.20
    if sym_feed and sym_feed.latest:
        spread_val = float(sym_feed.latest.get("spread", 0.20))
    analysis = analyzer.analyze(candles, current_spread=spread_val, is_market_open=is_open) if analyzer else {}
    return jsonify(analysis.get("xauusd_breakout") or {})


@app.route("/api/setups/xauusd")
def api_setups_xauusd():
    """Return historical XAU/USD setups (both actionable and NO_TRADE)."""
    from core.strategies.xauusd_logger import setup_logger
    limit = int(request.args.get("limit", 50))
    return jsonify({
        "recent_setups": setup_logger.get_recent(limit=limit),
        "no_trade_setups": setup_logger.get_no_trade_setups(limit=limit),
        "actionable_setups": setup_logger.get_actionable_setups(limit=limit),
        "score_distribution": setup_logger.count_by_score_brackets(),
    })


@app.route("/api/analytics/xauusd")
def api_analytics_xauusd():
    """Return score-bracket analytics and expectancy validation for XAU/USD."""
    from core.strategies.xauusd_backtest import XAUUSDBacktestEngine
    from dataclasses import asdict
    sym_feed = price_feed.get_feed("XAUUSD")
    candles = sym_feed.get_candles() if sym_feed else []
    bt_engine = XAUUSDBacktestEngine()
    report = bt_engine.run(candles, min_score_to_trade=60)
    return jsonify({
        "symbol": "XAUUSD",
        "total_candles": report.total_candles_evaluated,
        "total_setups": report.total_setups_observed,
        "total_trades": report.total_trades_taken,
        "false_breakout_rate": report.false_breakout_rate,
        "breakout_continuation_rate": report.breakout_continuation_rate,
        "overall_metrics": asdict(report.overall_metrics),
        "by_score_range": {k: asdict(v) for k, v in report.by_score_range.items()},
        "by_session": {k: asdict(v) for k, v in report.by_session.items()},
        "by_atr_regime": {k: asdict(v) for k, v in report.by_atr_regime.items()},
        "by_category": {k: asdict(v) for k, v in report.by_category.items()},
    })


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
    is_open, market_msg = get_market_status()
    return jsonify({
        "name":                     "Trader Machine V1",
        "version":                  "3.0.0-multisymbol",
        "mode":                     "RESEARCH / DEMO ONLY",
        "price_source":             price_feed.source,
        "tracked_symbols":          TRACKED_SYMBOLS,
        "market_open":              is_open,
        "market_status":            market_msg,
        "telegram_signals_enabled": tg.are_signals_enabled(),
    })


@app.route("/api/smc")
def api_smc():
    symbol = request.args.get("symbol", TRACKED_SYMBOLS[0]).upper()
    analyzer = _analyzers.get(symbol)
    sym_feed = price_feed.get_feed(symbol)
    candles  = sym_feed.get_candles() if sym_feed else []
    if analyzer and candles:
        analysis = analyzer.analyze(candles)
        return jsonify({"symbol": symbol, "smc": analysis.get("smc", {})})
    return jsonify({"symbol": symbol, "smc": {}})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    price_feed.start()

    tg_info = tg.verify()
    signals_enabled = tg.are_signals_enabled()
    if tg_info.get("configured"):
        if signals_enabled:
            tg.send_startup(tracked_symbols=TRACKED_SYMBOLS)
            logger.info(f"Telegram signals ACTIVE: @{tg_info.get('bot_username')}")
        else:
            logger.info(f"Telegram connected: @{tg_info.get('bot_username')} (Signals MUTED: TELEGRAM_SIGNALS_ENABLED=false)")
    else:
        logger.warning("Telegram not configured — add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env")

    is_open, market_msg = get_market_status()
    logger.info(f"Price source: {price_feed.source}")
    logger.info(f"Tracked symbols: {TRACKED_SYMBOLS}")
    logger.info(f"Market status: {market_msg}")

    print("\n" + "=" * 65)
    print("  TRADER MACHINE — DASHBOARD V3 (Multi-Symbol Real-Time)")
    print(f"  Symbols:        {', '.join(TRACKED_SYMBOLS)}")
    print(f"  Price source:   {price_feed.source}")
    print(f"  Market:         {'OPEN' if is_open else 'CLOSED (Weekend)'}")
    print(f"  Telegram Bot:   {'CONNECTED' if tg_info.get('configured') else 'NOT CONFIGURED'}")
    print(f"  Signal Alerts:  {'ACTIVE' if signals_enabled else 'MUTED (Research Mode — set TELEGRAM_SIGNALS_ENABLED=true to enable)'}")
    print(f"  Fake signals:   NONE — all outputs are mathematically derived")
    print("  URL:            http://localhost:5050")
    print("=" * 65 + "\n")

    socketio.run(app, host="0.0.0.0", port=5050, debug=False, allow_unsafe_werkzeug=True)


