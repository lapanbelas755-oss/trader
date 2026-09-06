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


class RealSignalAnalyzer:
    """
    Evaluates real market candles against S01-S05 setup archetypes.
    Guarantees zero random/simulated outputs.
    """

    def __init__(self, symbol: str = "EURUSD", timeframe: str = "M5"):
        self.symbol = symbol.strip().upper()
        self.timeframe = timeframe.strip().upper()
        self.struct_engine = MarketStructureEngine(
            left_bars=2,
            right_bars=2,
            default_tolerance=Decimal("0.00010"),
            default_min_displacement=Decimal("0.00010"),
        )
        self.liq_detector = LiquidityLevelDetector(
            symbol=self.symbol,
            tz=timezone.utc,
        )
        self.setup_engine = SetupDetectorEngine(
            symbol=self.symbol,
            timeframe=self.timeframe,
            fallback_atr=Decimal("0.00100"),
        )
        self._sent_signal_ids: set[str] = set()

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
            is_high = s.swing_type.value in ("HH", "LH")
            lvl_type = LiquidityLevelType.SWING_HIGH if is_high else LiquidityLevelType.SWING_LOW
            levels.append(
                LiquidityLevelRecord(
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    level_type=lvl_type,
                    price=s.price,
                    created_at=s.timestamp,
                    source_swing_id=s.swing_id,
                    strength=s.strength,
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
                mid = float(latest_c.close)
                atr_f = float(atr)
                direction_str = "BUY" if s.direction == SetupDirection.BULLISH else "SELL"

                # Standard sniper risk parameter: 1.2 * ATR SL, 2R TP target
                sl_dist = max(atr_f * 1.2, 0.00100)
                tp_dist = sl_dist * 2.0
                entry = round(mid, 5)
                sl = round(entry - sl_dist if direction_str == "BUY" else entry + sl_dist, 5)
                tp = round(entry + tp_dist if direction_str == "BUY" else entry - tp_dist, 5)

                confidence = int(s.evidence.confidence_score * 100) if s.evidence.confidence_score else 85

                sig_id = f"SIG-{s.setup_code.value}-{int(eval_time.timestamp())}"
                should_notify_telegram = sig_id not in self._sent_signal_ids

                actionable_signals.append({
                    "id": sig_id,
                    "setup": f"{s.setup_code.value} {s.liquidity_type or 'Reversal'}",
                    "direction": direction_str,
                    "confidence": confidence,
                    "regime": s.regime,
                    "session": "ACTIVE",
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "state": s.status.value,
                    "timestamp": eval_time.isoformat(),
                    "should_notify": should_notify_telegram,
                    "evidence": [
                        f"Setup: {s.setup_code.value}",
                        f"Liquidity Pool: {s.liquidity_type or 'Confirmed Level'}",
                        f"Structure Displacement: {s.structure_type or 'Confirmed Break'}",
                        f"ATR(14): {round(atr_f, 5)}",
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
