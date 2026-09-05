"""Break of Structure (BOS) and Change of Character (CHoCH) detector."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence, Optional
from core.structure.classifier import SwingClassifier
from core.structure.contract import BreakType, ConfirmedSwing, StructureClassification, StructureDirection, StructureEvent, SwingType

class BreakDetector:
    """Detects BOS and CHoCH events based on candle closes beyond confirmed swing levels."""

    def __init__(
        self,
        default_min_displacement: Decimal = Decimal("0.000100"),
        min_displacement_atr_mult: Decimal = Decimal("0.10"),
        fallback_displacement: Optional[Decimal] = None,
    ):
        self.default_min_displacement = fallback_displacement or default_min_displacement
        self.min_displacement_atr_mult = min_displacement_atr_mult
        self.classifier = SwingClassifier()

    def _get_attr(self, obj: Any, attr: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(attr)
        return getattr(obj, attr, None)

    def detect_breaks(
        self,
        candles: Sequence[Any],
        swings: Sequence[ConfirmedSwing],
        displacement_map: dict[datetime, Decimal] | None = None,
    ) -> list[StructureEvent]:
        """
        Detects BOS and CHoCH events sequentially through candles.
        Only swings with confirmed_at <= candle.timestamp are known.
        Wick penetration alone is rejected.
        """
        disp_lookup = displacement_map or {}
        events: list[StructureEvent] = []

        candle_list = list(candles)
        if not candle_list:
            return []

        def get_ts(c: Any) -> datetime:
            t = self._get_attr(c, "timestamp")
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

        candle_list.sort(key=get_ts)

        # Track broken swings to prevent repeated triggers on the exact same swing level
        broken_swing_ids: set[str] = set()

        for c in candle_list:
            ts = get_ts(c)
            symbol = str(self._get_attr(c, "symbol")).strip().upper()
            timeframe = str(self._get_attr(c, "timeframe")).strip().upper()
            close_p = Decimal(str(self._get_attr(c, "close")))
            high_p = Decimal(str(self._get_attr(c, "high")))
            low_p = Decimal(str(self._get_attr(c, "low")))

            val_disp = disp_lookup.get(ts)
            min_disp = val_disp if (val_disp is not None and val_disp > Decimal("0")) else self.default_min_displacement

            # Available swings known at this exact timestamp (causality check)
            known_swings = [s for s in swings if s.confirmed_at <= ts]
            if not known_swings:
                continue

            if len(known_swings) >= 2:
                classified_swings = self.classifier.classify_swings(known_swings)
                direction = self.classifier.get_structure_direction(classified_swings)
            else:
                classified_swings = list(known_swings)
                direction = StructureDirection.UNDEFINED

            active_highs = [s for s in classified_swings if s.swing_type == SwingType.SWING_HIGH and s.swing_id not in broken_swing_ids]
            active_lows = [s for s in classified_swings if s.swing_type == SwingType.SWING_LOW and s.swing_id not in broken_swing_ids]

            # 1. Check Bullish Break (above active high)
            if active_highs:
                target_high = active_highs[-1]
                # Wick only penetration check: high exceeded level, but close is <= level -> NOT A BREAK
                if high_p > target_high.price and close_p <= target_high.price:
                    pass  # Wick penetration alone is explicitly ignored
                elif close_p > target_high.price:
                    disp = close_p - target_high.price
                    if disp >= min_disp:
                        broken_swing_ids.add(target_high.swing_id)
                        # Check whether this high was a LH or if structure was BEARISH -> CHOCH_UP
                        if direction == StructureDirection.BEARISH or target_high.classification == StructureClassification.LH:
                            events.append(StructureEvent(
                                symbol=symbol,
                                timeframe=timeframe,
                                structure_type=BreakType.CHOCH_UP.value,
                                price=close_p,
                                timestamp=ts,
                                confirmed_at=ts,
                                reference_swing_id=target_high.swing_id,
                                direction=StructureDirection.BULLISH,
                                displacement=disp,
                            ))
                        else:
                            # Continuation break -> BOS_BULLISH
                            events.append(StructureEvent(
                                symbol=symbol,
                                timeframe=timeframe,
                                structure_type=BreakType.BOS_BULLISH.value,
                                price=close_p,
                                timestamp=ts,
                                confirmed_at=ts,
                                reference_swing_id=target_high.swing_id,
                                direction=StructureDirection.BULLISH,
                                displacement=disp,
                            ))

            # 2. Check Bearish Break (below active low)
            if active_lows:
                target_low = active_lows[-1]
                # Wick only penetration check
                if low_p < target_low.price and close_p >= target_low.price:
                    pass  # Wick penetration alone is explicitly ignored
                elif close_p < target_low.price:
                    disp = target_low.price - close_p
                    if disp >= min_disp:
                        broken_swing_ids.add(target_low.swing_id)
                        # Check whether this low was a HL or if structure was BULLISH -> CHOCH_DOWN
                        if direction == StructureDirection.BULLISH or target_low.classification == StructureClassification.HL:
                            events.append(StructureEvent(
                                symbol=symbol,
                                timeframe=timeframe,
                                structure_type=BreakType.CHOCH_DOWN.value,
                                price=close_p,
                                timestamp=ts,
                                confirmed_at=ts,
                                reference_swing_id=target_low.swing_id,
                                direction=StructureDirection.BEARISH,
                                displacement=disp,
                            ))
                        else:
                            # Continuation break -> BOS_BEARISH
                            events.append(StructureEvent(
                                symbol=symbol,
                                timeframe=timeframe,
                                structure_type=BreakType.BOS_BEARISH.value,
                                price=close_p,
                                timestamp=ts,
                                confirmed_at=ts,
                                reference_swing_id=target_low.swing_id,
                                direction=StructureDirection.BEARISH,
                                displacement=disp,
                            ))

        return events
