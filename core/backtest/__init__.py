"""
Backtest Engine package for Trader Machine V1.
Deterministic historical trade simulation, R-multiples, and performance metrics.
"""

from core.backtest.config import BacktestConfig
from core.backtest.contract import (
    BacktestRunRecord,
    BacktestTradeRecord,
    CollisionPolicy,
    EntryPriceType,
    SplitMetrics,
    TradeMetrics,
    TradeResult,
    TradeStatus,
)
from core.backtest.engine import BacktestEngine, BacktestRunResult
from core.backtest.metrics import BacktestMetricsCalculator
from core.backtest.report import BacktestReportGenerator
from core.backtest.rules import BacktestRuleEngine
from core.backtest.simulator import TradePathSimulator

__all__ = [
    "BacktestConfig",
    "BacktestTradeRecord",
    "BacktestRunRecord",
    "TradeMetrics",
    "SplitMetrics",
    "TradeResult",
    "TradeStatus",
    "EntryPriceType",
    "CollisionPolicy",
    "BacktestEngine",
    "BacktestRunResult",
    "BacktestRuleEngine",
    "TradePathSimulator",
    "BacktestMetricsCalculator",
    "BacktestReportGenerator",
]
