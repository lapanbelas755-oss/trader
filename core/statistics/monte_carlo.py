"""
Deterministic Monte Carlo permutation engine for Statistical Edge Engine V1.
Analyzes sequence-risk and path variability without modifying realized trade outcomes.
"""

from decimal import Decimal
import random
from typing import List, Optional, Sequence
from core.statistics.contract import MonteCarloMetricResult


class MonteCarloPermutationEngine:
    """
    Evaluates equity path sequence risk through deterministic permutation resampling.
    """

    def __init__(self, seed: int, iterations: int = 1000):
        self.seed = seed
        self.iterations = iterations

    def run_permutation_analysis(self, r_multiples: Sequence[Decimal]) -> Optional[MonteCarloMetricResult]:
        """Reshuffles realized trade sequence to estimate drawdown distributions."""
        if not r_multiples:
            return None

        data = [float(r) for r in r_multiples]
        n = len(data)

        if n == 1:
            r0 = data[0]
            dd = max(0.0, -r0)
            return MonteCarloMetricResult(
                iterations=self.iterations,
                drawdown_p95=Decimal(str(round(dd, 4))),
                drawdown_p99=Decimal(str(round(dd, 4))),
                drawdown_median=Decimal(str(round(dd, 4))),
                terminal_r_p5=Decimal(str(round(r0, 4))),
                terminal_r_median=Decimal(str(round(r0, 4))),
                prob_negative_terminal=Decimal("1.0000") if r0 < 0 else Decimal("0.0000"),
            )

        rng = random.Random(self.seed + 202)
        max_drawdowns: List[float] = []
        terminal_rs: List[float] = []
        terminal_sum = sum(data)

        for _ in range(self.iterations):
            # Shuffle without replacement to evaluate order dependency
            permuted = rng.sample(data, k=n)

            peak = 0.0
            cum_r = 0.0
            max_dd = 0.0

            for r in permuted:
                cum_r += r
                if cum_r > peak:
                    peak = cum_r
                dd = peak - cum_r
                if dd > max_dd:
                    max_dd = dd

            max_drawdowns.append(max_dd)
            terminal_rs.append(cum_r)

        max_drawdowns.sort()
        idx_50 = int(0.50 * self.iterations)
        idx_95 = int(0.95 * self.iterations)
        idx_99 = int(0.99 * self.iterations)

        prob_negative = 1.0 if terminal_sum < 0.0 else 0.0

        return MonteCarloMetricResult(
            iterations=self.iterations,
            drawdown_p95=Decimal(str(round(max_drawdowns[idx_95], 4))),
            drawdown_p99=Decimal(str(round(max_drawdowns[idx_99], 4))),
            drawdown_median=Decimal(str(round(max_drawdowns[idx_50], 4))),
            terminal_r_p5=Decimal(str(round(terminal_sum, 4))),
            terminal_r_median=Decimal(str(round(terminal_sum, 4))),
            prob_negative_terminal=Decimal(str(round(prob_negative, 4))),
        )
