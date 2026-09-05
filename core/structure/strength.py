"""Deterministic measurement of structural momentum and persistence strength."""
from decimal import Decimal
from typing import Optional

class StructureStrengthCalculator:
    """Calculates deterministic structural strength score [0.0, 10.0]. Not a probability."""

    @staticmethod
    def calculate_strength(
        displacement: Optional[Decimal],
        atr: Optional[Decimal],
        swing_distance: Optional[Decimal] = None,
        persistence_count: int = 1,
    ) -> Decimal:
        """
        Calculates strength score based on normalized displacement and persistence.
        Bounded between 0.00 and 10.00.
        """
        score = Decimal("0.0")

        # 1. Displacement component (normalized by ATR)
        if displacement is not None and atr is not None and atr > Decimal("0"):
            disp_ratio = displacement / atr
            score += Decimal("0.5") * disp_ratio * Decimal("5.0")  # Scale factor

        # 2. Swing distance component
        if swing_distance is not None and atr is not None and atr > Decimal("0"):
            dist_ratio = swing_distance / atr
            score += Decimal("0.3") * dist_ratio

        # 3. Persistence component (number of consecutive structural continuations)
        score += Decimal("0.2") * Decimal(str(min(persistence_count, 10)))

        # Clamp between 0.0 and 10.0
        clamped = max(Decimal("0.00"), min(Decimal("10.00"), score))
        return clamped.quantize(Decimal("0.01"))
