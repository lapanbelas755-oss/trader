"""
Collision manager for Backtest Engine V1.
Enforces trade collision policies (e.g. MAX_ONE_ACTIVE_TRADE_PER_SYMBOL)
without silently discarding overlapping opportunities.
"""

from datetime import datetime
from typing import List, Optional, Set
from core.backtest.config import BacktestConfig
from core.backtest.contract import BacktestTradeRecord, CollisionPolicy, TradeResult, TradeStatus


class CollisionManager:
    """
    Manages active position overlap and records SKIPPED_ACTIVE_TRADE.
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()

    def is_symbol_occupied(
        self,
        symbol: str,
        entry_time: datetime,
        active_trades: List[BacktestTradeRecord],
    ) -> Optional[BacktestTradeRecord]:
        """
        Checks if there is an open trade in the symbol at entry_time.
        A trade is active if prior_trade.entry_time <= entry_time and prior_trade.exit_time > entry_time.
        """
        if self.config.collision_policy == CollisionPolicy.ALLOW_ALL.value:
            return None

        matching_active = [
            t for t in active_trades
            if t.symbol == symbol
            and t.status == TradeStatus.CLOSED
            and t.result not in (TradeResult.SKIPPED_ACTIVE_TRADE, TradeResult.INVALID, TradeResult.DATA_ERROR)
            and t.entry_time <= entry_time
            and (t.exit_time is not None and t.exit_time > entry_time)
        ]

        if len(matching_active) >= self.config.max_active_trades:
            return matching_active[0]
        return None

    def mark_skipped_trade(
        self,
        candidate_trade: BacktestTradeRecord,
        blocking_trade: BacktestTradeRecord,
    ) -> BacktestTradeRecord:
        """Flags trade as SKIPPED_ACTIVE_TRADE with auditable justification."""
        candidate_trade.result = TradeResult.SKIPPED_ACTIVE_TRADE
        candidate_trade.status = TradeStatus.SKIPPED
        candidate_trade.exit_time = candidate_trade.entry_time
        candidate_trade.exit_price = candidate_trade.entry_price
        candidate_trade.r_multiple = None
        candidate_trade.mae_r = None
        candidate_trade.mfe_r = None
        candidate_trade.ambiguity_reason = (
            f"Active trade {blocking_trade.setup_id} open from "
            f"{blocking_trade.entry_time.isoformat()} to {blocking_trade.exit_time.isoformat() if blocking_trade.exit_time else 'OPEN'}"
        )
        return candidate_trade
