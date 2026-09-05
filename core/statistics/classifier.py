"""
Edge classifier for Statistical Edge Engine V1.
Implements objective multi-factor classification rules without arbitrary overclaiming.
"""

from decimal import Decimal
from typing import Optional
from core.statistics.config import StatisticalConfig
from core.statistics.contract import (
    BootstrapMetricResult,
    EdgeClassification,
    OOSDegradationReport,
    OOSDegradationStatus,
    SampleReliability,
    StatisticalMetricRecord,
)


class EdgeClassifier:
    """
    Evaluates statistical criteria to classify market edge hypotheses into:
    INSUFFICIENT_DATA, NEGATIVE_EDGE, NO_CLEAR_EDGE, PRELIMINARY_EDGE, POTENTIAL_EDGE, ROBUST_EDGE, INVALID_DATA.
    """

    def __init__(self, config: Optional[StatisticalConfig] = None):
        self.config = config or StatisticalConfig()

    def classify_sample_size(self, sample_size: int) -> SampleReliability:
        """Categorizes sample size into reliability tiers."""
        if sample_size < self.config.min_sample_preliminary:
            return SampleReliability.INSUFFICIENT_DATA
        elif sample_size < self.config.min_sample_relevant:
            return SampleReliability.PRELIMINARY
        else:
            return SampleReliability.STATISTICALLY_RELEVANT_CANDIDATE

    def classify_edge(
        self,
        overall_metrics: StatisticalMetricRecord,
        bootstrap_exp: Optional[BootstrapMetricResult] = None,
        degradation_report: Optional[OOSDegradationReport] = None,
        val_metrics: Optional[StatisticalMetricRecord] = None,
        data_quality_ok: bool = True,
    ) -> EdgeClassification:
        """
        Determines EdgeClassification through rigorous multi-factor validation.
        """
        if not data_quality_ok:
            return EdgeClassification.INVALID_DATA

        n = overall_metrics.sample_size
        if n < self.config.min_sample_preliminary:
            return EdgeClassification.INSUFFICIENT_DATA

        exp = overall_metrics.expectancy_r
        if exp is None or exp <= Decimal("0.0"):
            return EdgeClassification.NEGATIVE_EDGE

        # If bootstrap is available, check positive fraction
        pos_frac = bootstrap_exp.positive_fraction if bootstrap_exp else Decimal("0.5")

        # Preliminary Edge tier: 30 <= N < 100 with positive expectancy
        if n < self.config.min_sample_relevant:
            if pos_frac >= Decimal("0.70") and overall_metrics.max_drawdown_r <= self.config.max_acceptable_dd_r:
                return EdgeClassification.PRELIMINARY_EDGE
            return EdgeClassification.NO_CLEAR_EDGE

        # N >= 100: evaluate OOS and robustness
        if degradation_report is None or degradation_report.status == OOSDegradationStatus.NOT_APPLICABLE:
            if pos_frac >= Decimal("0.75"):
                return EdgeClassification.POTENTIAL_EDGE
            return EdgeClassification.NO_CLEAR_EDGE

        if degradation_report.status == OOSDegradationStatus.COLLAPSED:
            return EdgeClassification.NO_CLEAR_EDGE

        # Check Validation and OOS positive expectancy
        val_positive = val_metrics is not None and val_metrics.expectancy_r is not None and val_metrics.expectancy_r > Decimal("0.0")
        oos_positive = degradation_report.oos_expectancy is not None and degradation_report.oos_expectancy > Decimal("0.0")

        # ROBUST_EDGE requires all criteria to hold simultaneously
        if (
            degradation_report.status == OOSDegradationStatus.STABLE
            and oos_positive
            and val_positive
            and pos_frac >= Decimal("0.85")
            and overall_metrics.max_drawdown_r <= self.config.max_acceptable_dd_r
        ):
            return EdgeClassification.ROBUST_EDGE

        if oos_positive and pos_frac >= Decimal("0.75"):
            return EdgeClassification.POTENTIAL_EDGE

        return EdgeClassification.NO_CLEAR_EDGE
