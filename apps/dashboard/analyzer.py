"""
Trader Machine — Deterministic Signal Analyzer V1.
Integrates MarketStructureEngine, LiquidityLevelDetector, and SetupDetectorEngine (S01-S05).
Adheres strictly to Master Instruction (AGENTS.MD):
- SNIPER principle: WAIT is the default and valid decision.
- S01: Liquidity Sweep Reversal.
- No spam: Telegram alerts fire ONLY on mathematically validated ARMED/FIRE setups.
"""

from datetime import datetime, timezone
from decimal import Decimal
import logging
import time
from typing import Any, Dict, List, Optional

from core.candles.contract import AggregatedCandle, Timeframe
from core.liquidity.contract import (
    LiquidityLevelRecord,
    LiquidityLevelType,
    LiquidityStatus,
)
from core.liquidity.levels import LiquidityLevelDetector
from core.setups.contract import (
    SetupCode,
    SetupDirection,
    SetupRecord,
    SetupStatus,
)
from core.setups.engine import SetupDetectorEngine
from core.structure.contract import ConfirmedSwing, StructureEvent
from core.structure.engine import MarketStructureEngine

logger = logging.getLogger(__name__)


# Per-symbol defaults for pip calculation and ATR
_SYMBOL_DEFAULTS = {
    "EURUSD": {"pip_multiplier": 10000, "fallback_atr": Decimal("0.00100"), "tolerance": Decimal("0.00010"), "min_disp": Decimal("0.00010")},
    "XAUUSD": {"pip_multiplier": 100,   "fallback_atr": Decimal("2.00000"), "tolerance": Decimal("0.20000"), "min_disp": Decimal("0.10000")},
    "GBPUSD": {"pip_multiplier": 10000, "fallback_atr": Decimal("0.00120"), "tolerance": Decimal("0.00010"), "min_disp": Decimal("0.00010")},
    "USDJPY": {"pip_multiplier": 100,   "fallback_atr": Decimal("0.10000"), "tolerance": Decimal("0.01000"), "min_disp": Decimal("0.01000")},
    "GBPJPY": {"pip_multiplier": 100,   "fallback_atr": Decimal("0.15000"), "tolerance": Decimal("0.01000"), "min_disp": Decimal("0.01000")},
}


class RealSignalAnalyzer:
    """
    Evaluates real market candles against S01-S05 setup archetypes.
    Guarantees zero random/simulated outputs.
    Supports multiple symbols with per-symbol pip multiplier and ATR fallback.
    """

    def __init__(self, symbol: str = "EURUSD", timeframe: str = "M5"):
        self.symbol = symbol.strip().upper()
        self.timeframe = timeframe.strip().upper()
        cfg = _SYMBOL_DEFAULTS.get(self.symbol, _SYMBOL_DEFAULTS["EURUSD"])
        self.pip_multiplier = cfg["pip_multiplier"]
        self.struct_engine = MarketStructureEngine(
            left_bars=2,
            right_bars=2,
            default_tolerance=cfg["tolerance"],
            default_min_displacement=cfg["min_disp"],
        )
        self.liq_detector = LiquidityLevelDetector(
            symbol=self.symbol,
            tz=timezone.utc,
        )
        self.setup_engine = SetupDetectorEngine(
            symbol=self.symbol,
            timeframe=self.timeframe,
            fallback_atr=cfg["fallback_atr"],
        )
        self._sent_signal_ids: set = set()
        self._cooldowns: dict = {}

    def compute_atr(self, candles: List[AggregatedCandle], period: int = 14) -> Decimal:
        """Calculates standard ATR(14) in Decimal."""
        if len(candles) < 2:
            return Decimal("0.00100")

        tr_list = []
        for i in range(1, len(candles)):
            c = candles[i]
            prev = candles[i - 1]
            tr = max(
                c.high - c.low,
                abs(c.high - prev.close),
                abs(c.low - prev.close),
            )
            tr_list.append(tr)

        lookback = min(len(tr_list), period)
        recent_trs = tr_list[-lookback:]
        return (sum(recent_trs) / Decimal(str(len(recent_trs)))).quantize(Decimal("0.00001"))

    def build_liquidity_levels(
        self,
        candles: List[AggregatedCandle],
        swings: List[ConfirmedSwing],
        current_atr: Decimal,
    ) -> List[LiquidityLevelRecord]:
        """Extracts candidate liquidity levels from significant swings and sessions."""
        levels: List[LiquidityLevelRecord] = []
        if not candles:
            return levels

        # 1. Swing Highs & Lows as liquidity pools
        for s in swings[-10:]:
            is_high = s.swing_type.value in ("SWING_HIGH", "HH", "LH")
            lvl_type = LiquidityLevelType.SIGNIFICANT_SWING_HIGH if is_high else LiquidityLevelType.SIGNIFICANT_SWING_LOW
            levels.append(
                LiquidityLevelRecord(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    level_type=lvl_type,
                    price=s.price,
                    created_at=s.timestamp,
                    source_swing_id=s.swing_id,
                    strength=Decimal("1.0000"),
                    status=LiquidityStatus.UNTOUCHED,
                )
            )

        # 2. Session Highs / Lows
        try:
            latest_date = candles[-1].timestamp.date()
            pd_levels = self.liq_detector.extract_previous_day_levels(candles, latest_date, timeframe=self.timeframe)
            if pd_levels:
                levels.extend([pd_levels[0], pd_levels[1]])
        except Exception as e:
            logger.debug("Session level extraction notice: %s", e)

        return levels

    def analyze(self, raw_candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyzes full candle history against S01-S05 archetypes.
        Returns:
            {
                "status": "WAIT" | "WATCH" | "ARMED" | "FIRE",
                "reason": str,
                "signals": List[dict],
                "metrics": dict
            }
        """
        if len(raw_candles) < 15:
            return {
                "status": "WAIT",
                "reason": f"Accumulating market candles ({len(raw_candles)}/15 minimum required for M5 analysis)",
                "signals": [],
                "metrics": {"candles_loaded": len(raw_candles)},
            }

        # 1. Parse raw candles into validated AggregatedCandle models
        candles: List[AggregatedCandle] = []
        for c in raw_candles:
            try:
                raw_time = c.get("time")
                if isinstance(raw_time, (int, float)):
                    ts = datetime.fromtimestamp(raw_time, tz=timezone.utc)
                elif isinstance(raw_time, str):
                    ts = datetime.fromisoformat(raw_time)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                else:
                    continue

                o = Decimal(str(c["open"]))
                h = Decimal(str(c["high"]))
                l = Decimal(str(c["low"]))
                cl = Decimal(str(c["close"]))

                # Invariant sanity enforcement
                h = max(h, o, cl)
                l = min(l, o, cl)
                vol = max(1, int(c.get("volume", 1)))

                candles.append(
                    AggregatedCandle(
                        symbol=self.symbol,
                        timeframe=Timeframe.M5,
                        timestamp=ts,
                        open=o,
                        high=h,
                        low=l,
                        close=cl,
                        tick_volume=vol,
                        spread=Decimal("0.00010"),
                        is_closed=True,
                    )
                )
            except Exception as e:
                logger.debug("Candle parse error: %s", e)
                continue

        if len(candles) < 15:
            return {
                "status": "WAIT",
                "reason": "Insufficient valid candles after validation",
                "signals": [],
                "metrics": {},
            }

        # 2. Derive ATR(14)
        atr = self.compute_atr(candles, period=14)
        latest_c = candles[-1]
        eval_time = latest_c.timestamp

        # 3. Market Structure Analysis (Swings, BOS, CHoCH)
        atr_map = {c.timestamp: atr for c in candles}
        swings = self.struct_engine.swing_detector.detect_swings(candles)
        classified_swings = self.struct_engine.classifier.classify_swings(swings) if swings else []
        struct_events = self.struct_engine.analyze_structure(candles, atr_map=atr_map)

        # 4. Liquidity Pool Extraction
        liquidity_levels = self.build_liquidity_levels(candles, classified_swings, current_atr=atr)

        # 5. S01-S05 Setup Detector Evaluation
        features = [
            {
                "timestamp": latest_c.timestamp,
                "atr": atr,
                "is_strong_anomaly": False,
            }
        ]

        detected_records = self.setup_engine.detect_at_timestamp(
            timestamp=eval_time,
            candles=candles,
            features=features,
            liquidity_levels=liquidity_levels,
            structure_events=struct_events,
        )

        # 6. Filter for High-Quality ARMED & FIRE Setups
        actionable_signals: List[Dict[str, Any]] = []
        highest_status = "WAIT"

        for s in detected_records:
            if s.status in (SetupStatus.ARMED, SetupStatus.FIRE):
                highest_status = s.status.value
                mid   = float(latest_c.close)
                atr_f = float(atr)
                direction_str = "BUY" if s.direction == SetupDirection.BULLISH else "SELL"

                # Sniper risk: 1.2 × ATR SL, 2R TP
                # Minimum SL: 1 pip per symbol
                min_sl = 1.0 / self.pip_multiplier
                sl_dist = max(atr_f * 1.2, min_sl)
                tp_dist = sl_dist * 2.0

                # Round to appropriate decimals per symbol
                dec = len(str(mid).split(".")[1]) if "." in str(mid) else 5
                dec = min(dec, 5)
                entry = round(mid, dec)
                sl    = round(entry - sl_dist if direction_str == "BUY" else entry + sl_dist, dec)
                tp    = round(entry + tp_dist if direction_str == "BUY" else entry - tp_dist, dec)

                sl_pips = round(abs(entry - sl) * self.pip_multiplier, 1)
                tp_pips = round(abs(tp - entry) * self.pip_multiplier, 1)

                # Confluence-based confidence derived deterministically from confirmed evidence
                ev_items = s.evidence.to_evidence_items()
                confidence = min(95, 60 + len(ev_items) * 7) if ev_items else (90 if s.status == SetupStatus.FIRE else 80)

                sig_id = f"SIG-{self.symbol}-{s.setup_code.value}-{int(eval_time.timestamp())}"
                
                # Strict Sniper Cooldown (15 minutes per setup per symbol) & FIRE-only alerts
                now_ts = time.time()
                cooldown_key = f"{self.symbol}_{s.setup_code.value}"
                last_sent = self._cooldowns.get(cooldown_key, 0.0)
                is_fire = (s.status == SetupStatus.FIRE)
                can_alert = is_fire and (now_ts - last_sent > 900) and (sig_id not in self._sent_signal_ids)

                should_notify_telegram = can_alert
                if can_alert:
                    self._cooldowns[cooldown_key] = now_ts
                    self._sent_signal_ids.add(sig_id)

                raw_liq = str(s.liquidity_type or "Confirmed Pool").replace("LiquidityLevelType.", "").replace("_", " ").title()
                raw_struct = str(s.structure_type or "Confirmed Break").replace("BreakType.", "").replace("_", " ").title()

                actionable_signals.append({
                    "id":         sig_id,
                    "symbol":     self.symbol,
                    "setup":      f"{s.setup_code.value} — {raw_liq}",
                    "direction":  direction_str,
                    "confidence": confidence,
                    "regime":     s.regime,
                    "session":    "ACTIVE",
                    "entry":      entry,
                    "sl":         sl,
                    "tp":         tp,
                    "sl_pips":    sl_pips,
                    "tp_pips":    tp_pips,
                    "state":      s.status.value,
                    "timestamp":  eval_time.isoformat(),
                    "should_notify": should_notify_telegram,
                    "evidence": [
                        f"Symbol: {self.symbol}",
                        f"Setup: {s.setup_code.value}",
                        f"Liquidity Pool: {raw_liq}",
                        f"Structure Displacement: {raw_struct}",
                        f"ATR(14): {round(atr_f, dec)}",
                        f"SL: {sl_pips} pips | TP: {tp_pips} pips (2R)",
                    ],
                })
            elif s.status == SetupStatus.WATCH and highest_status == "WAIT":
                highest_status = "WATCH"

        return {
            "status": highest_status,
            "reason": "Sniper waiting for strict confluence" if not actionable_signals else f"{len(actionable_signals)} verified setups active",
            "signals": actionable_signals,
            "metrics": {
                "atr": float(atr),
                "swings_detected": len(swings),
                "structure_events": len(struct_events),
                "liquidity_levels": len(liquidity_levels),
                "last_close": float(latest_c.close),
                "eval_timestamp": eval_time.isoformat(),
            },
        }

    def mark_signal_sent(self, signal_id: str) -> None:
        """Records that a signal has been notified to Telegram to prevent duplicate alerts."""
        self._sent_signal_ids.add(signal_id)
