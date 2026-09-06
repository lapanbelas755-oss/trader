"""
Trader Machine — Real-Time Price Feed Engine
Supports:
  1. TraderMade REST API (real EURUSD data, free tier)
  2. Twelve Data REST API (alternative)
  3. Smart simulation fallback (when no API key configured)
"""

import os
import time
import random
import threading
import logging
from datetime import datetime, timezone
from typing import Optional
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TRADERMADE_API_KEY = os.getenv("TRADERMADE_API_KEY", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

TRADERMADE_URL = "https://marketdata.tradermade.com/api/v1/live"
TWELVE_DATA_URL = "https://api.twelvedata.com/price"

SYMBOL = "EURUSD"
POLL_INTERVAL_REAL = 2       # seconds — real API polling
POLL_INTERVAL_SIM  = 0.5     # seconds — simulation (faster)


# ---------------------------------------------------------------------------
# Smart Simulation Engine
# ---------------------------------------------------------------------------

class SmartSimulator:
    """
    Realistic EURUSD price simulation using:
    - Geometric Brownian Motion for price walk
    - Session-based volatility (Asian < London < NY)
    - Spread that widens outside sessions
    - Micro-tick noise
    """

    BASE_PRICE = 1.10250
    ANNUAL_DRIFT = 0.02
    ANNUAL_VOL   = 0.065

    def __init__(self):
        self.price = self.BASE_PRICE
        self.last_ts = time.time()
        self._lock = threading.Lock()

    def _session_multiplier(self) -> float:
        """Higher volatility during London + NY overlap."""
        hour = datetime.now(timezone.utc).hour
        if 7 <= hour < 9:   return 0.6   # Asian/London crossover
        if 9 <= hour < 12:  return 1.2   # London peak
        if 12 <= hour < 17: return 1.4   # London+NY overlap
        if 17 <= hour < 21: return 1.0   # NY only
        return 0.4                        # Off-hours

    def _spread(self) -> float:
        hour = datetime.now(timezone.utc).hour
        if 9 <= hour < 21:  return random.uniform(0.00007, 0.00012)
        return random.uniform(0.00015, 0.00030)   # wide spread off-hours

    def tick(self) -> dict:
        with self._lock:
            now = time.time()
            dt = min(now - self.last_ts, 60.0)   # cap at 60s
            self.last_ts = now

            vol   = (self.ANNUAL_VOL / (252 * 86400) ** 0.5) * self._session_multiplier()
            drift = self.ANNUAL_DRIFT / (252 * 86400)
            dW    = random.gauss(0, 1)
            self.price *= (1 + drift * dt + vol * dW * (dt ** 0.5))
            self.price  = round(self.price, 5)

            spread = self._spread()
            bid = round(self.price - spread / 2, 5)
            ask = round(self.price + spread / 2, 5)

            return {
                "symbol": SYMBOL,
                "bid": bid,
                "ask": ask,
                "mid": self.price,
                "spread_pips": round(spread * 10000, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "SIMULATION",
                "data_type": "SIMULATED",
            }


# ---------------------------------------------------------------------------
# Real Data Fetchers
# ---------------------------------------------------------------------------

def fetch_tradermade(api_key: str) -> Optional[dict]:
    """Fetch EURUSD from TraderMade REST API."""
    try:
        resp = requests.get(
            TRADERMADE_URL,
            params={"currency": SYMBOL, "api_key": api_key},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        quotes = data.get("quotes", [])
        if not quotes:
            return None
        q = quotes[0]
        bid = float(q["bid"])
        ask = float(q["ask"])
        mid = round((bid + ask) / 2, 5)
        return {
            "symbol": SYMBOL,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread_pips": round((ask - bid) * 10000, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "TRADERMADE",
            "data_type": "OBSERVED",
        }
    except Exception as e:
        logger.warning(f"TraderMade fetch error: {e}")
        return None


def fetch_twelve_data(api_key: str) -> Optional[dict]:
    """Fetch EURUSD from Twelve Data REST API."""
    try:
        resp = requests.get(
            TWELVE_DATA_URL,
            params={"symbol": "EUR/USD", "apikey": api_key},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        if "price" not in data:
            return None
        mid = float(data["price"])
        spread = 0.0001   # Twelve Data doesn't provide bid/ask on free tier
        bid = round(mid - spread / 2, 5)
        ask = round(mid + spread / 2, 5)
        return {
            "symbol": SYMBOL,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread_pips": round(spread * 10000, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "TWELVE_DATA",
            "data_type": "OBSERVED",
        }
    except Exception as e:
        logger.warning(f"Twelve Data fetch error: {e}")
        return None


def fetch_mt5_worker() -> Optional[dict]:
    """Fetch live EURUSD tick directly from local Windows MT5 Worker V3."""
    secret = os.getenv("WORKER_HMAC_SECRET", "")
    if not secret:
        return None

    ports = []
    env_port = os.getenv("MT5_WORKER_PORT")
    if env_port:
        ports.append(env_port)
    if "8080" not in ports:
        ports.append("8080")

    host = os.getenv("MT5_WORKER_HOST", "127.0.0.1")
    for p in ports:
        try:
            from core.execution.v2_spec import HMACRequestSigner, SignedNodeRequest
            req = SignedNodeRequest(
                request_id=f"tick_{int(time.time()*1000)}",
                action="get_tick",
                params={"symbol": SYMBOL}
            )
            signed_req = HMACRequestSigner.sign_request(req, secret)
            url = f"http://{host}:{p}/api/v3/request"
            resp = requests.post(url, json=signed_req.model_dump(), timeout=1.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "SUCCESS" and "payload" in data:
                    payload = data["payload"]
                    bid = float(payload["bid"])
                    ask = float(payload["ask"])
                    mid = round((bid + ask) / 2, 5)
                    spread_val = float(payload.get("spread", ask - bid))
                    # If spread is in price difference, convert to pips
                    spread_pips = round(spread_val * 10000, 1) if spread_val < 1.0 else round(spread_val, 1)
                    return {
                        "symbol": payload.get("symbol", SYMBOL),
                        "bid": bid,
                        "ask": ask,
                        "mid": mid,
                        "spread_pips": spread_pips,
                        "timestamp": payload.get("time") or datetime.now(timezone.utc).isoformat(),
                        "source": "MT5_REAL",
                        "data_type": "OBSERVED",
                    }
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Feed Manager
# ---------------------------------------------------------------------------

class PriceFeedManager:
    """
    Manages price feed with auto-fallback:
    TraderMade → Twelve Data → Smart Simulation
    """

    def __init__(self):
        self._sim = SmartSimulator()
        self._latest: dict = self._sim.tick()
        self._candles: list = []   # M5 candle buffer
        self._current_candle: Optional[dict] = None
        self._lock = threading.Lock()
        self._callbacks = []   # SocketIO emit callbacks
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._source = "SIMULATION"

    def register_callback(self, fn):
        """Register a function to call on every new tick."""
        self._callbacks.append(fn)

    def _notify(self, tick: dict):
        """Notify all registered callbacks."""
        for cb in self._callbacks:
            try:
                cb(tick)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def _update_candle(self, tick: dict):
        """Aggregate ticks into M5 candles."""
        ts   = datetime.fromisoformat(tick["timestamp"]).replace(second=0, microsecond=0)
        bar_ts = int(ts.replace(minute=(ts.minute // 5) * 5).timestamp())
        price = tick["mid"]

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

    def _fetch_tick(self) -> dict:
        # 1. Prioritize live MT5 Worker telemetry if available
        mt5_tick = fetch_mt5_worker()
        if mt5_tick:
            self._source = "MT5_REAL"
            return mt5_tick

        # 2. Fallback to external market data APIs
        if TRADERMADE_API_KEY:
            result = fetch_tradermade(TRADERMADE_API_KEY)
            if result:
                self._source = "TRADERMADE"
                return result

        if TWELVE_DATA_API_KEY:
            result = fetch_twelve_data(TWELVE_DATA_API_KEY)
            if result:
                self._source = "TWELVE_DATA"
                return result

        # 3. Last fallback: smart simulation
        self._source = "SIMULATION"
        return self._sim.tick()

    def _loop(self):
        while self._running:
            tick = self._fetch_tick()
            with self._lock:
                self._latest = tick
            self._update_candle(tick)
            self._notify(tick)
            interval = POLL_INTERVAL_REAL if self._source != "SIMULATION" else POLL_INTERVAL_SIM
            time.sleep(interval)

    def start(self):
        if self._running:
            return
        self._running = True
        # Pre-fill candle history from simulation
        sim = SmartSimulator()
        for _ in range(80):
            t = sim.tick()
            self._update_candle(t)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"PriceFeedManager started — source: {self._source or 'auto-detect'}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

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


# Singleton
feed = PriceFeedManager()
