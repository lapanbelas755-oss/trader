"""
Statistical Edge package for Trader Machine V1.
Deterministic statistical evidence evaluation, Wilson intervals, bootstrapping,
and multi-factor edge classification.
"""

from core.statistics.bootstrap import DeterministicBootstrapEngine
from core.statistics.classifier import EdgeClassifier
from core.statistics.config import StatisticalConfig
from core.statistics.contract import (
    BootstrapMetricResult,
    EdgeClassification,
    MonteCarloMetricResult,
    OOSDegradationReport,
    OOSDegradationStatus,
    SampleReliability,
    SegmentMetricRecord,
    SegmentType,
    StatisticalMetricRecord,
    StatisticalRunRecord,
    WilsonConfidenceInterval,
)
from core.statistics.degradation import DegradationEvaluator
from core.statistics.engine import StatisticalEdgeEngine, StatisticalRunResult
from core.statistics.intervals import WilsonScoreIntervalCalculator
from core.statistics.monte_carlo import MonteCarloPermutationEngine
from core.statistics.report import StatisticalReportGenerator
from core.statistics.segmentation import SegmentationEngine

__all__ = [
    "StatisticalConfig",
    "EdgeClassification",
    "SampleReliability",
    "OOSDegradationStatus",
    "SegmentType",
    "WilsonConfidenceInterval",
    "BootstrapMetricResult",
    "MonteCarloMetricResult",
    "OOSDegradationReport",
    "StatisticalMetricRecord",
    "SegmentMetricRecord",
    "StatisticalRunRecord",
    "WilsonScoreIntervalCalculator",
    "DeterministicBootstrapEngine",
    "MonteCarloPermutationEngine",
    "DegradationEvaluator",
    "EdgeClassifier",
    "SegmentationEngine",
    "StatisticalReportGenerator",
    "StatisticalEdgeEngine",
    "StatisticalRunResult",
]
