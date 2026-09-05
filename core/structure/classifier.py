"""Swing classification (HH, HL, LH, LL, EQH, EQL) and directional state tracking."""
from decimal import Decimal
from typing import Sequence
from core.structure.contract import ConfirmedSwing, StructureClassification, StructureDirection, SwingType

class SwingClassifier:
    """Classifies confirmed swings and determines current directional structure."""

    def __init__(self, default_tolerance: Decimal = Decimal("0.000100")):
        self.default_tolerance = default_tolerance

    def classify_swings(
        self,
        swings: Sequence[ConfirmedSwing],
        tolerance_map: dict[str, Decimal] | None = None,
    ) -> list[ConfirmedSwing]:
        """
        Classifies swings chronologically by confirmed_at.
        Does not rewrite historical classifications.
        """
        tolerance_lookup = tolerance_map or {}
        classified: list[ConfirmedSwing] = []
        prev_high: ConfirmedSwing | None = None
        prev_low: ConfirmedSwing | None = None

        # Swings must be processed in chronological confirmation order
        sorted_swings = sorted(swings, key=lambda s: (s.confirmed_at, s.timestamp))

        for swing in sorted_swings:
            tol = tolerance_lookup.get(swing.swing_id, self.default_tolerance)
            classification = None
            ref_id = None

            if swing.swing_type == SwingType.SWING_HIGH:
                if prev_high is not None:
                    ref_id = prev_high.swing_id
                    diff = abs(swing.price - prev_high.price)
                    if diff <= tol:
                        classification = StructureClassification.EQH
                    elif swing.price > prev_high.price:
                        classification = StructureClassification.HH
                    else:
                        classification = StructureClassification.LH
                prev_high = swing
            else:  # SWING_LOW
                if prev_low is not None:
                    ref_id = prev_low.swing_id
                    diff = abs(swing.price - prev_low.price)
                    if diff <= tol:
                        classification = StructureClassification.EQL
                    elif swing.price > prev_low.price:
                        classification = StructureClassification.HL
                    else:
                        classification = StructureClassification.LL
                prev_low = swing

            # Re-construct immutable swing with classification
            updated_swing = ConfirmedSwing(
                swing_id=swing.swing_id,
                symbol=swing.symbol,
                timeframe=swing.timeframe,
                swing_type=swing.swing_type,
                price=swing.price,
                timestamp=swing.timestamp,
                confirmed_at=swing.confirmed_at,
                classification=classification,
                reference_swing_id=ref_id,
            )
            classified.append(updated_swing)

        return classified

    def get_structure_direction(self, confirmed_swings: Sequence[ConfirmedSwing]) -> StructureDirection:
        """
        Determines current directional structure from confirmed swings sequence.
        Bullish: HH and HL sequence
        Bearish: LL and LH sequence
        """
        highs = [s for s in confirmed_swings if s.swing_type == SwingType.SWING_HIGH and s.classification]
        lows = [s for s in confirmed_swings if s.swing_type == SwingType.SWING_LOW and s.classification]

        if not highs or not lows:
            return StructureDirection.UNDEFINED

        last_high = highs[-1]
        last_low = lows[-1]

        # Check Bullish: last high is HH and last low is HL
        if last_high.classification == StructureClassification.HH and last_low.classification == StructureClassification.HL:
            return StructureDirection.BULLISH

        # Check Bearish: last low is LL and last high is LH
        if last_low.classification == StructureClassification.LL and last_high.classification == StructureClassification.LH:
            return StructureDirection.BEARISH

        # Check Transition: high is HH but low is LL, or high is LH but low is HL
        if (last_high.classification == StructureClassification.HH and last_low.classification == StructureClassification.LL) or \
           (last_high.classification == StructureClassification.LH and last_low.classification == StructureClassification.HL):
            return StructureDirection.TRANSITION

        return StructureDirection.MIXED

    def derive_direction(self, confirmed_swings: Sequence[ConfirmedSwing]) -> StructureDirection:
        """Alias for get_structure_direction."""
        return self.get_structure_direction(confirmed_swings)
