"""
Deterministic bootstrap engine for Statistical Edge Engine V1.
Computes empirical resampling distributions with zero non-deterministic randomness.
"""

from decimal import Decimal
import random
from typing import List, Optional, Sequence
from core.statistics.contract import BootstrapMetricResult


class DeterministicBootstrapEngine:
    """
    Performs bootstrap resampling using a deterministic pseudo-random generator
    seeded from cryptographically derived input hashes.
    """

    def __init__(self, seed: int, iterations: int = 10000):
        self.seed = seed
        self.iterations = iterations

    def bootstrap_expectancy(self, r_multiples: Sequence[Decimal]) -> Optional[BootstrapMetricResult]:
        """Bootstraps mean realized R (Expectancy)."""
        if not r_multiples:
            return None

        data = [float(r) for r in r_multiples]
        n = len(data)

        if n == 1:
            val = Decimal(str(round(data[0], 4)))
            pos = Decimal("1.0000") if data[0] > 0 else Decimal("0.0000")
            return BootstrapMetricResult(
                metric="EXPECTANCY_R",
                iterations=self.iterations,
                lower_bound=val,
                median=val,
                upper_bound=val,
                positive_fraction=pos,
            )

        rng = random.Random(self.seed)
        means: List[float] = []
        positive_count = 0

        for _ in range(self.iterations):
            # Resample N observations with replacement
            sample = rng.choices(data, k=n)
            m = sum(sample) / n
            means.append(m)
            if m > 0.0:
                positive_count += 1

        means.sort()
        idx_lower = int(0.025 * self.iterations)
        idx_median = int(0.500 * self.iterations)
        idx_upper = int(0.975 * self.iterations)

        return BootstrapMetricResult(
            metric="EXPECTANCY_R",
            iterations=self.iterations,
            lower_bound=Decimal(str(round(means[idx_lower], 4))),
            median=Decimal(str(round(means[idx_median], 4))),
            upper_bound=Decimal(str(round(means[idx_upper], 4))),
            positive_fraction=Decimal(str(round(positive_count / self.iterations, 4))),
        )

    def bootstrap_win_rate(self, binary_outcomes: Sequence[int]) -> Optional[BootstrapMetricResult]:
        """Bootstraps binary win rate (1 = Win, 0 = Loss)."""
        if not binary_outcomes:
            return None

        n = len(binary_outcomes)
        if n == 1:
            val = Decimal(str(round(float(binary_outcomes[0]), 4)))
            return BootstrapMetricResult(
                metric="WIN_RATE",
                iterations=self.iterations,
                lower_bound=val,
                median=val,
                upper_bound=val,
                positive_fraction=val,
            )

        rng = random.Random(self.seed + 101)  # Distinct deterministic stream
        win_rates: List[float] = []
        pos_count = 0

        for _ in range(self.iterations):
            sample = rng.choices(binary_outcomes, k=n)
            wr = sum(sample) / n
            win_rates.append(wr)
            if wr > 0.50:
                pos_count += 1

        win_rates.sort()
        idx_lower = int(0.025 * self.iterations)
        idx_median = int(0.500 * self.iterations)
        idx_upper = int(0.975 * self.iterations)

        return BootstrapMetricResult(
            metric="WIN_RATE",
            iterations=self.iterations,
            lower_bound=Decimal(str(round(win_rates[idx_lower], 4))),
            median=Decimal(str(round(win_rates[idx_median], 4))),
            upper_bound=Decimal(str(round(win_rates[idx_upper], 4))),
            positive_fraction=Decimal(str(round(pos_count / self.iterations, 4))),
        )
