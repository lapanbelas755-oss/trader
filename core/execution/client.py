"""Remote MT5 Execution Client.
Runs on Trader Machine (macOS), issuing traceable read-only requests across ISecureTransport.
Strictly blocks all trade and order execution methods.
"""
from datetime import datetime, timezone
from decimal import Decimal
import logging
import time
from typing import Any, Optional

from core.execution.contract import (
    AccountInfoReadOnly,
    SymbolInfoReadOnly,
    TerminalInfoReadOnly,
    TickReadOnly,
    TradingProhibitedError,
)
from core.execution.remote_protocol import (
    CURRENT_PROTOCOL_VERSION,
    HealthInfo,
    NodeAction,
    NodeFailureState,
    NodeRequest,
    NodeResponse,
    PositionReadOnly,
    generate_request_id,
)
from core.execution.transport import ISecureTransport

logger = logging.getLogger(__name__)


class RemoteExecutionError(RuntimeError):
    """Raised when remote node returns an error status."""

    def __init__(self, status: NodeFailureState, message: str, response: Optional[NodeResponse] = None):
        super().__init__(f"[{status.value}] {message}")
        self.status = status
        self.response = response


class RemoteExecutionClient:
    """Client proxy managing remote MT5 execution node communications."""

    def __init__(
        self,
        transport: ISecureTransport,
        auth_token: Optional[str] = None,
        default_timeout: float = 5.0,
        protocol_version: str = CURRENT_PROTOCOL_VERSION,
    ) -> None:
        self.transport = transport
        self.auth_token = auth_token
        self.default_timeout = default_timeout
        self.protocol_version = protocol_version
        self._request_counter = 0

    def _execute(self, action: NodeAction, params: Optional[dict[str, Any]] = None, timeout: Optional[float] = None) -> NodeResponse:
        self._request_counter += 1
        req_id = generate_request_id(action, self._request_counter)
        req = NodeRequest(
            request_id=req_id,
            action=action,
            params=params or {},
            protocol_version=self.protocol_version,
            auth_token=self.auth_token,
        )

        start_time = time.perf_counter()
        t_limit = timeout if timeout is not None else self.default_timeout
        response = self.transport.send_request(req, timeout_seconds=t_limit)
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # SAFE AUDIT LOGGING: request_id, operation, timestamp, status, latency. Never secrets.
        logger.info(
            f"EXECUTION_NODE_AUDIT: request_id={response.request_id} op={action.value} "
            f"status={response.status.value} latency_ms={latency_ms:.2f} node_id={response.node_id}"
        )

        if response.status != NodeFailureState.SUCCESS:
            raise RemoteExecutionError(
                status=response.status,
                message=response.error_message or f"Remote node operation failed with status {response.status.value}",
                response=response,
            )

        return response

    # --- Read-Only Operations ---

    def get_health(self) -> HealthInfo:
        """Fetch remote execution node health metrics."""
        resp = self._execute(NodeAction.GET_HEALTH)
        return HealthInfo.model_validate(resp.payload or {})

    def get_terminal_info(self) -> TerminalInfoReadOnly:
        """Fetch read-only terminal status from remote MT5."""
        resp = self._execute(NodeAction.GET_TERMINAL_INFO)
        return TerminalInfoReadOnly.model_validate(resp.payload or {})

    def get_account_info(self) -> AccountInfoReadOnly:
        """Fetch read-only account equity and balance with masked credentials."""
        resp = self._execute(NodeAction.GET_ACCOUNT_INFO)
        return AccountInfoReadOnly.model_validate(resp.payload or {})

    def get_symbol_info(self, symbol: str) -> SymbolInfoReadOnly:
        """Fetch read-only symbol specifications."""
        resp = self._execute(NodeAction.GET_SYMBOL_INFO, params={"symbol": symbol.strip().upper()})
        return SymbolInfoReadOnly.model_validate(resp.payload or {})

    def get_tick(self, symbol: str) -> TickReadOnly:
        """Fetch latest price tick for an instrument."""
        resp = self._execute(NodeAction.GET_TICK, params={"symbol": symbol.strip().upper()})
        return TickReadOnly.model_validate(resp.payload or {})

    def get_positions(self) -> list[PositionReadOnly]:
        """Fetch read-only open broker positions."""
        resp = self._execute(NodeAction.GET_POSITIONS)
        raw_list = (resp.payload or {}).get("positions", [])
        return [PositionReadOnly.model_validate(p) for p in raw_list]

    # --- PERMANENT HARD TRADING FIREWALL ---

    def send_order(self, *args: Any, **kwargs: Any) -> Any:
        logger.critical("FORBIDDEN CALL: send_order attempted on read-only RemoteExecutionClient.")
        raise TradingProhibitedError("send_order is permanently disabled in Trader Machine V1 execution client.")

    def modify_order(self, *args: Any, **kwargs: Any) -> Any:
        logger.critical("FORBIDDEN CALL: modify_order attempted on read-only RemoteExecutionClient.")
        raise TradingProhibitedError("modify_order is permanently disabled in Trader Machine V1 execution client.")

    def close_position(self, *args: Any, **kwargs: Any) -> Any:
        logger.critical("FORBIDDEN CALL: close_position attempted on read-only RemoteExecutionClient.")
        raise TradingProhibitedError("close_position is permanently disabled in Trader Machine V1 execution client.")
