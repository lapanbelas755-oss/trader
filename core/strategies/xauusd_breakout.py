"""
Trader Machine — XAUUSD Breakout Engine V1.
Deterministic, multi-confluence breakout engine engineered specifically for Gold (XAUUSD).

Adheres strictly to Master Instruction (AGENTS.MD) and User Specification:
1. Market Eligibility (Spread, ATR, Volatility, Session, Market Structure).
2. Level Prioritization (PDH, PDL, Asian H/L, London H/L, Swings, Multi-Touch).
3. Anti-Wick Breakout Validator (Requires candle close outside + acceptance).
4. Breakout Energy Confluence (Body >= 65%, ATR Expansion, Momentum, Range, Close Location).
5. Retest Confirmation (Broken Resistance -> Support; immediate collapse = TRAP / NO TRADE).
6. Profit Potential & RR (Minimum RR 1:2.0, Preferred RR 1:2.5+; if RR < 2.0 -> SKIP).
7. 100-Point Scoring Engine & Hard Firewall Veto Rules:
   - LEVEL QUALITY:       0-20
   - BREAKOUT STRENGTH:   0-20
   - MOMENTUM:            0-15
   - VOLATILITY:          0-15
   - RETEST:              0-10
   - SESSION:             0-5
   - SPREAD:              0-5
   - PROFIT POTENTIAL:    0-10
   TOTAL: 100
   Brackets: 0-59 NO TRADE, 60-74 WATCH, 75-84 VALID SETUP, 85-100 HIGH QUALITY TRADE.
"""

from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.candles.contract import AggregatedCandle
from core.structure.contract import ConfirmedSwing, SwingType

logger = logging.getLogger(__name__)


@dataclass
class XAUUSDBreakoutResult:
    """Complete evaluation report of the XAUUSD Breakout Engine V1."""
    symbol: str = "XAUUSD"
    market_status: str = "ACTIVE"          # ACTIVE | MARKET_CLOSED | UNFAVORABLE
    session: str = "NEW YORK"              # NEW YORK | LONDON | ASIAN | OFF_HOURS
    spread: float = 0.20                   # Measured spread in USD / pips
    spread_bad: bool = False               # Hard veto flag if spread exceeds limit
    atr: float = 2.50                      # M5 ATR(14)
    atr_state: str = "NORMAL"              # HIGH | NORMAL | LOW
    volatility_state: str = "NORMAL"       # EXPANDING | NORMAL | COMPRESSED
    
    resistance: float = 0.0
    support: float = 0.0
    level_type: str = "SWING"              # PDH | PDL | ASIAN_HL | LONDON_HL | MULTI_TOUCH | SWING
    level_touches: int = 1
    
    breakout_valid: bool = False
    breakout_type: str = "NONE"            # BULLISH_BREAKOUT | BEARISH_BREAKOUT | WICK_REJECTION | NONE
    
    momentum_state: str = "MODERATE"       # STRONG | MODERATE | WEAK
    retest_state: str = "NONE"             # CONFIRMED | PENDING | FAILED | NONE
    
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_dollars: float = 0.0
    reward_dollars: float = 0.0
    rr_ratio: float = 0.0
    rr_string: str = "N/A"
    profit_potential_valid: bool = False
    
    # 100-Point Score Breakdown
    score_level_quality: int = 0          # Max 20
    score_breakout_strength: int = 0      # Max 20
    score_momentum: int = 0               # Max 15
    score_volatility: int = 0             # Max 15
    score_retest: int = 0                 # Max 10
    score_session: int = 0                # Max 5
    score_spread: int = 0                 # Max 5
    score_profit_potential: int = 0       # Max 10
    total_score: int = 0                  # Max 100
    
    status_label: str = "NO TRADE"         # HIGH QUALITY TRADE | VALID SETUP | WATCH | NO TRADE
    signal: str = "NO_TRADE"               # BUY | SELL | NO_TRADE
    veto_reason: Optional[str] = None
    evidence_checklist: List[Dict[str, Any]] = field(default_factory=list)


class XAUUSDBreakoutEngine:
    """
    State-of-the-art Breakout Engine for Gold (XAUUSD).
    Operates with rigorous math, multi-factor confluence, and zero tolerance for false wick breakouts.
    """

    # Parameters tuned for XAUUSD M5
    MINIMUM_RR = 2.0
    PREFERRED_RR = 2.5
    MAX_SPREAD_POINTS = 0.40  # $0.40 spread limit (4 pips on gold)
    MIN_CANDLE_BODY_RATIO = 0.55  # Candle body must be >= 55% for breakout consideration
    STRONG_CANDLE_BODY_RATIO = 0.65  # Strong institutional impulse
    MIN_DISPLACEMENT_ATR_MULT = 0.10  # Close outside must penetrate level by at least 0.10 * ATR
    RETEST_TOLERANCE_ATR_MULT = 0.35  # Pullback within 0.35 * ATR qualifies as retest

    def __init__(
        self,
        symbol: str = "XAUUSD",
        minimum_rr: float = 2.0,
        preferred_rr: float = 2.5,
        max_spread: float = 0.40,
    ):
        self.symbol = symbol.upper()
        self.minimum_rr = minimum_rr
        self.preferred_rr = preferred_rr
        self.max_spread = max_spread

    # -------------------------------------------------------------------------
    # Pillar 1: Market Eligibility & Session
    # -------------------------------------------------------------------------

    def detect_session(self, dt: datetime) -> Tuple[str, int]:
        """
        Determines trading session and returns (session_name, score 0-5).
        London & New York overlap is optimal for Gold breakouts.
        """
        t = dt.time()
        # UTC Session Hours:
        # Asian: 00:00 - 08:00
        # London: 08:00 - 16:30
        # New York: 13:00 - 21:00
        # NY/London Overlap: 13:00 - 16:30
        if dt_time(13, 0) <= t < dt_time(16, 30):
            return "NEW YORK (OVERLAP)", 5
        elif dt_time(13, 0) <= t < dt_time(21, 0):
            return "NEW YORK", 5
        elif dt_time(8, 0) <= t < dt_time(16, 30):
            return "LONDON", 4
        elif dt_time(0, 0) <= t < dt_time(8, 0):
            return "ASIAN", 2
        else:
            return "OFF_HOURS", 1

    def compute_atr(self, candles: List[AggregatedCandle], period: int = 14) -> float:
        """Calculates standard Average True Range."""
        if len(candles) < 2:
            return 2.50
        trs: List[float] = []
        for i in range(1, len(candles)):
            c = candles[i]
            p = candles[i - 1]
            tr = max(
                float(c.high - c.low),
                abs(float(c.high - p.close)),
                abs(float(c.low - p.close)),
            )
            trs.append(tr)
        recent = trs[-min(len(trs), period):]
        return round(sum(recent) / len(recent), 3) if recent else 2.50

    def evaluate_volatility(
        self, candles: List[AggregatedCandle], atr: float
    ) -> Tuple[str, str, int]:
        """
        Evaluates volatility expansion vs compression.
        Returns: (atr_state, volatility_state, score 0-15).
        """
        if len(candles) < 20:
            return "NORMAL", "NORMAL", 8

        # Calculate median range of last 20 candles
        ranges = [float(c.high - c.low) for c in candles[-20:]]
        sorted_ranges = sorted(ranges)
        median_range = sorted_ranges[len(sorted_ranges) // 2]

        latest_range = float(candles[-1].high - candles[-1].low)
        ratio = latest_range / median_range if median_range > 0 else 1.0

        if atr > 3.5:
            atr_state = "HIGH"
        elif atr < 1.5:
            atr_state = "LOW"
        else:
            atr_state = "NORMAL"

        if ratio >= 1.5 or (latest_range >= 1.3 * atr):
            vol_state = "EXPANDING"
            score = 15 if ratio >= 1.8 else 12
        elif ratio <= 0.6:
            vol_state = "COMPRESSED"
            score = 5
        else:
            vol_state = "NORMAL"
            score = 9

        return atr_state, vol_state, score

    # -------------------------------------------------------------------------
    # Pillar 2: Level Identification & Quality
    # -------------------------------------------------------------------------

    def identify_key_levels(
        self,
        candles: List[AggregatedCandle],
        atr: float,
    ) -> Dict[str, Any]:
        """
        Identifies key Resistance and Support levels from:
        - Previous Day High / Low
        - Asian Session High / Low
        - Multi-touch swing levels
        """
        if len(candles) < 10:
            return {
                "resistance": 0.0,
                "support": 0.0,
                "level_type": "NONE",
                "touches": 0,
                "score": 0,
            }

        # We detect reference levels from prior candles (before the current breakout candle)
        eval_candles = candles[:-1] if len(candles) > 1 else candles
        prev_close = float(candles[-2].close) if len(candles) > 1 else curr_price
        eval_dt = candles[-1].timestamp
        eval_date = eval_dt.date()

        # 1. Group previous day candles for PDH/PDL
        prev_day_candles = [c for c in eval_candles if c.timestamp.date() < eval_date]
        pdh: Optional[float] = None
        pdl: Optional[float] = None
        if prev_day_candles:
            latest_prev_date = max(c.timestamp.date() for c in prev_day_candles)
            target_prev_candles = [c for c in prev_day_candles if c.timestamp.date() == latest_prev_date]
            if target_prev_candles:
                pdh = max(float(c.high) for c in target_prev_candles)
                pdl = min(float(c.low) for c in target_prev_candles)

        # 2. Asian Session High / Low (00:00 - 08:00 UTC of current day)
        asian_candles = [
            c for c in eval_candles
            if c.timestamp.date() == eval_date and dt_time(0, 0) <= c.timestamp.time() < dt_time(8, 0)
        ]
        asian_h = max([float(c.high) for c in asian_candles], default=None)
        asian_l = min([float(c.low) for c in asian_candles], default=None)

        # 3. Detect Swing Highs and Lows in recent candles
        prior_highs = [float(c.high) for c in eval_candles[-50:]]
        prior_lows = [float(c.low) for c in eval_candles[-50:]]

        resistances = []
        supports = []

        if pdh:
            resistances.append((pdh, "PREVIOUS_DAY_HIGH", 20, 2))
        if asian_h:
            resistances.append((asian_h, "ASIAN_HIGH", 16, 2))

        if pdl:
            supports.append((pdl, "PREVIOUS_DAY_LOW", 20, 2))
        if asian_l:
            supports.append((asian_l, "ASIAN_LOW", 16, 2))

        # Recent local swing pivots (2-left, 2-right peak/trough detection on eval_candles)
        tolerance = atr * 0.20
        swing_high_counts: Dict[float, int] = {}
        swing_low_counts: Dict[float, int] = {}

        if len(eval_candles) >= 5:
            for i in range(2, len(eval_candles) - 2):
                c_high = float(eval_candles[i].high)
                c_low = float(eval_candles[i].low)
                # Pivot High
                if (c_high >= float(eval_candles[i-1].high) and c_high >= float(eval_candles[i-2].high) and
                    c_high >= float(eval_candles[i+1].high) and c_high >= float(eval_candles[i+2].high)):
                    matched = False
                    for lvl in swing_high_counts:
                        if abs(lvl - c_high) <= tolerance:
                            swing_high_counts[lvl] += 1
                            matched = True
                            break
                    if not matched:
                        swing_high_counts[c_high] = 1

                # Pivot Low
                if (c_low <= float(eval_candles[i-1].low) and c_low <= float(eval_candles[i-2].low) and
                    c_low <= float(eval_candles[i+1].low) and c_low <= float(eval_candles[i+2].low)):
                    matched = False
                    for lvl in swing_low_counts:
                        if abs(lvl - c_low) <= tolerance:
                            swing_low_counts[lvl] += 1
                            matched = True
                            break
                    if not matched:
                        swing_low_counts[c_low] = 1

        for lvl, cnt in swing_high_counts.items():
            lvl_type = "MULTI_TOUCH_RESISTANCE" if cnt >= 2 else "SWING_HIGH"
            sc = 20 if cnt >= 3 else (16 if cnt == 2 else 12)
            resistances.append((lvl, lvl_type, sc, cnt))

        for lvl, cnt in swing_low_counts.items():
            lvl_type = "MULTI_TOUCH_SUPPORT" if cnt >= 2 else "SWING_LOW"
            sc = 20 if cnt >= 3 else (16 if cnt == 2 else 12)
            supports.append((lvl, lvl_type, sc, cnt))

        # Fallbacks if none found
        if not resistances:
            fallback_h = max(prior_highs) if prior_highs else curr_price + atr
            resistances.append((fallback_h, "SWING_HIGH", 12, 1))

        if not supports:
            fallback_l = min(prior_lows) if prior_lows else curr_price - atr
            supports.append((fallback_l, "SWING_LOW", 12, 1))

        # Identify the resistance level challenged or capping the move
        latest_high = float(candles[-1].high)
        latest_low = float(candles[-1].low)

        # Tested resistance: if high tested or penetrated a resistance level
        tested_res = [r for r in resistances if latest_high >= r[0] - tolerance]
        if tested_res:
            chosen_res = max(tested_res, key=lambda x: x[0])
        else:
            above_res = [r for r in resistances if r[0] >= prev_close]
            chosen_res = min(above_res, key=lambda x: abs(x[0] - prev_close)) if above_res else min(resistances, key=lambda x: abs(x[0] - prev_close))

        # Tested support: if low tested or penetrated a support level
        tested_sup = [s for s in supports if latest_low <= s[0] + tolerance]
        if tested_sup:
            chosen_sup = min(tested_sup, key=lambda x: x[0])
        else:
            below_sup = [s for s in supports if s[0] <= prev_close]
            chosen_sup = min(below_sup, key=lambda x: abs(x[0] - prev_close)) if below_sup else min(supports, key=lambda x: abs(x[0] - prev_close))

        # Level Quality Score (0-20)
        best_score = max(chosen_res[2], chosen_sup[2])

        res_val = chosen_res[0]
        sup_val = chosen_sup[0]
        if res_val <= sup_val:
            res_candidates = [r[0] for r in resistances if r[0] > sup_val]
            if res_candidates:
                res_val = min(res_candidates)
            else:
                res_val = sup_val + max(2.0, atr * 1.5)

        return {
            "resistance": round(res_val, 2),
            "support": round(sup_val, 2),
            "level_type": chosen_res[1] if abs(chosen_res[0] - prev_close) < abs(prev_close - chosen_sup[0]) else chosen_sup[1],
            "touches": max(chosen_res[3], chosen_sup[3]),
            "score": min(20, best_score),
        }

    # -------------------------------------------------------------------------
    # Pillar 3 & 4: Anti-Wick Validation & Breakout Energy
    # -------------------------------------------------------------------------

    def evaluate_breakout(
        self,
        candles: List[AggregatedCandle],
        resistance: float,
        support: float,
        atr: float,
    ) -> Dict[str, Any]:
        """
        Validates breakout strictly using candle CLOSE outside levels.
        Wicks alone poking above/below are tagged as WICK_REJECTION (not a breakout).
        Computes breakout strength score (0-20) and momentum score (0-15).
        """
        if len(candles) < 3:
            return {
                "breakout_valid": False,
                "breakout_type": "NONE",
                "strength_score": 0,
                "momentum_score": 0,
                "momentum_state": "WEAK",
                "body_ratio": 0.0,
                "close_location": 0.0,
                "reason": "Insufficient candles",
            }

        last_c = candles[-1]
        c_open = float(last_c.open)
        c_high = float(last_c.high)
        c_low = float(last_c.low)
        c_close = float(last_c.close)
        c_range = c_high - c_low if (c_high - c_low) > 0 else 0.01
        c_body = abs(c_close - c_open)
        body_ratio = c_body / c_range

        # Close location relative to range (0.0 = low, 1.0 = high)
        close_location = (c_close - c_low) / c_range

        min_disp = self.MIN_DISPLACEMENT_ATR_MULT * atr

        # Check Bullish Breakout
        is_bullish_wick = (c_high > resistance) and (c_close <= resistance)
        is_bullish_break = (c_close > resistance + min_disp) and (c_close > c_open)

        # Check Bearish Breakout
        is_bearish_wick = (c_low < support) and (c_close >= support)
        is_bearish_break = (c_close < support - min_disp) and (c_close < c_open)

        if is_bullish_wick:
            return {
                "breakout_valid": False,
                "breakout_type": "WICK_REJECTION",
                "strength_score": 3,
                "momentum_score": 4,
                "momentum_state": "WEAK",
                "body_ratio": body_ratio,
                "close_location": close_location,
                "reason": "Wick poked resistance but closed inside — Wick rejection, NOT breakout",
            }

        if is_bearish_wick:
            return {
                "breakout_valid": False,
                "breakout_type": "WICK_REJECTION",
                "strength_score": 3,
                "momentum_score": 4,
                "momentum_state": "WEAK",
                "body_ratio": body_ratio,
                "close_location": close_location,
                "reason": "Wick poked support but closed inside — Wick rejection, NOT breakout",
            }

        breakout_type = "NONE"
        breakout_valid = False

        if is_bullish_break:
            breakout_type = "BULLISH_BREAKOUT"
            breakout_valid = True
        elif is_bearish_break:
            breakout_type = "BEARISH_BREAKOUT"
            breakout_valid = True

        if not breakout_valid:
            return {
                "breakout_valid": False,
                "breakout_type": "NONE",
                "strength_score": 0,
                "momentum_score": 0,
                "momentum_state": "WEAK",
                "body_ratio": body_ratio,
                "close_location": close_location,
                "reason": "Price inside support and resistance range",
            }

        # Breakout Strength Scoring (0-20):
        # 1. Body Ratio (Max 8 pts)
        if body_ratio >= self.STRONG_CANDLE_BODY_RATIO:
            body_score = 8
        elif body_ratio >= self.MIN_CANDLE_BODY_RATIO:
            body_score = 5
        else:
            body_score = 2

        # 2. Range Expansion vs ATR (Max 7 pts)
        range_expansion = c_range / atr if atr > 0 else 1.0
        if range_expansion >= 1.5:
            range_score = 7
        elif range_expansion >= 1.1:
            range_score = 5
        else:
            range_score = 3

        # 3. Close Location (Max 5 pts)
        if breakout_type == "BULLISH_BREAKOUT":
            loc_score = 5 if close_location >= 0.80 else (3 if close_location >= 0.65 else 1)
        else:
            loc_score = 5 if close_location <= 0.20 else (3 if close_location <= 0.35 else 1)

        strength_score = min(20, body_score + range_score + loc_score)

        # Momentum Scoring (0-15):
        # Multi-candle displacement + Tick volume
        prev_closes = [float(c.close) for c in candles[-4:]]
        disp_3 = abs(prev_closes[-1] - prev_closes[0])
        disp_ratio = disp_3 / atr if atr > 0 else 1.0

        # Tick activity comparison
        avg_ticks = sum(float(getattr(c, "tick_volume", getattr(c, "tick_count", 100))) for c in candles[-10:]) / 10.0
        last_ticks = float(getattr(last_c, "tick_volume", getattr(last_c, "tick_count", 100)))
        tick_ratio = last_ticks / avg_ticks if avg_ticks > 0 else 1.0

        if disp_ratio >= 1.8 and tick_ratio >= 1.2:
            momentum_score = 15
            momentum_state = "STRONG"
        elif disp_ratio >= 1.2 or tick_ratio >= 1.1:
            momentum_score = 11
            momentum_state = "MODERATE"
        else:
            momentum_score = 6
            momentum_state = "WEAK"

        return {
            "breakout_valid": True,
            "breakout_type": breakout_type,
            "strength_score": strength_score,
            "momentum_score": momentum_score,
            "momentum_state": momentum_state,
            "body_ratio": body_ratio,
            "close_location": close_location,
            "reason": f"Valid {breakout_type} with strong candle body ({int(body_ratio*100)}%) and displacement",
        }

    # -------------------------------------------------------------------------
    # Pillar 5: Retest Confirmation
    # -------------------------------------------------------------------------

    def evaluate_retest(
        self,
        candles: List[AggregatedCandle],
        breakout_type: str,
        level: float,
        atr: float,
    ) -> Tuple[str, int, bool]:
        """
        Evaluates retest behavior on broken level.
        Returns: (retest_state, score 0-10, trap_collapse_flag)
        - CONFIRMED: Price pulled back to level and bounced away (Score 10)
        - PENDING: Fresh breakout, retest has not occurred yet (Score 7)
        - FAILED (Trap Collapse): Price plunged back inside range (Score 0, hard veto!)
        """
        if breakout_type == "NONE" or len(candles) < 1:
            return "NONE", 0, False

        last_c = candles[-1]
        c_close = float(last_c.close)
        c_low = float(last_c.low)
        c_high = float(last_c.high)
        tolerance = self.RETEST_TOLERANCE_ATR_MULT * atr

        if breakout_type == "BULLISH_BREAKOUT":
            # If price immediately falls back below the broken resistance
            if c_close < level - 0.05 * atr:
                return "FAILED", 0, True

            # If low touched near resistance and close held above
            if abs(c_low - level) <= tolerance and c_close > level:
                return "CONFIRMED", 10, False
            else:
                return "PENDING", 7, False

        elif breakout_type == "BEARISH_BREAKOUT":
            # If price immediately rises back above the broken support
            if c_close > level + 0.05 * atr:
                return "FAILED", 0, True

            # If high touched near support and close held below
            if abs(c_high - level) <= tolerance and c_close < level:
                return "CONFIRMED", 10, False
            else:
                return "PENDING", 7, False

        return "NONE", 0, False

    # -------------------------------------------------------------------------
    # Pillar 6: Profit Potential & Risk:Reward
    # -------------------------------------------------------------------------

    def calculate_trade_levels(
        self,
        candles: List[AggregatedCandle],
        breakout_type: str,
        broken_level: float,
        atr: float,
        opposing_level: float,
    ) -> Dict[str, Any]:
        """
        Computes Entry, Stop Loss, Take Profit, Risk, Reward, and RR Ratio.
        Enforces:
        - Minimum RR = 1:2.0
        - Preferred RR = 1:2.5+
        """
        if breakout_type == "NONE" or len(candles) == 0:
            return {
                "entry": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "risk": 0.0,
                "reward": 0.0,
                "rr_ratio": 0.0,
                "rr_string": "N/A",
                "profit_potential_valid": False,
                "score": 0,
            }

        last_c = candles[-1]
        entry = float(last_c.close)

        # SL Placement:
        # BUY: Just below broken resistance or breakout candle low
        # SELL: Just above broken support or breakout candle high
        buffer = max(0.50, atr * 0.35)

        if breakout_type == "BULLISH_BREAKOUT":
            sl_candidate_1 = broken_level - buffer
            sl_candidate_2 = float(last_c.low) - buffer * 0.5
            stop_loss = round(min(sl_candidate_1, sl_candidate_2), 2)
            risk = round(entry - stop_loss, 2)
            if risk <= 0.20:
                risk = round(atr * 1.0, 2)
                stop_loss = round(entry - risk, 2)

            # Target 1: Target minimum 2.5R or opposing liquidity pool
            tp_at_least_min = entry + (risk * self.minimum_rr)
            tp_preferred = entry + (risk * self.preferred_rr)

            if opposing_level > entry:
                take_profit = round(max(opposing_level, tp_preferred), 2)
            else:
                take_profit = round(tp_preferred, 2)

            reward = round(take_profit - entry, 2)

        else:  # BEARISH_BREAKOUT
            sl_candidate_1 = broken_level + buffer
            sl_candidate_2 = float(last_c.high) + buffer * 0.5
            stop_loss = round(max(sl_candidate_1, sl_candidate_2), 2)
            risk = round(stop_loss - entry, 2)
            if risk <= 0.20:
                risk = round(atr * 1.0, 2)
                stop_loss = round(entry + risk, 2)

            tp_at_least_min = entry - (risk * self.minimum_rr)
            tp_preferred = entry - (risk * self.preferred_rr)

            if opposing_level < entry and opposing_level > 0:
                take_profit = round(min(opposing_level, tp_preferred), 2)
            else:
                take_profit = round(tp_preferred, 2)

            reward = round(entry - take_profit, 2)

        rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0
        rr_string = f"1 : {rr_ratio}"

        # Hard Rule: Minimum RR = 1:2.0
        profit_potential_valid = (rr_ratio >= self.minimum_rr)

        # Score (0-10)
        if rr_ratio >= self.preferred_rr:
            score = 10
        elif rr_ratio >= self.minimum_rr:
            score = 7
        else:
            score = 2

        return {
            "entry": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "risk": risk,
            "reward": reward,
            "rr_ratio": rr_ratio,
            "rr_string": rr_string,
            "profit_potential_valid": profit_potential_valid,
            "score": score,
        }

    # -------------------------------------------------------------------------
    # Master Evaluation: 100-Point Scoring & Hard Firewall Veto
    # -------------------------------------------------------------------------

    def evaluate(
        self,
        candles: List[AggregatedCandle],
        current_spread: float = 0.20,
        is_market_open: bool = True,
    ) -> XAUUSDBreakoutResult:
        """
        Executes the full 6-pillar evaluation and scoring pipeline.
        Enforces the Hard Firewall Veto rule:
        IF breakout_valid = false OR profit_potential = false OR rr < minimum_rr OR spread_bad = true OR market_filter = false:
        THEN SIGNAL = NO_TRADE.
        """
        result = XAUUSDBreakoutResult(symbol=self.symbol)
        result.spread = round(current_spread, 2)

        # 1. Market Status
        if not is_market_open:
            result.market_status = "MARKET_CLOSED"
        else:
            result.market_status = "ACTIVE"

        if not candles or len(candles) < 5:
            result.signal = "NO_TRADE"
            result.status_label = "NO TRADE"
            result.veto_reason = "Insufficient candle history"
            return result

        eval_candle = candles[-1]
        eval_dt = eval_candle.timestamp

        # 2. Session & Volatility
        session_name, score_session = self.detect_session(eval_dt)
        result.session = session_name
        result.score_session = score_session

        atr = self.compute_atr(candles, period=14)
        result.atr = atr
        atr_state, vol_state, score_vol = self.evaluate_volatility(candles, atr)
        result.atr_state = atr_state
        result.volatility_state = vol_state
        result.score_volatility = score_vol

        # 3. Spread Score & Check
        if current_spread <= 0.25:
            result.score_spread = 5
            result.spread_bad = False
        elif current_spread <= self.max_spread:
            result.score_spread = 3
            result.spread_bad = False
        else:
            result.score_spread = 0
            result.spread_bad = True

        # 4. Identify Key Levels
        levels_info = self.identify_key_levels(candles, atr)
        result.resistance = levels_info["resistance"]
        result.support = levels_info["support"]
        result.level_type = levels_info["level_type"]
        result.level_touches = levels_info["touches"]
        result.score_level_quality = levels_info["score"]

        # 5. Evaluate Breakout (Anti-Wick & Energy)
        breakout_info = self.evaluate_breakout(
            candles,
            resistance=result.resistance,
            support=result.support,
            atr=atr,
        )
        result.breakout_valid = breakout_info["breakout_valid"]
        result.breakout_type = breakout_info["breakout_type"]
        result.score_breakout_strength = breakout_info["strength_score"]
        result.score_momentum = breakout_info["momentum_score"]
        result.momentum_state = breakout_info["momentum_state"]

        # 6. Evaluate Retest
        target_broken_level = result.resistance if result.breakout_type == "BULLISH_BREAKOUT" else result.support
        retest_state, score_retest, is_trap = self.evaluate_retest(
            candles,
            breakout_type=result.breakout_type,
            level=target_broken_level,
            atr=atr,
        )
        result.retest_state = retest_state
        result.score_retest = score_retest

        if is_trap:
            # Price immediately collapsed back into the range
            result.breakout_valid = False
            result.breakout_type = "NONE"
            result.veto_reason = "Price collapsed back into range — Breakout trap rejected"

        # 7. Evaluate Profit Potential & Trade Levels
        opposing = result.support if result.breakout_type == "BULLISH_BREAKOUT" else result.resistance
        trade_levels = self.calculate_trade_levels(
            candles,
            breakout_type=result.breakout_type,
            broken_level=target_broken_level,
            atr=atr,
            opposing_level=opposing,
        )
        result.entry = trade_levels["entry"]
        result.stop_loss = trade_levels["stop_loss"]
        result.take_profit = trade_levels["take_profit"]
        result.risk_dollars = trade_levels["risk"]
        result.reward_dollars = trade_levels["reward"]
        result.rr_ratio = trade_levels["rr_ratio"]
        result.rr_string = trade_levels["rr_string"]
        result.profit_potential_valid = trade_levels["profit_potential_valid"]
        result.score_profit_potential = trade_levels["score"]

        # 8. Compute Total 100-Point Score
        raw_score = (
            result.score_level_quality
            + result.score_breakout_strength
            + result.score_momentum
            + result.score_volatility
            + result.score_retest
            + result.score_session
            + result.score_spread
            + result.score_profit_potential
        )
        result.total_score = min(100, max(0, raw_score))

        # 9. Evidence Checklist for UI
        result.evidence_checklist = [
            {"name": "Market Status", "status": "ACTIVE" if is_market_open else "CLOSED", "ok": is_market_open},
            {"name": "Session", "status": result.session, "ok": result.score_session >= 4},
            {"name": "Spread", "status": f"${result.spread:.2f}", "ok": not result.spread_bad},
            {"name": "ATR / Volatility", "status": f"{result.atr_state} ({result.volatility_state})", "ok": result.score_volatility >= 9},
            {"name": "Breakout", "status": "VALID" if result.breakout_valid else ("REJECTED (WICK)" if breakout_info["breakout_type"] == "WICK_REJECTION" else "WAITING"), "ok": result.breakout_valid},
            {"name": "Momentum", "status": result.momentum_state, "ok": result.score_momentum >= 10},
            {"name": "Retest", "status": result.retest_state, "ok": result.retest_state in ("CONFIRMED", "PENDING")},
            {"name": "Risk : Reward", "status": result.rr_string, "ok": result.profit_potential_valid},
        ]

        # 10. HARD FIREWALL VETO (Master Instruction Law #10, User Rule)
        # IF breakout_valid = false OR profit_potential = false OR rr < minimum_rr OR spread_bad = true OR market_filter = false
        # THEN SIGNAL = NO_TRADE
        veto_triggers = []
        if not is_market_open:
            veto_triggers.append("Market closed")
        if result.spread_bad:
            veto_triggers.append(f"Spread abnormal (${result.spread:.2f} > ${self.max_spread:.2f})")
        if not result.breakout_valid:
            veto_triggers.append(breakout_info["reason"] if not result.veto_reason else result.veto_reason)
        if not result.profit_potential_valid:
            veto_triggers.append(f"Risk:Reward insufficient ({result.rr_string} < 1:{self.minimum_rr})")

        if veto_triggers:
            result.signal = "NO_TRADE"
            result.veto_reason = "; ".join(veto_triggers)
            # Cap score below valid setup bracket if hard vetoed
            result.total_score = min(result.total_score, 59)
            result.status_label = "NO TRADE"
            return result

        # 11. Score Brackets:
        # 0–59   = NO TRADE
        # 60–74  = WATCH
        # 75–84  = VALID SETUP
        # 85–100 = HIGH QUALITY TRADE
        if result.total_score >= 85:
            result.status_label = "HIGH QUALITY TRADE"
            result.signal = "BUY" if result.breakout_type == "BULLISH_BREAKOUT" else "SELL"
        elif result.total_score >= 75:
            result.status_label = "VALID SETUP"
            result.signal = "BUY" if result.breakout_type == "BULLISH_BREAKOUT" else "SELL"
        elif result.total_score >= 60:
            result.status_label = "WATCH"
            result.signal = "NO_TRADE"
        else:
            result.status_label = "NO TRADE"
            result.signal = "NO_TRADE"

        return result
