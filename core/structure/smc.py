"""
Smart Money Concepts (SMC) Structure & Order Block Engine.
Extracts:
1. Swings ZigZag points (Highs/Lows)
2. Market Structure Breaks (MSB / BOS / CHoCH)
3. Bullish & Bearish Order Blocks (Bu-OB, Be-OB)
4. Breaker Blocks (Bu-BB, Be-MB)
5. Momentum Validation (Displacement vs ATR)
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Dict, Optional, Sequence


def _get(candle: Any, attr: str) -> Any:
    if isinstance(candle, dict):
        return candle.get(attr)
    return getattr(candle, attr, None)


def _to_epoch(dt: Any) -> int:
    if isinstance(dt, (int, float)):
        return int(dt)
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return 0
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return 0


class SMCEngine:
    """Detects SMC Order Blocks, Breaker Blocks, MSB levels, and ZigZag."""

    def __init__(self, atr_multiplier: float = 1.0):
        self.atr_multiplier = atr_multiplier

    def extract_zigzag(self, swings: Sequence[Any]) -> List[Dict[str, Any]]:
        """
        Converts confirmed swings to a chronological list of (time, value) points for ZigZag line.
        """
        points = []
        for s in swings:
            ts = getattr(s, "timestamp", None)
            price = getattr(s, "price", None)
            stype = getattr(s, "swing_type", None)
            stype_val = getattr(stype, "value", str(stype))
            classification = getattr(s, "classification", None)
            class_val = getattr(classification, "value", str(classification)) if classification else ""

            if ts and price is not None:
                points.append({
                    "time": _to_epoch(ts),
                    "value": float(price),
                    "type": class_val or stype_val,
                    "is_high": "HIGH" in stype_val or class_val in ("HH", "LH"),
                })
        # Sort chronologically by time
        points.sort(key=lambda p: p["time"])
        return points

    def extract_msb_lines(self, structure_events: Sequence[Any], candles: Sequence[Any]) -> List[Dict[str, Any]]:
        """
        Extracts Market Structure Break (MSB) horizontal lines from confirmed structure events.
        """
        lines = []
        if not candles:
            return lines

        last_c = candles[-1]
        last_epoch = _to_epoch(_get(last_c, "timestamp"))

        for ev in structure_events:
            stype = getattr(ev, "structure_type", "")
            price = getattr(ev, "price", None)
            ts = getattr(ev, "timestamp", None)
            direction = getattr(ev, "direction", None)
            dir_val = getattr(direction, "value", str(direction))

            is_bullish = "UP" in str(stype) or "BULLISH" in dir_val
            ev_epoch = _to_epoch(ts)

            if price is not None and ev_epoch > 0:
                lines.append({
                    "type": "MSB_BULLISH" if is_bullish else "MSB_BEARISH",
                    "price": float(price),
                    "start_time": ev_epoch,
                    "end_time": last_epoch,
                    "label": f"MSB ({'Bull' if is_bullish else 'Bear'})",
                    "color": "#00e676" if is_bullish else "#ff4d6d",
                })
        return lines

    def detect_order_blocks(
        self,
        candles: Sequence[Any],
        atr: float,
        lookback: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Detects Order Blocks (Bu-OB and Be-OB).
        - Bu-OB: The last bearish candle before a strong upward impulsive displacement (> 1.0 * ATR).
        - Be-OB: The last bullish candle before a strong downward impulsive displacement (> 1.0 * ATR).
        """
        if len(candles) < 4:
            return []

        c_list = list(candles[-lookback:])
        order_blocks = []
        last_epoch = _to_epoch(_get(c_list[-1], "timestamp"))
        min_displacement = atr * 1.0

        for i in range(1, len(c_list) - 2):
            c_curr = c_list[i]
            c_next1 = c_list[i + 1]
            c_next2 = c_list[i + 2]

            o = float(_get(c_curr, "open"))
            h = float(_get(c_curr, "high"))
            l = float(_get(c_curr, "low"))
            c = float(_get(c_curr, "close"))
            t = _to_epoch(_get(c_curr, "timestamp"))

            n1_o = float(_get(c_next1, "open"))
            n1_c = float(_get(c_next1, "close"))

            n2_c = float(_get(c_next2, "close"))

            # 1. Bullish Order Block (Bu-OB)
            # Candle i is bearish (c < o).
            # Followed by strong upward displacement (close of next 1 or 2 candles surpasses high of candle i by >= min_displacement)
            if c < o:
                disp_up = max(n1_c - h, n2_c - h)
                if disp_up >= min_displacement and (n1_c > n1_o or n2_c > n1_o):
                    mitigated = False
                    end_t = last_epoch
                    for future_c in c_list[i + 2:]:
                        fut_l = float(_get(future_c, "low"))
                        fut_t = _to_epoch(_get(future_c, "timestamp"))
                        if fut_l < l:  # Broken/mitigated
                            mitigated = True
                            end_t = fut_t
                            break

                    order_blocks.append({
                        "id": f"OB-BU-{t}",
                        "type": "Bu-OB",
                        "direction": "BULLISH",
                        "top": h,
                        "bottom": l,
                        "start_time": t,
                        "end_time": end_t,
                        "mitigated": mitigated,
                        "color": "rgba(0, 230, 118, 0.22)",
                        "border_color": "#00e676",
                        "label": "Bu-OB",
                    })

            # 2. Bearish Order Block (Be-OB)
            # Candle i is bullish (c > o).
            # Followed by strong downward displacement (low of candle i - close >= min_displacement)
            elif c > o:
                disp_down = max(l - n1_c, l - n2_c)
                if disp_down >= min_displacement and (n1_c < n1_o or n2_c < n1_o):
                    mitigated = False
                    end_t = last_epoch
                    for future_c in c_list[i + 2:]:
                        fut_h = float(_get(future_c, "high"))
                        fut_t = _to_epoch(_get(future_c, "timestamp"))
                        if fut_h > h:  # Broken/mitigated
                            mitigated = True
                            end_t = fut_t
                            break

                    order_blocks.append({
                        "id": f"OB-BE-{t}",
                        "type": "Be-OB",
                        "direction": "BEARISH",
                        "top": h,
                        "bottom": l,
                        "start_time": t,
                        "end_time": end_t,
                        "mitigated": mitigated,
                        "color": "rgba(255, 77, 109, 0.22)",
                        "border_color": "#ff4d6d",
                        "label": "Be-OB",
                    })

        # Keep recent active or newly mitigated OBs (max 6)
        active_obs = [ob for ob in order_blocks if not ob["mitigated"]][-4:]
        mit_obs = [ob for ob in order_blocks if ob["mitigated"]][-2:]
        return sorted(active_obs + mit_obs, key=lambda x: x["start_time"])

    def detect_breaker_blocks(
        self,
        candles: Sequence[Any],
        order_blocks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Detects Breaker Blocks (Bu-BB, Be-MB):
        - A Bearish OB broken upwards becomes a Bullish Breaker Block (Bu-BB).
        - A Bullish OB broken downwards becomes a Bearish Mitigation Block (Be-MB).
        """
        breakers = []
        if not candles or not order_blocks:
            return breakers

        last_epoch = _to_epoch(_get(candles[-1], "timestamp"))

        for ob in order_blocks:
            if not ob.get("mitigated"):
                continue

            top = ob["top"]
            bottom = ob["bottom"]
            end_t = ob["end_time"]

            if ob["type"] == "Be-OB":
                breakers.append({
                    "id": f"BB-BU-{ob['start_time']}",
                    "type": "Bu-BB",
                    "direction": "BULLISH",
                    "top": top,
                    "bottom": bottom,
                    "start_time": end_t,
                    "end_time": last_epoch,
                    "color": "rgba(0, 176, 255, 0.22)",
                    "border_color": "#00b0ff",
                    "label": "Bu-BB",
                })
            elif ob["type"] == "Bu-OB":
                breakers.append({
                    "id": f"MB-BE-{ob['start_time']}",
                    "type": "Be-MB",
                    "direction": "BEARISH",
                    "top": top,
                    "bottom": bottom,
                    "start_time": end_t,
                    "end_time": last_epoch,
                    "color": "rgba(255, 145, 0, 0.22)",
                    "border_color": "#ff9100",
                    "label": "Be-MB",
                })

        return breakers[-4:]

    def check_momentum(
        self,
        candles: Sequence[Any],
        atr: float,
        direction: str,
    ) -> Dict[str, Any]:
        """
        Evaluates whether genuine institutional momentum / displacement is present.
        Requirements:
        1. Last candle body >= 1.0 * ATR in trade direction OR
           Two consecutive candles in trade direction totaling >= 1.4 * ATR.
        2. Candle closes near high (for BUY) or near low (for SELL) — strong conviction.
        """
        if len(candles) < 2:
            return {"has_momentum": False, "score": 0.0, "reason": "Insufficient candles"}

        c_curr = candles[-1]
        c_prev = candles[-2]

        curr_o = float(_get(c_curr, "open"))
        curr_c = float(_get(c_curr, "close"))
        curr_h = float(_get(c_curr, "high"))
        curr_l = float(_get(c_curr, "low"))

        prev_o = float(_get(c_prev, "open"))
        prev_c = float(_get(c_prev, "close"))

        curr_body = abs(curr_c - curr_o)
        curr_range = max(curr_h - curr_l, 0.00001)

        is_bullish = curr_c > curr_o
        is_bearish = curr_c < curr_o

        if direction.upper() == "BUY":
            body_ratio = curr_body / max(atr, 0.0001)
            close_strength = (curr_c - curr_l) / curr_range

            two_bar_disp = (curr_c - prev_o) if (is_bullish and prev_c > prev_o) else 0.0
            two_bar_ratio = two_bar_disp / max(atr, 0.0001)

            has_momentum = (is_bullish and body_ratio >= 0.9 and close_strength >= 0.60) or (two_bar_ratio >= 1.3)
            return {
                "has_momentum": has_momentum,
                "score": round(max(body_ratio, two_bar_ratio), 2),
                "reason": f"Displacement: {round(max(body_ratio, two_bar_ratio), 2)}x ATR (Bullish conviction)",
            }
        else:
            body_ratio = curr_body / max(atr, 0.0001)
            close_strength = (curr_h - curr_c) / curr_range

            two_bar_disp = (prev_o - curr_c) if (is_bearish and prev_c < prev_o) else 0.0
            two_bar_ratio = two_bar_disp / max(atr, 0.0001)

            has_momentum = (is_bearish and body_ratio >= 0.9 and close_strength >= 0.60) or (two_bar_ratio >= 1.3)
            return {
                "has_momentum": has_momentum,
                "score": round(max(body_ratio, two_bar_ratio), 2),
                "reason": f"Displacement: {round(max(body_ratio, two_bar_ratio), 2)}x ATR (Bearish conviction)",
            }
