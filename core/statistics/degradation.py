"""
Out-Of-Sample degradation evaluator for Statistical Edge Engine V1.
Measures performance degradation across chronological data splits.
"""

from decimal import Decimal
from typing import Optional
from core.statistics.config import StatisticalConfig
from core.statistics.contract import OOSDegradationReport, OOSDegradationStatus, StatisticalMetricRecord


class DegradationEvaluator:
    """
    Evaluates OOS degradation ratio: OOS Expectancy / In-Sample Expectancy.
    """

    def __init__(self, config: Optional[StatisticalConfig] = None):
        self.config = config or StatisticalConfig()

    def evaluate_degradation(
        self,
        is_metrics: StatisticalMetricRecord,
        oos_metrics: StatisticalMetricRecord,
    ) -> OOSDegradationReport:
        """Compares In-Sample against Out-Of-Sample metrics."""
        is_exp = is_metrics.expectancy_r
        oos_exp = oos_metrics.expectancy_r
        is_wr = is_metrics.win_rate
        oos_wr = oos_metrics.win_rate

        if is_exp is None or is_exp <= Decimal("0.0"):
            return OOSDegradationReport(
                is_expectancy=is_exp,
                oos_expectancy=oos_exp,
                expectancy_ratio=None,
                is_win_rate=is_wr,
                oos_win_rate=oos_wr,
                status=OOSDegradationStatus.NOT_APPLICABLE,
                reason="In-sample expectancy is non-positive or undefined; degradation ratio not applicable",
            )

        if oos_exp is None:
            return OOSDegradationReport(
                is_expectancy=is_exp,
                oos_expectancy=None,
                expectancy_ratio=None,
                is_win_rate=is_wr,
                oos_win_rate=oos_wr,
                status=OOSDegradationStatus.NOT_APPLICABLE,
                reason="Out-of-sample expectancy is undefined or empty",
            )

        ratio = (oos_exp / is_exp).quantize(Decimal("0.0001"))

        if ratio <= self.config.oos_collapsed_ratio:
            status = OOSDegradationStatus.COLLAPSED
            reason = f"OOS expectancy collapsed ({ratio} <= {self.config.oos_collapsed_ratio})"
        elif ratio < self.config.oos_degraded_ratio:
            status = OOSDegradationStatus.DEGRADED
            reason = f"OOS expectancy degraded ({ratio} < {self.config.oos_degraded_ratio})"
        else:
            status = OOSDegradationStatus.STABLE
            reason = f"OOS expectancy stable ({ratio} >= {self.config.oos_degraded_ratio})"

        return OOSDegradationReport(
            is_expectancy=is_exp,
            oos_expectancy=oos_exp,
            expectancy_ratio=ratio,
            is_win_rate=is_wr,
            oos_win_rate=oos_wr,
            status=status,
            reason=reason,
        )
