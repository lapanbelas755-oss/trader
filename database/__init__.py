"""Database package for Trader Machine V1."""
from database.connection import get_engine, get_session_factory, check_connection
from database.models import (
    Base,
    MarketTick,
    MarketCandle,
    MarketFeature,
    MarketStructure,
    LiquidityLevel,
    Setup,
    SetupEvidence,
    ResearchDataset,
    ResearchRun,
    ResearchSetupOccurrence,
    BacktestRun,
    BacktestTrade,
)
from database.migrate import run_migrations

__all__ = [
    "get_engine",
    "get_session_factory",
    "check_connection",
    "Base",
    "MarketTick",
    "MarketCandle",
    "MarketFeature",
    "MarketStructure",
    "LiquidityLevel",
    "Setup",
    "SetupEvidence",
    "ResearchDataset",
    "ResearchRun",
    "ResearchSetupOccurrence",
    "BacktestRun",
    "BacktestTrade",
    "run_migrations",
]

