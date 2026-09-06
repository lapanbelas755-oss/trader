"""
Trader Machine — Real-Time Price Feed Engine (Multi-Symbol)
Supports:
  1. MT5 Worker (highest priority — live data from Windows VPS)
  2. TraderMade REST API (real market data, free tier fallback)
  3. Twelve Data REST API (alternative fallback)
  4. Smart simulation per-symbol (last resort)

Tracked symbols: EURUSD, XAUUSD, GBPUSD, USDJPY, GBPJPY
"""

import os
import time
import random
import threading
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict
import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_ROOT / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TRADERMADE_API_KEY  = os.getenv("TRADERMADE_API_KEY", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

TRADERMADE_URL  = "https://marketdata.tradermade.com/api/v1/live"
TWELVE_DATA_URL = "https://api.twelvedata.com/price"

_raw_symbols = os.getenv("TRACKED_SYMBOLS", "EURUSD,XAUUSD,GBPUSD,USDJPY,GBPJPY")
TRACKED_SYMBOLS: list = [s.strip().upper() for s in _raw_symbols.split(",") if s.strip()]

POLL_INTERVAL_REAL = 2      # seconds — real API polling
POLL_INTERVAL_SIM  = 0.5    # seconds — simulation (faster)

# Per-symbol config: base_price, pip_multiplier, volatility
# Forex majors:  1 pip = 0.0001 → pip_multiplier = 10000
# JPY pairs:     1 pip = 0.01   → pip_multiplier = 100
# XAUUSD (gold): 1 pip = 0.01   → pip_multiplier = 100
SYMBOL_CONFIG: Dict = {
    "EURUSD": {"base_price": 1.10250, "pip_multiplier": 10000, "annual_vol": 0.065, "annual_drift": 0.02, "decimals": 5},
    "XAUUSD": {"base_price": 2485.0,  "pip_multiplier": 100,   "annual_vol": 0.18,  "annual_drift": 0.04, "decimals": 2},
    "GBPUSD": {"base_price": 1.27500, "pip_multiplier": 10000, "annual_vol": 0.080, "annual_drift": 0.02, "decimals": 5},
    "USDJPY": {"base_price": 147.500, "pip_multiplier": 100,   "annual_vol": 0.070, "annual_drift": 0.01, "decimals": 3},
    "GBPJPY": {"base_price": 188.000, "pip_multiplier": 100,   "annual_vol": 0.095, "annual_drift": 0.01, "decimals": 3},
}

TRADERMADE_SYMBOL_MAP: Dict = {
    "EURUSD": "EURUSD",
    "XAUUSD": "XAUUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "GBPJPY": "GBPJPY",
}

TWELVE_DATA_SYMBOL_MAP: Dict = {
    "EURUSD": "EUR/USD",
    "XAUUSD": "XAU/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "GBPJPY": "GBP/JPY",
}


# ---------------------------------------------------------------------------
# Smart Simulation Engine (per-symbol)
# ---------------------------------------------------------------------------

class SmartSimulator:
    """Realistic per-symbol price simulation using Geometric Brownian Motion."""

    def __init__(self, symbol: str):
        cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])
        self.symbol         = symbol
        self.pip_multiplier = cfg["pip_multiplier"]
        self.decimals       = cfg["decimals"]
        self.annual_drift   = cfg["annual_drift"]
        self.annual_vol     = cfg["annual_vol"]
        self.price          = cfg["base_price"]
        self.last_ts        = time.time()
        self._lock          = threading.Lock()

    def _session_multiplier(self) -> float:
        hour = datetime.now(timezone.utc).hour
        if 7 <= hour < 9:   return 0.6
        if 9 <= hour < 12:  return 1.2
        if 12 <= hour < 17: return 1.4
        if 17 <= hour < 21: return 1.0
        return 0.4

    def _spread(self) -> float:
        pip  = 1.0 / self.pip_multiplier
        hour = datetime.now(timezone.utc).hour
        if 9 <= hour < 21:
            return random.uniform(pip * 0.7, pip * 1.2)
        return random.uniform(pip * 1.5, pip * 3.0)

    def tick(self) -> dict:
        with self._lock:
            now = time.time()
            dt  = min(now - self.last_ts, 60.0)
            self.last_ts = now

            vol   = (self.annual_vol / (252 * 86400) ** 0.5) * self._session_multiplier()
            drift = self.annual_drift / (252 * 86400)
            dW    = random.gauss(0, 1)
            self.price *= (1 + drift * dt + vol * dW * (dt ** 0.5))
            self.price  = round(self.price, self.decimals)

            spread = self._spread()
            bid    = round(self.price - spread / 2, self.decimals)
            ask    = round(self.price + spread / 2, self.decimals)

            return {
                "symbol":      self.symbol,
                "bid":         bid,
                "ask":         ask,
                "mid":         self.price,
                "spread_pips": round(spread * self.pip_multiplier, 1),
                "timestamp":   datetime.now(timezone.utc).isoformat(),
                "source":      "SIMULATION",
                "data_type":   "SIMULATED",
            }


# ---------------------------------------------------------------------------
# Real Data Fetchers
# ---------------------------------------------------------------------------

def _make_tick(symbol: str, bid: float, ask: float, source: str) -> dict:
    """Build a validated tick dict from raw bid/ask."""
    cfg     = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG["EURUSD"])
    dec     = cfg["decimals"]
    pip_mul = cfg["pip_multiplier"]
    bid     = round(bid, dec)
    ask     = round(ask, dec)
    mid     = round((bid + ask) / 2, dec)
    spread  = round((ask - bid) * pip_mul, 1)
    return {
        "symbol":      symbol,
        "bid":         bid,
        "ask":         ask,
        "mid":         mid,
        "spread_pips": spread,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "source":      source,
        "data_type":   "OBSERVED",
    }


_tradermade_disabled = False
_twelve_data_disabled = False

def fetch_tradermade_multi(api_key: str, symbols: list) -> Dict:
    """Fetch multiple symbols from TraderMade in a single HTTP request."""
    global _tradermade_disabled
    if _tradermade_disabled:
        return {}
    currency_str = ",".join(TRADERMADE_SYMBOL_MAP.get(s, s) for s in symbols)
    try:
        resp = requests.get(
            TRADERMADE_URL,
            params={"currency": currency_str, "api_key": api_key},
            timeout=5,
        )
        if resp.status_code in (401, 403):
            logger.warning("TraderMade API key is invalid/unauthorized — disabling TraderMade feed.")
            _tradermade_disabled = True
            return {}
        resp.raise_for_status()
        data   = resp.json()
        result = {}
        for q in data.get("quotes", []):
            raw_sym = q.get("base_currency", "") + q.get("quote_currency", "")
            sym     = raw_sym.upper()
            if sym in SYMBOL_CONFIG:
                result[sym] = _make_tick(sym, float(q["bid"]), float(q["ask"]), "TRADERMADE")
        return result
    except Exception as e:
        logger.debug(f"TraderMade multi-fetch notice: {e}")
        return {}


def fetch_twelve_data_single(api_key: str, symbol: str) -> Optional[dict]:
    """Fetch single symbol from Twelve Data."""
    global _twelve_data_disabled
    if _twelve_data_disabled:
        return None
    twelve_sym = TWELVE_DATA_SYMBOL_MAP.get(symbol, symbol)
    try:
        resp = requests.get(
            TWELVE_DATA_URL,
            params={"symbol": twelve_sym, "apikey": api_key},
            timeout=5,
        )
        if resp.status_code in (401, 403):
            logger.warning("Twelve Data API key is invalid/unauthorized — disabling Twelve Data feed.")
            _twelve_data_disabled = True
            return None
        resp.raise_for_status()
        data = resp.json()
        if "price" not in data:
            return None
        mid    = float(data["price"])
        pip    = 1.0 / SYMBOL_CONFIG.get(symbol, {}).get("pip_multiplier", 10000)
        spread = pip
        return _make_tick(symbol, mid - spread / 2, mid + spread / 2, "TWELVE_DATA")
    except Exception as e:
        logger.debug(f"Twelve Data fetch notice ({symbol}): {e}")
YAHOO_SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "GBPJPY": "GBPJPY=X",
}

_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

def fetch_real_public_ticks(symbols: list) -> Dict[str, dict]:
    """
    Fetch real observed market prices without API key requirement.
    Uses Yahoo Finance for Forex majors and Gold API for XAU/USD spot.
    Returns: {symbol: tick_dict}
    """
    results = {}

    # 1. Real spot gold from Gold API
    if "XAUUSD" in symbols:
        try:
            r = requests.get("https://api.gold-api.com/price/XAU", headers=_HTTP_HEADERS, timeout=3.5)
            if r.status_code == 200:
                raw_price = float(r.json()["price"])
                results["XAUUSD"] = _make_tick("XAUUSD", raw_price - 0.15, raw_price + 0.15, "GOLD_API_REAL")
        except Exception as e:
            logger.debug(f"Gold API notice: {e}")

    # 2. Real forex rates from Yahoo Finance
    forex_to_fetch = [s for s in symbols if s in YAHOO_SYMBOL_MAP and s not in results]
    for sym in forex_to_fetch:
        ysym = YAHOO_SYMBOL_MAP[sym]
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?interval=1m&range=1d"
            r = requests.get(url, headers=_HTTP_HEADERS, timeout=3.5)
            if r.status_code == 200:
                meta = r.json()["chart"]["result"][0]["meta"]
                raw_price = float(meta["regularMarketPrice"])
                cfg = SYMBOL_CONFIG.get(sym, {})
                pip_mul = cfg.get("pip_multiplier", 10000)
                dec = cfg.get("decimals", 5)
                spread = 1.2 / pip_mul
                results[sym] = _make_tick(sym, raw_price - spread / 2, raw_price + spread / 2, "YAHOO_REAL")
        except Exception as e:
            logger.debug(f"Yahoo real forex notice ({sym}): {e}")

    return results


def fetch_real_public_m5_bars(symbol: str, count: int = 80) -> list:
    """Fetch real historical M5 candles from Yahoo Finance."""
    ysym = YAHOO_SYMBOL_MAP.get(symbol)
    if not ysym and symbol == "XAUUSD":
        ysym = "GC=F"
    if not ysym:
        return []

    try:
        rng = "5d" if symbol == "XAUUSD" else "2d"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?interval=5m&range={rng}"
        r = requests.get(url, headers=_HTTP_HEADERS, timeout=4.0)
        if r.status_code != 200:
            return []
        d = r.json()
        res = d["chart"]["result"][0]
        timestamps = res.get("timestamp", [])
        quotes = res["indicators"]["quote"][0]
        dec = SYMBOL_CONFIG.get(symbol, {}).get("decimals", 5)

        candles = []
        for i in range(len(timestamps)):
            o = quotes["open"][i]
            h = quotes["high"][i]
            l = quotes["low"][i]
            c = quotes["close"][i]
            v = quotes.get("volume", [1] * len(timestamps))[i] or 1
            if None in (o, h, l, c):
                continue
            candles.append({
                "time":   int(timestamps[i]),
                "open":   round(float(o), dec),
                "high":   round(float(h), dec),
                "low":    round(float(l), dec),
                "close":  round(float(c), dec),
                "volume": int(v),
            })
        return candles[-count:] if len(candles) > count else candles
    except Exception as e:
        logger.debug(f"Yahoo real M5 fetch notice ({symbol}): {e}")
        return []


def fetch_mt5_worker_tick(symbol: str) -> Optional[dict]:
    """Fetch live tick from Windows MT5 Worker via HMAC-signed HTTP."""
    secret = os.getenv("WORKER_HMAC_SECRET", "")
    host   = os.getenv("MT5_WORKER_HOST", "127.0.0.1")
    if not secret:
        return None

    ports = []
    env_port = os.getenv("MT5_WORKER_PORT")
    if env_port:
        ports.append(env_port)
    if "8080" not in ports:
        ports.append("8080")

    for p in ports:
        try:
            from core.execution.v2_spec import HMACRequestSigner, SignedNodeRequest
            req = SignedNodeRequest(
                request_id=f"tick_{symbol}_{int(time.time()*1000)}",
                action="get_tick",
                params={"symbol": symbol}
            )
            signed_req = HMACRequestSigner.sign_request(req, secret)
            url  = f"http://{host}:{p}/api/v3/request"
            resp = requests.post(url, json=signed_req.model_dump(), timeout=1.5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "SUCCESS" and "payload" in data:
                    payload = data["payload"]
                    bid  = float(payload["bid"])
                    ask  = float(payload["ask"])
                    tick = _make_tick(symbol, bid, ask, "MT5_REAL")
                    if payload.get("time"):
                        tick["timestamp"] = payload["time"]
                    return tick
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Per-Symbol Feed Manager
# ---------------------------------------------------------------------------

class SymbolFeedManager:
    """Manages real-time price feed and M5 candle aggregation for a single symbol."""

    def __init__(self, symbol: str):
        self.symbol         = symbol
        self._sim           = SmartSimulator(symbol)
        self._latest: dict  = self._sim.tick()
        self._candles: list = []
        self._current_candle: Optional[dict] = None
        self._lock          = threading.Lock()
        self._callbacks     = []
        self._source        = "SIMULATION"

    def register_callback(self, fn):
        self._callbacks.append(fn)

    def _notify(self, tick: dict):
        for cb in self._callbacks:
            try:
                cb(tick)
            except Exception as e:
                logger.error(f"Callback error ({self.symbol}): {e}")

    def _update_candle(self, tick: dict):
        try:
            ts = datetime.fromisoformat(tick["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            ts = datetime.now(timezone.utc)

        ts     = ts.replace(second=0, microsecond=0)
        bar_ts = int(ts.replace(minute=(ts.minute // 5) * 5).timestamp())
        price  = tick["mid"]

        with self._lock:
            if self._current_candle is None or self._current_candle["time"] != bar_ts:
                if self._current_candle is not None:
                    self._candles.append(dict(self._current_candle))
                    if len(self._candles) > 200:
                        self._candles = self._candles[-200:]
                self._current_candle = {
                    "time":   bar_ts,
                    "open":   price,
                    "high":   price,
                    "low":    price,
                    "close":  price,
                    "volume": 1,
                }
            else:
                c = self._current_candle
                c["high"]   = max(c["high"], price)
                c["low"]    = min(c["low"],  price)
                c["close"]  = price
                c["volume"] += 1

    def update_from_tick(self, tick: dict):
        with self._lock:
            self._latest = tick
        self._source = tick.get("source", "SIMULATION")
        self._update_candle(tick)
        self._notify(tick)

    def seed_candles(self, count: int = 80):
        # 1. Try loading real historical candles from PostgreSQL
        db_url = os.getenv("DATABASE_URL", "")
        if db_url:
            try:
                from sqlalchemy import create_engine, text
                engine = create_engine(db_url, connect_args={"connect_timeout": 3})
                with engine.connect() as conn:
                    rows = conn.execute(text("""
                        SELECT timestamp, open, high, low, close, tick_volume
                        FROM market_candles
                        WHERE symbol = :symbol
                        ORDER BY timestamp DESC
                        LIMIT :count
                    """), {"symbol": self.symbol, "count": count}).fetchall()

                    if rows:
                        with self._lock:
                            self._candles = []
                            for r in reversed(rows):
                                ts = r[0]
                                self._candles.append({
                                    "time":   int(ts.timestamp()),
                                    "open":   float(r[1]),
                                    "high":   float(r[2]),
                                    "low":    float(r[3]),
                                    "close":  float(r[4]),
                                    "volume": int(r[5]) if r[5] else 1,
                                })
                            if self._candles:
                                last = self._candles[-1]
                                self._latest = {
                                    "symbol":      self.symbol,
                                    "bid":         last["close"],
                                    "ask":         last["close"],
                                    "mid":         last["close"],
                                    "spread_pips": 0.5,
                                    "timestamp":   datetime.fromtimestamp(last["time"], tz=timezone.utc).isoformat(),
                                    "source":      "POSTGRESQL",
                                    "data_type":   "OBSERVED",
                                }
                                self._source = "POSTGRESQL"
                        logger.info(f"Loaded {len(self._candles)} real candles for {self.symbol} from PostgreSQL")
                        return
            except Exception as e:
                logger.debug(f"DB candle seed notice ({self.symbol}): {e}")

        # 2. Try loading real historical candles from public live market data
        real_bars = fetch_real_public_m5_bars(self.symbol, count=count)
        if real_bars:
            with self._lock:
                self._candles = real_bars
                last = self._candles[-1]
                dec = SYMBOL_CONFIG.get(self.symbol, {}).get("decimals", 5)
                self._latest = {
                    "symbol":      self.symbol,
                    "bid":         last["close"],
                    "ask":         last["close"],
                    "mid":         last["close"],
                    "spread_pips": 1.2,
                    "timestamp":   datetime.fromtimestamp(last["time"], tz=timezone.utc).isoformat(),
                    "source":      "YAHOO_REAL" if self.symbol != "XAUUSD" else "GOLD_API_REAL",
                    "data_type":   "OBSERVED",
                }
                self._source = "YAHOO_REAL" if self.symbol != "XAUUSD" else "GOLD_API_REAL"
            logger.info(f"Loaded {len(self._candles)} real M5 candles for {self.symbol} from live market data")
            return

        # 3. Last-resort fallback to simulation (only if network is offline)
        now_ts = int(time.time() // 300) * 300
        sim = SmartSimulator(self.symbol)
        with self._lock:
            self._candles = []
            cur_price = sim.price
            for i in range(count):
                bar_time = now_ts - (count - i) * 300
                step = (sim.annual_vol / (252 * 288) ** 0.5) * cur_price * random.gauss(0, 1)
                c_open = cur_price
                c_close = round(cur_price + step, sim.decimals)
                c_high = round(max(c_open, c_close) + abs(random.gauss(0, 1)) * abs(step) * 0.4, sim.decimals)
                c_low = round(min(c_open, c_close) - abs(random.gauss(0, 1)) * abs(step) * 0.4, sim.decimals)
                cur_price = c_close
                self._candles.append({
                    "time":   bar_time,
                    "open":   c_open,
                    "high":   c_high,
                    "low":    c_low,
                    "close":  c_close,
                    "volume": random.randint(50, 500),
                })
            sim.price = cur_price
            self._current_candle = None

    @property
    def latest(self) -> dict:
        with self._lock:
            return dict(self._latest)

    @property
    def source(self) -> str:
        return self._source

    def get_candles(self) -> list:
        with self._lock:
            candles = list(self._candles)
            if self._current_candle:
                candles.append(dict(self._current_candle))
            return candles


# ---------------------------------------------------------------------------
# Master Multi-Symbol Feed Manager
# ---------------------------------------------------------------------------

class PriceFeedManager:
    """
    Manages real-time price feeds for all tracked symbols.
    Fallback chain: MT5 Worker → TraderMade → Twelve Data → Simulation
    """

    def __init__(self, symbols: Optional[list] = None):
        self._symbols  = symbols or TRACKED_SYMBOLS
        self._feeds: Dict = {sym: SymbolFeedManager(sym) for sym in self._symbols}
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._source   = "SIMULATION"

    def get_feed(self, symbol: str) -> Optional[SymbolFeedManager]:
        return self._feeds.get(symbol.upper())

    def register_callback(self, symbol: str, fn):
        feed = self._feeds.get(symbol.upper())
        if feed:
            feed.register_callback(fn)

    def register_global_callback(self, fn):
        for f in self._feeds.values():
            f.register_callback(fn)

    @property
    def source(self) -> str:
        return self._source

    @property
    def latest(self) -> dict:
        default = self._symbols[0] if self._symbols else "EURUSD"
        feed = self._feeds.get(default)
        return feed.latest if feed else {}

    def get_candles(self, symbol: Optional[str] = None) -> list:
        sym  = (symbol or (self._symbols[0] if self._symbols else "EURUSD")).upper()
        feed = self._feeds.get(sym)
        return feed.get_candles() if feed else []

    def _fetch_all_ticks(self) -> Dict:
        results: Dict = {}

        # 1. MT5 Worker (highest priority)
        mt5_ok = set()
        for sym in self._symbols:
            tick = fetch_mt5_worker_tick(sym)
            if tick:
                results[sym] = tick
                mt5_ok.add(sym)
        if mt5_ok:
            self._source = "MT5_REAL"

        remaining = [s for s in self._symbols if s not in results]
        if not remaining:
            return results

        # 2. Real Public Market Data (Yahoo Finance Forex + Spot Gold API)
        real_ticks = fetch_real_public_ticks(remaining)
        for sym, tick in real_ticks.items():
            results[sym] = tick
            remaining = [s for s in remaining if s != sym]
        if real_ticks and not mt5_ok:
            self._source = "REAL_MARKET"

        if not remaining:
            return results

        # 3. TraderMade batch (fallback)
        if TRADERMADE_API_KEY and remaining:
            tm = fetch_tradermade_multi(TRADERMADE_API_KEY, remaining)
            for sym, tick in tm.items():
                results[sym] = tick
                remaining = [s for s in remaining if s != sym]
            if tm and not mt5_ok and not real_ticks:
                self._source = "TRADERMADE"

        # 4. Twelve Data single requests (fallback)
        if TWELVE_DATA_API_KEY and remaining:
            for sym in list(remaining):
                tick = fetch_twelve_data_single(TWELVE_DATA_API_KEY, sym)
                if tick:
                    results[sym] = tick
                    remaining.remove(sym)
            if not mt5_ok and not real_ticks:
                self._source = "TWELVE_DATA"

        # 5. Last resort simulation (only if network fails completely)
        for sym in remaining:
            feed = self._feeds.get(sym)
            if feed:
                results[sym] = feed._sim.tick()

        if not mt5_ok and not real_ticks and not TRADERMADE_API_KEY and not TWELVE_DATA_API_KEY:
            self._source = "SIMULATION"

        return results

    def _loop(self):
        while self._running:
            ticks = self._fetch_all_ticks()
            for sym, tick in ticks.items():
                feed = self._feeds.get(sym)
                if feed:
                    feed.update_from_tick(tick)
            interval = POLL_INTERVAL_REAL if self._source != "SIMULATION" else POLL_INTERVAL_SIM
            time.sleep(interval)

    def start(self):
        if self._running:
            return
        for feed in self._feeds.values():
            feed.seed_candles(80)
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"PriceFeedManager started — symbols: {self._symbols}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)


# Singleton
feed = PriceFeedManager()

