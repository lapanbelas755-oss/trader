"""Execution Service Layer V1.
Provides a unified, read-only interface for Trader Machine to inspect remote terminal state,
market quotes, and demo account status.
"""
from typing import Any, Optional

from core.execution.client import RemoteExecutionClient
from core.execution.contract import (
    AccountInfoReadOnly,
    SymbolInfoReadOnly,
    TerminalInfoReadOnly,
    TickReadOnly,
    TradingProhibitedError,
)
from core.execution.remote_protocol import HealthInfo, PositionReadOnly


class ExecutionService:
    """Read-only execution service coordinator."""

    def __init__(self, client: RemoteExecutionClient) -> None:
        self.client = client

    def check_health(self) -> HealthInfo:
        """Query execution node health."""
        return self.client.get_health()

    def get_terminal(self) -> TerminalInfoReadOnly:
        """Query terminal specifications."""
        return self.client.get_terminal_info()

    def get_account(self) -> AccountInfoReadOnly:
        """Query account balance and equity."""
        return self.client.get_account_info()

    def get_symbol(self, symbol: str) -> SymbolInfoReadOnly:
        """Query symbol specifications and bid/ask."""
        return self.client.get_symbol_info(symbol)

    def get_current_tick(self, symbol: str) -> TickReadOnly:
        """Query latest market tick."""
        return self.client.get_tick(symbol)

    def get_open_positions(self) -> list[PositionReadOnly]:
        """Query current open positions."""
        return self.client.get_positions()

    # --- Trading Prohibitions ---

    def execute_order(self, *args: Any, **kwargs: Any) -> Any:
        raise TradingProhibitedError("execute_order is disabled in ExecutionService V1 (Read-Only Phase).")

    def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
        raise TradingProhibitedError("cancel_order is disabled in ExecutionService V1 (Read-Only Phase).")
