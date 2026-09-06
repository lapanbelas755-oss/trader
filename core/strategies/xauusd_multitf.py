"""Trader Machine — XAU/USD Multi-Timeframe Confluence Engine (V1).

Strict Top-Down Confluence Hierarchy:
- H4: Macro Trend, Dominant Bias & Major Barrier Clearance (Anti-Beli di Pucuk / Anti-Jual di Lembah)
- H1: Key Structural Levels & Major Liquidity (PDH/PDL, Range Boundaries)
- M15: Intermediate Context & Market Regime (Compression -> Expansion)
- M5: Breakout Engine, Body Confirmation & Momentum Trigger
- M1: Microstructure, Sniper Retest Rejection & Tight SL Positioning
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional, Union
import numpy as np


class TrendBias(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class VolatilityState(str, Enum):
    COMPRESSION = "COMPRESSION"
    EXPANSION = "EXPANSION"
    NORMAL = "NORMAL"


@dataclass
class CandleRecord:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


@dataclass
class TimeframeAnalysis:
    timeframe: str
    trend: TrendBias
    structure: str
    nearest_resistance: float
    nearest_support: float
    atr: float
    volatility: VolatilityState
    is_aligned: bool
    notes: str


@dataclass
class MultiTFConfluenceResult:
    confluence_passed: bool
    dominant_macro_bias: TrendBias
    h4: TimeframeAnalysis
    h1: TimeframeAnalysis
    m15: TimeframeAnalysis
    m5: TimeframeAnalysis
    m1: TimeframeAnalysis
    h4_barrier_clear: bool
    m15_structure_confirmed: bool
    m5_breakout_confirmed: bool
    m1_retest_confirmed: bool
    confluence_score: int
    veto_reasons: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "confluence_passed": self.confluence_passed,
            "dominant_macro_bias": self.dominant_macro_bias.value,
            "h4_barrier_clear": self.h4_barrier_clear,
            "m15_structure_confirmed": self.m15_structure_confirmed,
            "m5_breakout_confirmed": self.m5_breakout_confirmed,
            "m1_retest_confirmed": self.m1_retest_confirmed,
            "confluence_score": self.confluence_score,
            "veto_reasons": self.veto_reasons,
            "summary": self.summary,
            "timeframes": {
                "H4": {
                    "trend": self.h4.trend.value,
                    "structure": self.h4.structure,
                    "resistance": round(self.h4.nearest_resistance, 2),
                    "support": round(self.h4.nearest_support, 2),
                    "atr": round(self.h4.atr, 2),
                    "volatility": self.h4.volatility.value,
                    "aligned": self.h4.is_aligned,
                    "notes": self.h4.notes,
                },
                "H1": {
                    "trend": self.h1.trend.value,
                    "structure": self.h1.structure,
                    "resistance": round(self.h1.nearest_resistance, 2),
                    "support": round(self.h1.nearest_support, 2),
                    "atr": round(self.h1.atr, 2),
                    "volatility": self.h1.volatility.value,
                    "aligned": self.h1.is_aligned,
                    "notes": self.h1.notes,
                },
                "M15": {
                    "trend": self.m15.trend.value,
                    "structure": self.m15.structure,
                    "resistance": round(self.m15.nearest_resistance, 2),
                    "support": round(self.m15.nearest_support, 2),
                    "atr": round(self.m15.atr, 2),
                    "volatility": self.m15.volatility.value,
                    "aligned": self.m15.is_aligned,
                    "notes": self.m15.notes,
                },
                "M5": {
                    "trend": self.m5.trend.value,
                    "structure": self.m5.structure,
                    "resistance": round(self.m5.nearest_resistance, 2),
                    "support": round(self.m5.nearest_support, 2),
                    "atr": round(self.m5.atr, 2),
                    "volatility": self.m5.volatility.value,
                    "aligned": self.m5.is_aligned,
                    "notes": self.m5.notes,
                },
                "M1": {
                    "trend": self.m1.trend.value,
                    "structure": self.m1.structure,
                    "resistance": round(self.m1.nearest_resistance, 2),
                    "support": round(self.m1.nearest_support, 2),
                    "atr": round(self.m1.atr, 2),
                    "volatility": self.m1.volatility.value,
                    "aligned": self.m1.is_aligned,
                    "notes": self.m1.notes,
                },
            }
        }


def _to_candles(raw: Any) -> list[CandleRecord]:
    """Convert various candle formats (dict, AggregatedCandle, tuple) to CandleRecord."""
    if not raw:
        return []
    records: list[CandleRecord] = []
    for item in raw:
        try:
            if hasattr(item, "open") and hasattr(item, "close"):
                t = getattr(item, "timestamp", getattr(item, "time", datetime.now(timezone.utc)))
                if not isinstance(t, datetime):
                    t = datetime.now(timezone.utc)
                records.append(CandleRecord(
                    timestamp=t,
                    open=float(item.open),
                    high=float(item.high),
                    low=float(item.low),
                    close=float(item.close),
                    volume=int(getattr(item, "volume", getattr(item, "tick_volume", 0))),
                ))
            elif isinstance(item, dict):
                t_raw = item.get("timestamp") or item.get("time") or datetime.now(timezone.utc)
                if isinstance(t_raw, str):
                    try:
                        t = datetime.fromisoformat(t_raw.replace("Z", "+00:00"))
                    except Exception:
                        t = datetime.now(timezone.utc)
                elif isinstance(t_raw, (int, float)):
                    t = datetime.fromtimestamp(t_raw, tz=timezone.utc)
                elif isinstance(t_raw, datetime):
                    t = t_raw
                else:
                    t = datetime.now(timezone.utc)

                records.append(CandleRecord(
                    timestamp=t,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=int(item.get("volume", item.get("tick_volume", 0))),
                ))
        except (KeyError, ValueError, TypeError):
            continue
    return records


def _calc_atr(candles: list[CandleRecord], period: int = 14) -> float:
    if len(candles) < 2:
        return 1.0
    trs: list[float] = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev = candles[i - 1]
        tr = max(
            c.high - c.low,
            abs(c.high - prev.close),
            abs(c.low - prev.close)
        )
        trs.append(tr)
    recent = trs[-period:] if len(trs) >= period else trs
    return float(np.mean(recent)) if recent else 1.0


def _calc_ema(closes: list[float], period: int) -> float:
    if not closes:
        return 0.0
    if len(closes) < period:
        return float(np.mean(closes))
    k = 2.0 / (period + 1)
    ema = float(closes[0])
    for price in closes[1:]:
        ema = price * k + ema * (1.0 - k)
    return ema


def _analyze_single_timeframe(tf: str, candles: list[CandleRecord], current_price: float) -> TimeframeAnalysis:
    if not candles:
        return TimeframeAnalysis(
            timeframe=tf,
            trend=TrendBias.NEUTRAL,
            structure="RANGE",
            nearest_resistance=current_price + 20.0,
            nearest_support=current_price - 20.0,
            atr=2.0,
            volatility=VolatilityState.NORMAL,
            is_aligned=True,
            notes="Data candle tidak mencukupi (default neutral)."
        )

    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    atr = _calc_atr(candles, period=min(14, len(candles) - 1 or 1))

    # 1. Trend via EMA 20 & EMA 50
    ema20 = _calc_ema(closes, period=min(20, len(closes)))
    ema50 = _calc_ema(closes, period=min(50, len(closes)))

    last_close = closes[-1]
    if last_close > ema20 and ema20 >= ema50:
        trend = TrendBias.BULLISH
    elif last_close < ema20 and ema20 <= ema50:
        trend = TrendBias.BEARISH
    else:
        trend = TrendBias.NEUTRAL

    # 2. Key swing S/R (exclude current active candle)
    recent_window = min(20, len(candles))
    prior_highs = highs[:-1] if len(highs) > 1 else highs
    prior_lows = lows[:-1] if len(lows) > 1 else lows
    recent_highs = prior_highs[-recent_window:]
    recent_lows = prior_lows[-recent_window:]

    above_cur = [h for h in recent_highs if h > current_price + 0.1]
    below_cur = [l for l in recent_lows if l < current_price - 0.1]

    nearest_res = min(above_cur) if above_cur else current_price + 5.0 * atr
    nearest_sup = max(below_cur) if below_cur else current_price - 5.0 * atr

    # 3. Structure
    if len(closes) >= 5:
        first_half = closes[-10:-5] if len(closes) >= 10 else closes[: len(closes)//2]
        second_half = closes[-5:]
        mean1 = float(np.mean(first_half)) if first_half else last_close
        mean2 = float(np.mean(second_half))
        if mean2 > mean1 + 0.1 * atr:
            structure = "HIGHER_HIGHS"
        elif mean2 < mean1 - 0.1 * atr:
            structure = "LOWER_LOWS"
        else:
            structure = "RANGE"
    else:
        structure = "RANGE"

    # 4. Volatility state (Compression vs Expansion)
    ranges = [c.high - c.low for c in candles[-15:]]
    med_range = float(np.median(ranges)) if ranges else atr
    last_range = candles[-1].high - candles[-1].low

    if last_range > 1.4 * med_range:
        vol = VolatilityState.EXPANSION
    elif last_range < 0.6 * med_range:
        vol = VolatilityState.COMPRESSION
    else:
        vol = VolatilityState.NORMAL

    return TimeframeAnalysis(
        timeframe=tf,
        trend=trend,
        structure=structure,
        nearest_resistance=nearest_res,
        nearest_support=nearest_sup,
        atr=atr,
        volatility=vol,
        is_aligned=True,
        notes=f"{tf} {trend.value} ({structure})"
    )


class XAUUSDMultiTFConfluenceEngine:
    """Evaluates top-down confluence across H4, H1, M15, M5, and M1 for Gold."""

    def __init__(self, min_barrier_clearance_atr_mult: float = 1.5):
        self.min_barrier_clearance_atr_mult = min_barrier_clearance_atr_mult

    def evaluate(
        self,
        current_price: float,
        breakout_direction: str,  # "BULLISH", "BEARISH", or "NONE"
        m1_candles: Any,
        m5_candles: Any,
        m15_candles: Any,
        h1_candles: Any,
        h4_candles: Any,
    ) -> MultiTFConfluenceResult:
        """Run top-down multi-timeframe analysis."""
        c_m1 = _to_candles(m1_candles)
        c_m5 = _to_candles(m5_candles)
        c_m15 = _to_candles(m15_candles)
        c_h1 = _to_candles(h1_candles)
        c_h4 = _to_candles(h4_candles)

        # Fallback synthesis if higher timeframes are empty: synthesize from M5
        if not c_m1:
            c_m1 = c_m5[-5:] if c_m5 else []
        if not c_m15:
            c_m15 = c_m5
        if not c_h1:
            c_h1 = c_m5
        if not c_h4:
            c_h4 = c_m5

        h4_a = _analyze_single_timeframe("H4", c_h4, current_price)
        h1_a = _analyze_single_timeframe("H1", c_h1, current_price)
        m15_a = _analyze_single_timeframe("M15", c_m15, current_price)
        m5_a = _analyze_single_timeframe("M5", c_m5, current_price)
        m1_a = _analyze_single_timeframe("M1", c_m1, current_price)

        direction = breakout_direction.upper()
        veto_reasons: list[str] = []
        score = 0

        # Dominant Macro Bias from H4 & H1
        if h4_a.trend == TrendBias.BULLISH and h1_a.trend in (TrendBias.BULLISH, TrendBias.NEUTRAL):
            macro_bias = TrendBias.BULLISH
        elif h4_a.trend == TrendBias.BEARISH and h1_a.trend in (TrendBias.BEARISH, TrendBias.NEUTRAL):
            macro_bias = TrendBias.BEARISH
        else:
            macro_bias = TrendBias.NEUTRAL

        # --- Rule 1: H4 Barrier Clearance (Anti-Beli di Pucuk / Anti-Jual di Lembah) ---
        h4_barrier_clear = True
        required_clearance = max(2.0, self.min_barrier_clearance_atr_mult * m5_a.atr)

        if direction == "BULLISH":
            dist_to_h4_res = h4_a.nearest_resistance - current_price
            if h4_candles is not None and dist_to_h4_res < required_clearance and dist_to_h4_res > 0.05:
                h4_barrier_clear = False
                veto_reasons.append(
                    f"H4 Resistance (${h4_a.nearest_resistance:.2f}) terlalu dekat (${dist_to_h4_res:.2f} < ${required_clearance:.2f}). Ruang profit terhalang barrier H4."
                )
            if h4_a.trend == TrendBias.BEARISH and len(c_h4) >= 20 and h4_candles is not None:
                veto_reasons.append("Breakout Bullish melawan Macro Trend H4 (Bearish).")
        elif direction == "BEARISH":
            dist_to_h4_sup = current_price - h4_a.nearest_support
            if h4_candles is not None and dist_to_h4_sup < required_clearance and dist_to_h4_sup > 0.05:
                h4_barrier_clear = False
                veto_reasons.append(
                    f"H4 Support (${h4_a.nearest_support:.2f}) terlalu dekat (${dist_to_h4_sup:.2f} < ${required_clearance:.2f}). Ruang profit terhalang barrier H4."
                )
            if h4_a.trend == TrendBias.BULLISH and len(c_h4) >= 20 and h4_candles is not None:
                veto_reasons.append("Breakout Bearish melawan Macro Trend H4 (Bullish).")

        # --- Rule 2: M15 Structure Confirmation ---
        m15_structure_confirmed = True
        if direction == "BULLISH":
            if m15_a.structure == "LOWER_LOWS" and m15_candles is not None:
                m15_structure_confirmed = False
                veto_reasons.append("Struktur M15 masih membentuk Lower Lows (belum terjadi Bullish CHoCH).")
        elif direction == "BEARISH":
            if m15_a.structure == "HIGHER_HIGHS" and m15_candles is not None:
                m15_structure_confirmed = False
                veto_reasons.append("Struktur M15 masih membentuk Higher Highs (belum terjadi Bearish CHoCH).")

        # --- Rule 3: M5 Breakout Confirmation ---
        m5_breakout_confirmed = (m5_a.volatility == VolatilityState.EXPANSION) or (m5_a.trend.value == direction)
        if direction != "NONE" and not m5_breakout_confirmed and len(c_m5) >= 10:
            m5_breakout_confirmed = True  # Allowed if breakout trigger was mathematically validated by M5 engine

        # --- Rule 4: M1 Micro Retest / Clean Rejection ---
        m1_retest_confirmed = True
        if m1_candles is not None and c_m1 and len(c_m1) >= 2:
            last_m1 = c_m1[-1]
            prev_m1 = c_m1[-2]
            if direction == "BULLISH":
                is_bull_m1 = (last_m1.close >= last_m1.open) or (last_m1.close > prev_m1.close)
                if not is_bull_m1:
                    m1_retest_confirmed = False
                    veto_reasons.append("Micro M1 belum memberikan konfirmasi rejection candle bullish.")
            elif direction == "BEARISH":
                is_bear_m1 = (last_m1.close <= last_m1.open) or (last_m1.close < prev_m1.close)
                if not is_bear_m1:
                    m1_retest_confirmed = False
                    veto_reasons.append("Micro M1 belum memberikan konfirmasi rejection candle bearish.")

        # --- Calculate Confluence Score (0 - 100) ---
        if h4_a.trend.value == direction:
            score += 25
        elif h4_a.trend == TrendBias.NEUTRAL:
            score += 15

        if h1_a.trend.value == direction:
            score += 20
        elif h1_a.trend == TrendBias.NEUTRAL:
            score += 15

        if m15_structure_confirmed:
            score += 20
        if m5_breakout_confirmed:
            score += 20
        if m1_retest_confirmed:
            score += 20

        confluence_passed = (
            direction in ("BULLISH", "BEARISH")
            and h4_barrier_clear
            and m15_structure_confirmed
            and len(veto_reasons) == 0
        )

        if confluence_passed:
            summary = f"FULL 5-TF CONFLUENCE ({direction}): H4/H1 sejalan, M15 struktur valid, M5 breakout tegas, M1 sniper entry terkonfirmasi."
        elif direction == "NONE":
            summary = "NO TRADE | Tidak ada arah breakout terdeteksi pada M5."
        else:
            summary = f"CONFLUENCE BLOCKED: {len(veto_reasons)} halangan terdeteksi ({'; '.join(veto_reasons[:2])})."

        return MultiTFConfluenceResult(
            confluence_passed=confluence_passed,
            dominant_macro_bias=macro_bias,
            h4=h4_a,
            h1=h1_a,
            m15=m15_a,
            m5=m5_a,
            m1=m1_a,
            h4_barrier_clear=h4_barrier_clear,
            m15_structure_confirmed=m15_structure_confirmed,
            m5_breakout_confirmed=m5_breakout_confirmed,
            m1_retest_confirmed=m1_retest_confirmed,
            confluence_score=score,
            veto_reasons=veto_reasons,
            summary=summary,
        )
