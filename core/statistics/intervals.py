"""
Interval calculation utilities for Statistical Edge Engine V1.
Implements robust Wilson score interval for binomial proportions.
"""

from decimal import Decimal
import math
from typing import Optional
from core.statistics.contract import WilsonConfidenceInterval


class WilsonScoreIntervalCalculator:
    """
    Computes Wilson score confidence interval for binomial proportion (win rate).
    Prevents degenerate zero-variance intervals on small samples or boundary probabilities.
    """

    # Two-sided standard normal quantiles for common confidence levels
    Z_VALUES = {
        Decimal("0.90"): 1.6448536269514722,
        Decimal("0.95"): 1.959963984540054,
        Decimal("0.99"): 2.5758293035489004,
    }

    @classmethod
    def calculate(
        cls,
        wins: int,
        total_decisions: int,
        confidence_level: Decimal = Decimal("0.95"),
    ) -> Optional[WilsonConfidenceInterval]:
        """
        Calculates Wilson confidence interval for binomial win rate: wins / total_decisions.
        Returns None if total_decisions <= 0.
        """
        if total_decisions <= 0 or wins < 0 or wins > total_decisions:
            return None

        z = cls.Z_VALUES.get(confidence_level, 1.959963984540054)
        n = float(total_decisions)
        p_hat = float(wins) / n
        z2 = z * z

        denominator = 1.0 + (z2 / n)
        center = (p_hat + (z2 / (2.0 * n))) / denominator
        margin = (z / denominator) * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z2 / (4.0 * n * n)))

        lower = max(0.0, center - margin)
        upper = min(1.0, center + margin)

        return WilsonConfidenceInterval(
            lower_bound=Decimal(str(round(lower, 4))),
            upper_bound=Decimal(str(round(upper, 4))),
            confidence_level=confidence_level,
        )
