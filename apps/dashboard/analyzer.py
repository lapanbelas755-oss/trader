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
from core.structure.smc import SMCEngine
from core.strategies.xauusd_breakout import XAUUSDBreakoutEngine, XAUUSDBreakoutResult

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
        self.smc_engine = SMCEngine()
        self.xauusd_engine = XAUUSDBreakoutEngine(symbol=self.symbol) if self.symbol == "XAUUSD" else None
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

    def analyze(
        self,
        raw_candles: List[Dict[str, Any]],
        current_spread: float = 0.20,
        is_market_open: bool = True,
    ) -> Dict[str, Any]:
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

        # 6. Extract Smart Money Concepts (SMC) Structure Overlays
        atr_f = float(atr)
        zigzag_points = self.smc_engine.extract_zigzag(classified_swings)
        msb_lines = self.smc_engine.extract_msb_lines(struct_events, candles)
        order_blocks = self.smc_engine.detect_order_blocks(candles, atr=atr_f)
        breaker_blocks = self.smc_engine.detect_breaker_blocks(candles, order_blocks)

        smc_data = {
            "zigzag": zigzag_points,
            "msb_lines": msb_lines,
            "order_blocks": order_blocks,
            "breaker_blocks": breaker_blocks,
        }

        # 7. Deduplicate & Validate Setups with Momentum & 1:3+ RR
        # Group candidates by (setup_code, direction) to eliminate redundant duplicates
        dedup_candidates: Dict[str, Any] = {}
        highest_status = "WAIT"

        for s in detected_records:
            if s.status in (SetupStatus.ARMED, SetupStatus.FIRE, SetupStatus.WATCH):
                direction_str = "BUY" if s.direction == SetupDirection.BULLISH else "SELL"
                key = f"{s.setup_code.value}_{direction_str}"
                
                # Keep the record with higher status ranking
                existing = dedup_candidates.get(key)
                if not existing:
                    dedup_candidates[key] = s
                else:
                    status_rank = {SetupStatus.FIRE: 3, SetupStatus.ARMED: 2, SetupStatus.WATCH: 1, SetupStatus.OBSERVE: 0}
                    if status_rank.get(s.status, 0) > status_rank.get(existing.status, 0):
                        dedup_candidates[key] = s

        actionable_signals: List[Dict[str, Any]] = []

        for key, s in dedup_candidates.items():
            direction_str = "BUY" if s.direction == SetupDirection.BULLISH else "SELL"
            mid = float(latest_c.close)
            
            # Momentum / Institutional Displacement Check
            momentum_info = self.smc_engine.check_momentum(candles, atr=atr_f, direction=direction_str)
            has_momentum = momentum_info["has_momentum"]

            # Determine final confirmed setup state:
            # A setup can ONLY enter FIRE state if genuine momentum / displacement is confirmed!
            # Otherwise, it stays ARMED waiting for momentum confirmation.
            current_status = s.status
            if current_status == SetupStatus.FIRE and not has_momentum:
                current_status = SetupStatus.ARMED

            if current_status in (SetupStatus.ARMED, SetupStatus.FIRE):
                if current_status.value == "FIRE":
                    highest_status = "FIRE"
                elif highest_status != "FIRE":
                    highest_status = current_status.value

                # Sniper Risk Management: Minimum 1:3 Risk:Reward (3R+)
                RR_RATIO = 3.0
                min_sl = 1.0 / self.pip_multiplier
                sl_dist = max(atr_f * 1.2, min_sl)
                tp_dist = sl_dist * RR_RATIO

                dec = len(str(mid).split(".")[1]) if "." in str(mid) else 5
                dec = min(dec, 5)
                entry = round(mid, dec)
                sl    = round(entry - sl_dist if direction_str == "BUY" else entry + sl_dist, dec)
                tp    = round(entry + tp_dist if direction_str == "BUY" else entry - tp_dist, dec)

                sl_pips = round(abs(entry - sl) * self.pip_multiplier, 1)
                tp_pips = round(abs(tp - entry) * self.pip_multiplier, 1)

                ev_items = s.evidence.to_evidence_items()
                confidence = min(95, 60 + len(ev_items) * 7) if ev_items else (90 if current_status == SetupStatus.FIRE else 80)
                if has_momentum:
                    confidence = min(95, confidence + 5)

                sig_id = f"SIG-{self.symbol}-{s.setup_code.value}-{int(eval_time.timestamp())}"

                now_ts = time.time()
                cooldown_key = f"{self.symbol}_{s.setup_code.value}"
                last_sent = self._cooldowns.get(cooldown_key, 0.0)
                is_fire = (current_status == SetupStatus.FIRE)
                can_alert = is_fire and has_momentum and (now_ts - last_sent > 900) and (sig_id not in self._sent_signal_ids)

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
                    "rr_ratio":   "1:3",
                    "momentum":   "CONFIRMED" if has_momentum else "PENDING",
                    "momentum_score": momentum_info.get("score", 0.0),
                    "state":      current_status.value,
                    "timestamp":  eval_time.isoformat(),
                    "should_notify": should_notify_telegram,
                    "evidence": [
                        f"Symbol: {self.symbol}",
                        f"Setup: {s.setup_code.value}",
                        f"Liquidity Pool: {raw_liq}",
                        f"Structure: {raw_struct}",
                        f"Risk/Reward: 1:3 RR ({sl_pips}p SL / {tp_pips}p TP)",
                        f"Momentum: {'CONFIRMED (' + str(momentum_info['score']) + 'x ATR)' if has_momentum else 'PENDING'}",
                        f"SMC Zones: {len(order_blocks)} OBs, {len(breaker_blocks)} BBs active",
                    ],
                })
            elif current_status == SetupStatus.WATCH and highest_status == "WAIT":
                highest_status = "WATCH"

        # 8. XAUUSD Breakout Engine V1 Integration
        xauusd_data = None
        if self.xauusd_engine and candles:
            try:
                breakout_res = self.xauusd_engine.evaluate(
                    candles,
                    current_spread=current_spread,
                    is_market_open=is_market_open,
                )
                xauusd_data = {
                    "symbol": breakout_res.symbol,
                    "market_status": breakout_res.market_status,
                    "session": breakout_res.session,
                    "spread": breakout_res.spread,
                    "spread_bad": breakout_res.spread_bad,
                    "atr": breakout_res.atr,
                    "atr_state": breakout_res.atr_state,
                    "volatility_state": breakout_res.volatility_state,
                    "resistance": breakout_res.resistance,
                    "support": breakout_res.support,
                    "level_type": breakout_res.level_type,
                    "level_touches": breakout_res.level_touches,
                    "breakout_valid": breakout_res.breakout_valid,
                    "breakout_type": breakout_res.breakout_type,
                    "momentum_state": breakout_res.momentum_state,
                    "retest_state": breakout_res.retest_state,
                    "entry": breakout_res.entry,
                    "stop_loss": breakout_res.stop_loss,
                    "take_profit": breakout_res.take_profit,
                    "risk_dollars": breakout_res.risk_dollars,
                    "reward_dollars": breakout_res.reward_dollars,
                    "rr_ratio": breakout_res.rr_ratio,
                    "rr_string": breakout_res.rr_string,
                    "profit_potential_valid": breakout_res.profit_potential_valid,
                    "score_level_quality": breakout_res.score_level_quality,
                    "score_breakout_strength": breakout_res.score_breakout_strength,
                    "score_momentum": breakout_res.score_momentum,
                    "score_volatility": breakout_res.score_volatility,
                    "score_retest": breakout_res.score_retest,
                    "score_session": breakout_res.score_session,
                    "score_spread": breakout_res.score_spread,
                    "score_profit_potential": breakout_res.score_profit_potential,
                    "total_score": breakout_res.total_score,
                    "status_label": breakout_res.status_label,
                    "signal": breakout_res.signal,
                    "veto_reason": breakout_res.veto_reason,
                    "evidence_checklist": breakout_res.evidence_checklist,
                }

                # If high quality breakout setup fires, promote to actionable signal
                if breakout_res.signal in ("BUY", "SELL") and breakout_res.total_score >= 75:
                    sig_id = f"SIG-XAUUSD-BREAKOUT-{int(eval_time.timestamp())}"
                    actionable_signals.append({
                        "id": sig_id,
                        "symbol": "XAUUSD",
                        "setup": f"XAU/USD Breakout ({breakout_res.total_score}/100)",
                        "direction": breakout_res.signal,
                        "confidence": breakout_res.total_score,
                        "regime": f"BREAKOUT_{breakout_res.volatility_state}",
                        "session": breakout_res.session,
                        "entry": breakout_res.entry,
                        "sl": breakout_res.stop_loss,
                        "tp": breakout_res.take_profit,
                        "sl_pips": round(breakout_res.risk_dollars * 10, 1),
                        "tp_pips": round(breakout_res.reward_dollars * 10, 1),
                        "rr_ratio": breakout_res.rr_string,
                        "momentum": breakout_res.momentum_state,
                        "momentum_score": float(breakout_res.score_momentum),
                        "state": "FIRE" if breakout_res.total_score >= 85 else "ARMED",
                        "timestamp": eval_time.isoformat(),
                        "should_notify": (breakout_res.total_score >= 85 and is_market_open),
                        "evidence": [
                            f"Score: {breakout_res.total_score}/100 ({breakout_res.status_label})",
                            f"Breakout: {breakout_res.breakout_type}",
                            f"Resistance: {breakout_res.resistance} | Support: {breakout_res.support}",
                            f"Risk/Reward: {breakout_res.rr_string}",
                            f"Retest: {breakout_res.retest_state}",
                        ],
                    })
                    if breakout_res.total_score >= 85:
                        highest_status = "FIRE"
                    elif highest_status != "FIRE":
                        highest_status = "ARMED"

            except Exception as ex:
                logger.error("Error running XAUUSDBreakoutEngine: %s", ex, exc_info=True)

        return {
            "status": highest_status,
            "reason": "Sniper waiting for strict confluence & momentum" if not actionable_signals else f"{len(actionable_signals)} verified setups active (1:3+ RR)",
            "signals": actionable_signals,
            "smc": smc_data,
            "xauusd_breakout": xauusd_data,
            "metrics": {
                "atr": float(atr),
                "swings_detected": len(swings),
                "structure_events": len(struct_events),
                "liquidity_levels": len(liquidity_levels),
                "order_blocks": len(order_blocks),
                "breaker_blocks": len(breaker_blocks),
                "last_close": float(latest_c.close),
                "eval_timestamp": eval_time.isoformat(),
            },
        }

    def mark_signal_sent(self, signal_id: str) -> None:
        """Records that a signal has been notified to Telegram to prevent duplicate alerts."""
        self._sent_signal_ids.add(signal_id)
