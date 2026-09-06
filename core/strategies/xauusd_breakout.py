"""
Trader Machine — XAUUSD Breakout Engine V1 (Master Specification).
Deterministic, multi-confluence breakout engine engineered strictly for Gold (XAUUSD).

Adheres strictly to Master Instruction (AGENTS.MD) and User Specification (Sections A through J):
A. MARKET FILTER: Spread, ATR, Volatility, Session, Structure Regime, News condition.
B. KEY LEVEL ENGINE: PDH, PDL, Asian H/L, London H/L, Swings, Range H/L (Quality Score 0-20).
C. BREAKOUT DETECTION: Differentiates 1. Wick, 2. Weak, 3. Valid, 4. Strong. Only 3 & 4 advance.
D. FALSE BREAKOUT FILTER: Re-entry trap, wick only, abnormal spread, low volatility vetoes.
E. RETEST ENGINE: S/R flip confirmation, pending state, strong breakout bypass.
F. MOMENTUM ENGINE: Multi-confluence (body ratio, ATR expansion, consecutive candles, tick volume).
G. VOLATILITY ENGINE: Compression -> Expansion detection.
H. PROFIT POTENTIAL ENGINE: Entry, SL, nearest opposing level, expected move, minimum 1:2.0 RR.
I. SCORE ENGINE: 100-point multi-factor score and configurable decision brackets.
J. SIGNAL RULE: Strict mandatory condition gates; detailed reasons on NO_TRADE.
"""

from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.candles.contract import AggregatedCandle, Timeframe
from core.structure.contract import ConfirmedSwing, SwingType

logger = logging.getLogger(__name__)


@dataclass
class XAUUSDConfig:
    """Configurable thresholds for XAU/USD Breakout Engine."""
    symbol: str = "XAUUSD"
    # Risk:Reward
    minimum_rr: float = 2.0
    preferred_rr: float = 2.5
    # Spread limit in USD ($0.40 = 4 pips on gold)
    max_spread: float = 0.40
    # Candle geometry thresholds
    min_candle_body_ratio: float = 0.55
    strong_candle_body_ratio: float = 0.65
    min_displacement_atr_mult: float = 0.10
    strong_displacement_atr_mult: float = 0.20
    retest_tolerance_atr_mult: float = 0.35
    # Scoring brackets
    minimum_live_score: int = 85
    valid_setup_score: int = 75
    watch_score: int = 60
    # Volatility compression lookback
    compression_lookback: int = 10
    compression_percentile: float = 0.25
    expansion_mult: float = 1.5


@dataclass
class XAUUSDBreakoutResult:
    """Complete evaluation report of the XAUUSD Breakout Engine V1."""
    symbol: str = "XAUUSD"
    market_status: str = "ACTIVE"          # ACTIVE | MARKET_CLOSED | UNFAVORABLE
    session: str = "NEW YORK"              # NEW YORK | LONDON | ASIAN | OFF_HOURS
    spread: float = 0.20                   # Measured spread in USD
    spread_bad: bool = False               # Hard veto flag if spread exceeds limit
    atr: float = 2.50                      # M5 ATR(14) in USD
    atr_state: str = "NORMAL"              # HIGH | NORMAL | LOW
    volatility_state: str = "NORMAL"       # EXPANDING | NORMAL | COMPRESSED
    market_regime: str = "RANGE"           # TREND_UP | TREND_DOWN | RANGE | COMPRESSION | EXPANSION
    
    resistance: float = 0.0
    support: float = 0.0
    level_type: str = "SWING"              # PDH | PDL | ASIAN_HL | LONDON_HL | RANGE_HL | MULTI_TOUCH | SWING
    level_touches: int = 1
    
    breakout_valid: bool = False
    breakout_type: str = "NONE"            # BULLISH_BREAKOUT | BEARISH_BREAKOUT | WICK_REJECTION | NONE
    breakout_category: str = "NONE"        # WICK_BREAKOUT | WEAK_BREAKOUT | VALID_BREAKOUT | STRONG_BREAKOUT | NONE
    
    momentum_state: str = "MODERATE"       # STRONG | MODERATE | WEAK
    retest_state: str = "NONE"             # CONFIRMED | PENDING | FAILED | NONE
    
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_dollars: float = 0.0
    reward_dollars: float = 0.0
    expected_move_dollars: float = 0.0
    expected_move_pips: float = 0.0
    target_opposing_level: float = 0.0
    rr_ratio: float = 0.0
    rr_string: str = "N/A"
    profit_potential_valid: bool = False
    
    # 100-Point Score Breakdown (Sections A through I)
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
    reasons_for_no_trade: List[str] = field(default_factory=list)
    no_trade_summary: str = ""
    evidence_checklist: List[Dict[str, Any]] = field(default_factory=list)


class XAUUSDBreakoutEngine:
    """
    XAU/USD ONLY Valid Breakout Engine V1.
    Engineered with mathematical multi-confluence, zero tolerance for false wicks,
    strict profit space validation, and configurable parameters.
    """

    def __init__(
        self,
        symbol: str = "XAUUSD",
        minimum_rr: float = 2.0,
        preferred_rr: float = 2.5,
        max_spread: float = 0.40,
        config: Optional[XAUUSDConfig] = None,
    ):
        if config is not None:
            self.cfg = config
        else:
            self.cfg = XAUUSDConfig(
                symbol=symbol.upper(),
                minimum_rr=minimum_rr,
                preferred_rr=preferred_rr,
                max_spread=max_spread,
            )
        self.symbol = self.cfg.symbol
        self.minimum_rr = self.cfg.minimum_rr
        self.preferred_rr = self.cfg.preferred_rr
        self.max_spread = self.cfg.max_spread

    def _ensure_candle(self, c: Any) -> Optional[AggregatedCandle]:
        """Ensures candle is an AggregatedCandle, converting from dict if necessary."""
        if isinstance(c, AggregatedCandle):
            return c
        elif isinstance(c, dict):
            try:
                raw_time = c.get("time") or c.get("timestamp")
                if isinstance(raw_time, (int, float)):
                    ts = datetime.fromtimestamp(raw_time, tz=timezone.utc)
                elif isinstance(raw_time, str):
                    ts = datetime.fromisoformat(raw_time)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = datetime.now(timezone.utc)
                o = Decimal(str(c.get("open", 0)))
                h = Decimal(str(c.get("high", 0)))
                l = Decimal(str(c.get("low", 0)))
                cl = Decimal(str(c.get("close", 0)))
                h = max(h, o, cl)
                l = min(l, o, cl)
                return AggregatedCandle(
                    symbol=self.symbol,
                    timeframe=Timeframe.M5,
                    timestamp=ts,
                    open=o,
                    high=h,
                    low=l,
                    close=cl,
                    tick_volume=int(c.get("volume", c.get("tick_volume", 100))),
                    real_volume=1000,
                    spread=Decimal("0.20"),
                    is_closed=True,
                )
            except Exception:
                return None
        return None

    # -------------------------------------------------------------------------
    # Section A: Market Filter & Session Guard
    # -------------------------------------------------------------------------

    def detect_session(self, dt: datetime) -> Tuple[str, int]:
        """
        Determines trading session and returns (session_name, score 0-5).
        London & New York overlap is prime liquidity for Gold breakouts.
        UTC Hours:
        - Asian: 00:00 - 08:00
        - London: 08:00 - 16:30
        - New York: 13:00 - 21:00
        - NY/London Overlap: 13:00 - 16:30
        """
        t = dt.time()
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

    def detect_market_regime(
        self, candles: List[AggregatedCandle], atr: float
    ) -> str:
        """Determines prevailing structural market regime."""
        if len(candles) < 15:
            return "RANGE"
        recent = candles[-15:]
        closes = [float(c.close) for c in recent]
        net_move = closes[-1] - closes[0]
        max_c = max(closes)
        min_c = min(closes)
        span = max_c - min_c

        # Compression check
        ranges = [float(c.high - c.low) for c in recent[-10:]]
        avg_range = sum(ranges) / len(ranges)
        if avg_range <= 0.6 * atr:
            return "COMPRESSION"

        if net_move >= 1.5 * atr:
            return "TREND_UP"
        elif net_move <= -1.5 * atr:
            return "TREND_DOWN"
        elif span >= 3.0 * atr:
            return "EXPANSION"
        else:
            return "RANGE"

    # -------------------------------------------------------------------------
    # Section G: Volatility Engine (Compression -> Expansion)
    # -------------------------------------------------------------------------

    def evaluate_volatility(
        self, candles: List[AggregatedCandle], atr: float
    ) -> Tuple[str, str, int, bool]:
        """
        Evaluates volatility expansion vs compression.
        Specifically hunts for: COMPRESSION -> EXPANSION.
        Returns: (atr_state, volatility_state, score 0-15, compression_breakout_flag).
        """
        if len(candles) < 20:
            return "NORMAL", "NORMAL", 8, False

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

        # Check prior compression (candles before the breakout)
        prior_ranges = [float(c.high - c.low) for c in candles[-11:-1]]
        was_compressed = False
        if prior_ranges:
            avg_prior = sum(prior_ranges) / len(prior_ranges)
            was_compressed = avg_prior <= 0.7 * atr

        if ratio >= self.cfg.expansion_mult or (latest_range >= 1.3 * atr):
            vol_state = "EXPANDING"
            # Compression followed immediately by expansion is premium institutional energy
            if was_compressed:
                score = 15
            elif ratio >= 1.8:
                score = 14
            else:
                score = 12
            return atr_state, vol_state, score, was_compressed
        elif ratio <= 0.6:
            vol_state = "COMPRESSED"
            score = 5
            return atr_state, vol_state, score, False
        else:
            vol_state = "NORMAL"
            score = 9
            return atr_state, vol_state, score, False

    # -------------------------------------------------------------------------
    # Section B: Key Level Engine (PDH, PDL, Asian, London, Swings, Range)
    # -------------------------------------------------------------------------

    def identify_key_levels(
        self,
        candles: List[AggregatedCandle],
        atr: float,
    ) -> Dict[str, Any]:
        """
        Identifies key Resistance and Support levels from:
        - Previous Day High (PDH) / Low (PDL)
        - Asian Session High / Low (00:00 - 08:00 UTC)
        - London Session High / Low (08:00 - 16:30 UTC)
        - Range High / Low
        - Swing Highs / Lows & Multi-touch clusters
        Computes Level Quality score (0-20).
        """
        if len(candles) < 10:
            return {
                "resistance": 0.0,
                "support": 0.0,
                "level_type": "NONE",
                "touches": 0,
                "score": 0,
                "details": {},
            }

        eval_candles = candles[:-1] if len(candles) > 1 else candles
        curr_price = float(candles[-1].close)
        prev_close = float(candles[-2].close) if len(candles) > 1 else curr_price
        eval_dt = candles[-1].timestamp
        eval_date = eval_dt.date()

        # 1. Previous Day High / Low
        prev_day_candles = [c for c in eval_candles if c.timestamp.date() < eval_date]
        pdh: Optional[float] = None
        pdl: Optional[float] = None
        if prev_day_candles:
            latest_prev_date = max(c.timestamp.date() for c in prev_day_candles)
            target_prev_candles = [c for c in prev_day_candles if c.timestamp.date() == latest_prev_date]
            if target_prev_candles:
                pdh = max(float(c.high) for c in target_prev_candles)
                pdl = min(float(c.low) for c in target_prev_candles)

        # 2. Asian Session High / Low (00:00 - 08:00 UTC)
        asian_candles = [
            c for c in eval_candles
            if c.timestamp.date() == eval_date and dt_time(0, 0) <= c.timestamp.time() < dt_time(8, 0)
        ]
        asian_h = max([float(c.high) for c in asian_candles], default=None)
        asian_l = min([float(c.low) for c in asian_candles], default=None)

        # 3. London Session High / Low (08:00 - 16:30 UTC)
        london_candles = [
            c for c in eval_candles
            if c.timestamp.date() == eval_date and dt_time(8, 0) <= c.timestamp.time() < dt_time(16, 30)
        ]
        london_h = max([float(c.high) for c in london_candles], default=None)
        london_l = min([float(c.low) for c in london_candles], default=None)

        # 4. Multi-touch swing pivots and range extremes
        prior_highs = [float(c.high) for c in eval_candles[-50:]]
        prior_lows = [float(c.low) for c in eval_candles[-50:]]
        range_h = max(prior_highs) if prior_highs else None
        range_l = min(prior_lows) if prior_lows else None

        resistances: List[Tuple[float, str, int, int]] = []
        supports: List[Tuple[float, str, int, int]] = []

        if pdh:
            resistances.append((pdh, "PREVIOUS_DAY_HIGH", 20, 2))
        if london_h and (not pdh or abs(london_h - pdh) > atr * 0.20):
            resistances.append((london_h, "LONDON_HIGH", 18, 2))
        if asian_h and (not pdh or abs(asian_h - pdh) > atr * 0.20):
            resistances.append((asian_h, "ASIAN_HIGH", 16, 2))

        if pdl:
            supports.append((pdl, "PREVIOUS_DAY_LOW", 20, 2))
        if london_l and (not pdl or abs(london_l - pdl) > atr * 0.20):
            supports.append((london_l, "LONDON_LOW", 18, 2))
        if asian_l and (not pdl or abs(asian_l - pdl) > atr * 0.20):
            supports.append((asian_l, "ASIAN_LOW", 16, 2))

        # Swing pivot detection (2-left, 2-right peak/trough)
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
            sc = 20 if cnt >= 3 else (17 if cnt == 2 else 13)
            resistances.append((lvl, lvl_type, sc, cnt))

        for lvl, cnt in swing_low_counts.items():
            lvl_type = "MULTI_TOUCH_SUPPORT" if cnt >= 2 else "SWING_LOW"
            sc = 20 if cnt >= 3 else (17 if cnt == 2 else 13)
            supports.append((lvl, lvl_type, sc, cnt))

        if range_h and not any(abs(r[0] - range_h) <= tolerance for r in resistances):
            resistances.append((range_h, "RANGE_HIGH", 15, 1))
        if range_l and not any(abs(s[0] - range_l) <= tolerance for s in supports):
            supports.append((range_l, "RANGE_LOW", 15, 1))

        # Fallbacks
        if not resistances:
            fallback_h = max(prior_highs) if prior_highs else curr_price + atr
            resistances.append((fallback_h, "SWING_HIGH", 12, 1))
        if not supports:
            fallback_l = min(prior_lows) if prior_lows else curr_price - atr
            supports.append((fallback_l, "SWING_LOW", 12, 1))

        latest_high = float(candles[-1].high)
        latest_low = float(candles[-1].low)

        # Match relevant resistance tested or nearest above
        tested_res = [r for r in resistances if latest_high >= r[0] - tolerance]
        if tested_res:
            chosen_res = max(tested_res, key=lambda x: x[0])
        else:
            above_res = [r for r in resistances if r[0] >= prev_close]
            chosen_res = min(above_res, key=lambda x: abs(x[0] - prev_close)) if above_res else min(resistances, key=lambda x: abs(x[0] - prev_close))

        # Match relevant support tested or nearest below
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

        chosen_type = chosen_res[1] if abs(chosen_res[0] - prev_close) < abs(prev_close - chosen_sup[0]) else chosen_sup[1]
        touches = max(chosen_res[3], chosen_sup[3])

        return {
            "resistance": round(res_val, 2),
            "support": round(sup_val, 2),
            "level_type": chosen_type,
            "touches": touches,
            "score": min(20, best_score),
            "details": {
                "pdh": pdh,
                "pdl": pdl,
                "asian_h": asian_h,
                "asian_l": asian_l,
                "london_h": london_h,
                "london_l": london_l,
                "range_h": range_h,
                "range_l": range_l,
            },
        }

    # -------------------------------------------------------------------------
    # Section C & D: Breakout Detection & False Breakout Filter
    # -------------------------------------------------------------------------

    def evaluate_breakout(
        self,
        candles: List[AggregatedCandle],
        resistance: float,
        support: float,
        atr: float,
    ) -> Dict[str, Any]:
        """
        Classifies breakout into 4 explicit categories:
        1. WICK_BREAKOUT: Wick poked outside, closed inside (not valid, score 0).
        2. WEAK_BREAKOUT: Closed outside but weak body or small displacement (not valid for live trade).
        3. VALID_BREAKOUT: Closed outside, body >= 55%, penetration >= 0.10*ATR.
        4. STRONG_BREAKOUT: Closed outside, body >= 65%, penetration >= 0.20*ATR, range expansion >= 1.5x.

        Only categories 3 and 4 can advance to confirmation.
        """
        if len(candles) < 3:
            return {
                "breakout_valid": False,
                "breakout_type": "NONE",
                "breakout_category": "NONE",
                "strength_score": 0,
                "momentum_score": 0,
                "momentum_state": "WEAK",
                "body_ratio": 0.0,
                "close_location": 0.0,
                "consecutive_candles": 0,
                "reason": "Insufficient candle history",
            }

        last_c = candles[-1]
        c_open = float(last_c.open)
        c_high = float(last_c.high)
        c_low = float(last_c.low)
        c_close = float(last_c.close)
        c_range = c_high - c_low if (c_high - c_low) > 0 else 0.01
        c_body = abs(c_close - c_open)
        body_ratio = c_body / c_range
        close_location = (c_close - c_low) / c_range

        min_disp = self.cfg.min_displacement_atr_mult * atr
        strong_disp = self.cfg.strong_displacement_atr_mult * atr

        # Check Category 1: Wick Breakout
        is_bullish_wick = (c_high > resistance) and (c_close <= resistance)
        is_bearish_wick = (c_low < support) and (c_close >= support)

        if is_bullish_wick:
            return {
                "breakout_valid": False,
                "breakout_type": "WICK_REJECTION",
                "breakout_category": "WICK_BREAKOUT",
                "strength_score": 0,
                "momentum_score": 3,
                "momentum_state": "WEAK",
                "body_ratio": body_ratio,
                "close_location": close_location,
                "consecutive_candles": 0,
                "reason": f"Wick poked resistance (${resistance:.2f}) but closed inside (${c_close:.2f}) — Category 1: Wick Breakout (False)",
            }

        if is_bearish_wick:
            return {
                "breakout_valid": False,
                "breakout_type": "WICK_REJECTION",
                "breakout_category": "WICK_BREAKOUT",
                "strength_score": 0,
                "momentum_score": 3,
                "momentum_state": "WEAK",
                "body_ratio": body_ratio,
                "close_location": close_location,
                "consecutive_candles": 0,
                "reason": f"Wick poked support (${support:.2f}) but closed inside (${c_close:.2f}) — Category 1: Wick Breakout (False)",
            }

        # Check closes outside
        is_bull_outside = (c_close > resistance) and (c_close > c_open)
        is_bear_outside = (c_close < support) and (c_close < c_open)

        if not (is_bull_outside or is_bear_outside):
            return {
                "breakout_valid": False,
                "breakout_type": "NONE",
                "breakout_category": "NONE",
                "strength_score": 0,
                "momentum_score": 0,
                "momentum_state": "WEAK",
                "body_ratio": body_ratio,
                "close_location": close_location,
                "consecutive_candles": 0,
                "reason": "Harga masih berada di dalam range key level (Support & Resistance)",
            }

        disp = (c_close - resistance) if is_bull_outside else (support - c_close)
        range_ratio = c_range / atr if atr > 0 else 1.0

        # Check Category 2: Weak Breakout
        if disp < min_disp or body_ratio < self.cfg.min_candle_body_ratio:
            return {
                "breakout_valid": False,
                "breakout_type": "BULLISH_BREAKOUT" if is_bull_outside else "BEARISH_BREAKOUT",
                "breakout_category": "WEAK_BREAKOUT",
                "strength_score": 6,
                "momentum_score": 5,
                "momentum_state": "WEAK",
                "body_ratio": body_ratio,
                "close_location": close_location,
                "consecutive_candles": 1,
                "reason": f"Breakout lemah (body {int(body_ratio*100)}% < {int(self.cfg.min_candle_body_ratio*100)}% atau jarak {disp:.2f} < {min_disp:.2f}) — Category 2: Weak Breakout (Tidak layak)",
            }

        # Check Category 4: Strong Breakout vs Category 3: Valid Breakout
        is_strong = (
            body_ratio >= self.cfg.strong_candle_body_ratio
            and disp >= strong_disp
            and range_ratio >= self.cfg.expansion_mult
            and ((close_location >= 0.75 and is_bull_outside) or (close_location <= 0.25 and is_bear_outside))
        )

        breakout_type = "BULLISH_BREAKOUT" if is_bull_outside else "BEARISH_BREAKOUT"
        breakout_category = "STRONG_BREAKOUT" if is_strong else "VALID_BREAKOUT"

        # Breakout Strength Score (0-20):
        # 1. Body Ratio (Max 8 pts)
        if body_ratio >= self.cfg.strong_candle_body_ratio:
            body_score = 8
        elif body_ratio >= self.cfg.min_candle_body_ratio:
            body_score = 6
        else:
            body_score = 2

        # 2. Range Expansion vs ATR (Max 7 pts)
        if range_ratio >= 1.5:
            range_score = 7
        elif range_ratio >= 1.1:
            range_score = 5
        else:
            range_score = 3

        # 3. Close Location (Max 5 pts)
        if is_bull_outside:
            loc_score = 5 if close_location >= 0.80 else (3 if close_location >= 0.65 else 1)
        else:
            loc_score = 5 if close_location <= 0.20 else (3 if close_location <= 0.35 else 1)

        strength_score = min(20, body_score + range_score + loc_score)

        # -------------------------------------------------------------------------
        # Section F: Momentum Engine (0-15 pts)
        # -------------------------------------------------------------------------
        # Consecutive directional candles
        consecutive = 1
        for i in range(len(candles) - 2, max(-1, len(candles) - 5), -1):
            c_prev = candles[i]
            if is_bull_outside and float(c_prev.close) > float(c_prev.open):
                consecutive += 1
            elif is_bear_outside and float(c_prev.close) < float(c_prev.open):
                consecutive += 1
            else:
                break

        # Displacement over last 3 candles
        prev_closes = [float(c.close) for c in candles[-4:]]
        disp_3 = abs(prev_closes[-1] - prev_closes[0])
        disp_ratio = disp_3 / atr if atr > 0 else 1.0

        # Tick activity comparison
        avg_ticks = sum(float(getattr(c, "tick_volume", getattr(c, "tick_count", 100))) for c in candles[-10:]) / 10.0
        last_ticks = float(getattr(last_c, "tick_volume", getattr(last_c, "tick_count", 100)))
        tick_ratio = last_ticks / avg_ticks if avg_ticks > 0 else 1.0

        # Score Momentum (0-15)
        m_score = 0
        if consecutive >= 2:
            m_score += 4
        else:
            m_score += 2

        if disp_ratio >= 1.8:
            m_score += 6
        elif disp_ratio >= 1.2:
            m_score += 4
        else:
            m_score += 2

        if tick_ratio >= 1.2:
            m_score += 5
        elif tick_ratio >= 1.0:
            m_score += 3
        else:
            m_score += 1

        momentum_score = min(15, m_score)
        if momentum_score >= 12:
            momentum_state = "STRONG"
        elif momentum_score >= 8:
            momentum_state = "MODERATE"
        else:
            momentum_state = "WEAK"

        return {
            "breakout_valid": True,
            "breakout_type": breakout_type,
            "breakout_category": breakout_category,
            "strength_score": strength_score,
            "momentum_score": momentum_score,
            "momentum_state": momentum_state,
            "body_ratio": body_ratio,
            "close_location": close_location,
            "consecutive_candles": consecutive,
            "reason": f"Breakout terkonfirmasi ({breakout_category}) — Body {int(body_ratio*100)}%, Displ {disp:.2f}, Momentum {momentum_state}",
        }

    # -------------------------------------------------------------------------
    # Section E: Retest Engine (0-10 pts)
    # -------------------------------------------------------------------------

    def evaluate_retest(
        self,
        candles: List[AggregatedCandle],
        breakout_type: str,
        level: float,
        atr: float,
        breakout_category: str = "VALID_BREAKOUT",
        momentum_score: int = 10,
    ) -> Tuple[str, int, bool]:
        """
        Evaluates retest behavior on broken level.
        Returns: (retest_state, score 0-10, trap_collapse_flag)
        - CONFIRMED: Price pulled back to level and bounced away (Score 10)
        - PENDING: Fresh breakout, retest has not occurred yet (Score 7)
        - FAILED (Trap Collapse): Price plunged back inside range (Score 0, hard veto!)

        Rule: Retest is NOT mandatory if breakout is STRONG_BREAKOUT with high momentum (>= 12).
        """
        if breakout_type == "NONE" or len(candles) < 1:
            return "NONE", 0, False

        last_c = candles[-1]
        c_close = float(last_c.close)
        c_low = float(last_c.low)
        c_high = float(last_c.high)
        tolerance = self.cfg.retest_tolerance_atr_mult * atr

        if breakout_type == "BULLISH_BREAKOUT":
            # If price immediately falls back below the broken resistance -> TRAP!
            if c_close < level - 0.05 * atr:
                return "FAILED", 0, True

            # If low touched near resistance and close held above -> CONFIRMED RETEST
            if abs(c_low - level) <= tolerance and c_close > level:
                return "CONFIRMED", 10, False
            else:
                # If strong breakout with elite momentum, pending retest gets strong score
                sc = 9 if (breakout_category == "STRONG_BREAKOUT" and momentum_score >= 12) else 7
                return "PENDING", sc, False

        elif breakout_type == "BEARISH_BREAKOUT":
            # If price immediately rises back above the broken support -> TRAP!
            if c_close > level + 0.05 * atr:
                return "FAILED", 0, True

            # If high touched near support and close held below -> CONFIRMED RETEST
            if abs(c_high - level) <= tolerance and c_close < level:
                return "CONFIRMED", 10, False
            else:
                sc = 9 if (breakout_category == "STRONG_BREAKOUT" and momentum_score >= 12) else 7
                return "PENDING", sc, False

        return "NONE", 0, False

    # -------------------------------------------------------------------------
    # Section H: Profit Potential Engine (0-10 pts)
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
        Computes Entry, Stop Loss, Take Profit, Nearest Opposing Level, Expected Move,
        Risk $, Reward $, and RR Ratio.
        Enforces minimum RR = 1:2.0 (preferred 1:2.5+).
        """
        if breakout_type == "NONE" or len(candles) == 0:
            return {
                "entry": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "risk": 0.0,
                "reward": 0.0,
                "expected_move_dollars": 0.0,
                "expected_move_pips": 0.0,
                "target_opposing_level": 0.0,
                "rr_ratio": 0.0,
                "rr_string": "N/A",
                "profit_potential_valid": False,
                "score": 0,
            }

        last_c = candles[-1]
        entry = float(last_c.close)
        buffer = max(0.50, atr * 0.35)

        if breakout_type == "BULLISH_BREAKOUT":
            sl_candidate_1 = broken_level - buffer
            sl_candidate_2 = float(last_c.low) - buffer * 0.5
            stop_loss = round(min(sl_candidate_1, sl_candidate_2), 2)
            risk = round(entry - stop_loss, 2)
            if risk <= 0.20:
                risk = round(atr * 1.0, 2)
                stop_loss = round(entry - risk, 2)

            tp_min = entry + (risk * self.minimum_rr)
            tp_preferred = entry + (risk * self.preferred_rr)

            # Check nearest opposing level
            target_opposing = opposing_level if opposing_level > entry else tp_preferred
            if opposing_level > entry:
                # If opposing level caps space below minimum RR
                if opposing_level < tp_min:
                    # Space is too tight! Opposing liquidity will block the trade before 2R
                    take_profit = round(opposing_level, 2)
                    reward = round(take_profit - entry, 2)
                    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0
                    return {
                        "entry": round(entry, 2),
                        "stop_loss": round(stop_loss, 2),
                        "take_profit": round(take_profit, 2),
                        "risk": risk,
                        "reward": reward,
                        "expected_move_dollars": reward,
                        "expected_move_pips": round(reward * 10, 1),
                        "target_opposing_level": round(opposing_level, 2),
                        "rr_ratio": rr_ratio,
                        "rr_string": f"1 : {rr_ratio}",
                        "profit_potential_valid": False,  # Blocked by opposing level!
                        "score": 2,
                    }
                else:
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

            tp_min = entry - (risk * self.minimum_rr)
            tp_preferred = entry - (risk * self.preferred_rr)

            target_opposing = opposing_level if (opposing_level < entry and opposing_level > 0) else tp_preferred
            if opposing_level < entry and opposing_level > 0:
                # If opposing level caps space below minimum RR
                if opposing_level > tp_min:
                    take_profit = round(opposing_level, 2)
                    reward = round(entry - take_profit, 2)
                    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0
                    return {
                        "entry": round(entry, 2),
                        "stop_loss": round(stop_loss, 2),
                        "take_profit": round(take_profit, 2),
                        "risk": risk,
                        "reward": reward,
                        "expected_move_dollars": reward,
                        "expected_move_pips": round(reward * 10, 1),
                        "target_opposing_level": round(opposing_level, 2),
                        "rr_ratio": rr_ratio,
                        "rr_string": f"1 : {rr_ratio}",
                        "profit_potential_valid": False,  # Blocked by opposing level!
                        "score": 2,
                    }
                else:
                    take_profit = round(min(opposing_level, tp_preferred), 2)
            else:
                take_profit = round(tp_preferred, 2)

            reward = round(entry - take_profit, 2)

        rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0
        rr_string = f"1 : {rr_ratio}"
        profit_potential_valid = (rr_ratio >= self.minimum_rr)

        # Score Profit Potential (0-10)
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
            "expected_move_dollars": reward,
            "expected_move_pips": round(reward * 10, 1),
            "target_opposing_level": round(target_opposing, 2),
            "rr_ratio": rr_ratio,
            "rr_string": rr_string,
            "profit_potential_valid": profit_potential_valid,
            "score": score,
        }

    # -------------------------------------------------------------------------
    # Section I & J: Score Engine & Master Evaluation Pipeline
    # -------------------------------------------------------------------------

    def evaluate(
        self,
        candles: List[AggregatedCandle],
        current_spread: float = 0.20,
        is_market_open: bool = True,
        is_news_restricted: bool = False,
    ) -> XAUUSDBreakoutResult:
        """
        Executes full evaluation pipeline (Sections A through J).
        Enforces Hard Firewall Veto Rule:
        IF any mandatory condition fails -> SIGNAL = NO_TRADE with explicit reason list.
        """
        result = XAUUSDBreakoutResult(symbol=self.symbol)
        result.spread = round(current_spread, 2)

        # Convert/validate candles if passed as dicts
        parsed_candles = [self._ensure_candle(c) for c in (candles or [])]
        candles = [c for c in parsed_candles if c is not None]

        # 1. Market Status Filter
        if not is_market_open:
            result.market_status = "MARKET_CLOSED"
        elif is_news_restricted:
            result.market_status = "NEWS_RESTRICTED"
        else:
            result.market_status = "ACTIVE"

        if not candles or len(candles) < 5:
            result.signal = "NO_TRADE"
            result.status_label = "NO TRADE"
            result.veto_reason = "Data candle history belum mencukupi (minimal 5 candle M5)"
            result.reasons_for_no_trade = [result.veto_reason]
            result.no_trade_summary = f"NO TRADE | Score: 0 | Reasons: {result.veto_reason}"
            return result

        eval_candle = candles[-1]
        eval_dt = eval_candle.timestamp

        # 2. Session & Volatility & Market Regime
        session_name, score_session = self.detect_session(eval_dt)
        result.session = session_name
        result.score_session = score_session

        atr = self.compute_atr(candles, period=14)
        result.atr = atr
        result.market_regime = self.detect_market_regime(candles, atr)

        atr_state, vol_state, score_vol, was_compressed = self.evaluate_volatility(candles, atr)
        result.atr_state = atr_state
        result.volatility_state = vol_state
        result.score_volatility = score_vol

        # 3. Spread Score & Bad Spread Check
        if current_spread <= 0.25:
            result.score_spread = 5
            result.spread_bad = False
        elif current_spread <= self.max_spread:
            result.score_spread = 3
            result.spread_bad = False
        else:
            result.score_spread = 0
            result.spread_bad = True

        # 4. Key Level Identification & Quality Score (0-20)
        levels_info = self.identify_key_levels(candles, atr)
        result.resistance = levels_info["resistance"]
        result.support = levels_info["support"]
        result.level_type = levels_info["level_type"]
        result.level_touches = levels_info["touches"]
        result.score_level_quality = levels_info["score"]

        # 5. Breakout Detection & Category Classifier (0-20 pts) + Momentum (0-15 pts)
        breakout_info = self.evaluate_breakout(
            candles,
            resistance=result.resistance,
            support=result.support,
            atr=atr,
        )
        result.breakout_valid = breakout_info["breakout_valid"]
        result.breakout_type = breakout_info["breakout_type"]
        result.breakout_category = breakout_info["breakout_category"]
        result.score_breakout_strength = breakout_info["strength_score"]
        result.score_momentum = breakout_info["momentum_score"]
        result.momentum_state = breakout_info["momentum_state"]

        # 6. Retest Engine (0-10 pts)
        target_broken_level = result.resistance if result.breakout_type == "BULLISH_BREAKOUT" else result.support
        retest_state, score_retest, is_trap = self.evaluate_retest(
            candles,
            breakout_type=result.breakout_type,
            level=target_broken_level,
            atr=atr,
            breakout_category=result.breakout_category,
            momentum_score=result.score_momentum,
        )
        result.retest_state = retest_state
        result.score_retest = score_retest

        if is_trap:
            # Trap Collapse: Immediate plunge back inside range -> False Breakout Veto
            result.breakout_valid = False
            result.breakout_type = "NONE"
            result.breakout_category = "FALSE_BREAKOUT_TRAP"
            result.veto_reason = "Harga langsung jatuh kembali ke dalam range (Trap Collapse / False Breakout)"

        # 7. Profit Potential Engine (0-10 pts)
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
        result.expected_move_dollars = trade_levels["expected_move_dollars"]
        result.expected_move_pips = trade_levels["expected_move_pips"]
        result.target_opposing_level = trade_levels["target_opposing_level"]
        result.rr_ratio = trade_levels["rr_ratio"]
        result.rr_string = trade_levels["rr_string"]
        result.profit_potential_valid = trade_levels["profit_potential_valid"]
        result.score_profit_potential = trade_levels["score"]

        # 8. Compute Total 100-Point Score (Section I)
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

        # 9. Evidence Checklist for UI / Dashboard
        result.evidence_checklist = [
            {"name": "Market Status", "status": result.market_status, "ok": is_market_open and not is_news_restricted},
            {"name": "Session", "status": result.session, "ok": result.score_session >= 4},
            {"name": "Spread", "status": f"${result.spread:.2f}", "ok": not result.spread_bad},
            {"name": "ATR / Volatility", "status": f"{result.atr_state} ({result.volatility_state})", "ok": result.score_volatility >= 9},
            {"name": "Breakout", "status": "VALID" if result.breakout_valid else ("REJECTED (WICK)" if breakout_info["breakout_type"] == "WICK_REJECTION" else "WAITING"), "ok": result.breakout_valid},
            {"name": "Momentum", "status": result.momentum_state, "ok": result.score_momentum >= 10},
            {"name": "Retest", "status": result.retest_state, "ok": result.retest_state in ("CONFIRMED", "PENDING")},
            {"name": "Risk : Reward", "status": result.rr_string, "ok": result.profit_potential_valid},
        ]

        # 10. Mandatory Conditions & NO_TRADE Reason Aggregator (Section J)
        reasons: List[str] = []
        if not is_market_open:
            reasons.append("Market closed (Forex weekend / holiday)")
        if is_news_restricted:
            reasons.append("High-impact economic news window active")
        if result.spread_bad:
            reasons.append(f"Spread abnormal (${result.spread:.2f} > limit ${self.max_spread:.2f})")
        if not result.breakout_valid:
            if result.breakout_category == "WICK_BREAKOUT":
                reasons.append("Breakout hanya berupa wick (Anti-Wick Validator: Wick pokes outside, closes inside)")
            elif result.breakout_category == "WEAK_BREAKOUT":
                reasons.append("Breakout lemah (Candle body < 55% atau displacement belum cukup)")
            elif result.breakout_category == "FALSE_BREAKOUT_TRAP":
                reasons.append("False breakout trap: Harga kembali masuk ke dalam range")
            else:
                reasons.append("Belum ada valid breakout pada key level (Harga di dalam S/R)")
        if result.momentum_state == "WEAK":
            reasons.append("Momentum lemah / tidak mendukung breakout")
        if result.volatility_state == "COMPRESSED":
            reasons.append("Volatility pasar masih terkompresi / belum terjadi expansion")
        if not result.profit_potential_valid:
            reasons.append(f"Risk:Reward tidak memadai ({result.rr_string} < minimum 1:{self.minimum_rr:.1f})")
        if result.retest_state == "FAILED":
            reasons.append("Retest gagal (Harga breakdown kembali ke dalam range)")

        # Mandatory Hard Firewall Check
        if reasons:
            result.signal = "NO_TRADE"
            result.reasons_for_no_trade = reasons
            result.veto_reason = "; ".join(reasons)
            # Cap score below valid setup bracket if hard vetoed
            result.total_score = min(result.total_score, 59)
            result.status_label = "NO TRADE"
            result.no_trade_summary = f"NO TRADE | Score: {result.total_score} | Reasons: {'; '.join(reasons)}"
            return result

        # 11. Decision Brackets (Section I):
        # 0–59   = NO TRADE
        # 60–74  = WATCH
        # 75–84  = VALID SETUP
        # 85–100 = HIGH QUALITY TRADE
        if result.total_score >= self.cfg.minimum_live_score:
            result.status_label = "HIGH QUALITY TRADE"
            result.signal = "BUY" if result.breakout_type == "BULLISH_BREAKOUT" else "SELL"
        elif result.total_score >= self.cfg.valid_setup_score:
            result.status_label = "VALID SETUP"
            result.signal = "BUY" if result.breakout_type == "BULLISH_BREAKOUT" else "SELL"
        elif result.total_score >= self.cfg.watch_score:
            result.status_label = "WATCH"
            result.signal = "NO_TRADE"
            result.reasons_for_no_trade = [f"Score {result.total_score} berada dalam bracket WATCH (menunggu konfirmasi tambahan >= {self.cfg.valid_setup_score})"]
            result.no_trade_summary = f"WATCH | Score: {result.total_score} | Reasons: Menunggu konfirmasi score >= {self.cfg.valid_setup_score}"
        else:
            result.status_label = "NO TRADE"
            result.signal = "NO_TRADE"
            result.reasons_for_no_trade = [f"Score {result.total_score} < {self.cfg.watch_score}"]
            result.no_trade_summary = f"NO TRADE | Score: {result.total_score} | Reasons: Score di bawah ambang batas minimal"

        return result
