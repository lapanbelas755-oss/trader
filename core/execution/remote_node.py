"""Remote MT5 Execution Node Server-Side Interface & Mock Implementation.
Enforces a hard read-only firewall on the remote execution node.
"""
from abc import ABC, abstractmethod
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
    BLOCKED_TRADE_ACTIONS,
    CURRENT_PROTOCOL_VERSION,
    HealthInfo,
    NodeAction,
    NodeFailureState,
    NodeIdentity,
    NodeRequest,
    NodeResponse,
    PositionReadOnly,
)

logger = logging.getLogger(__name__)


class IRemoteExecutionNode(ABC):
    """Abstract interface for the remote Windows execution node."""

    @abstractmethod
    def get_identity(self) -> NodeIdentity:
        """Return the identity specification of this node."""
        pass

    @abstractmethod
    def handle_request(self, request: NodeRequest) -> NodeResponse:
        """Process a remote protocol request and generate a standardized response."""
        pass


class MockExecutionNode(IRemoteExecutionNode):
    """Hermetic mock implementation of the remote Windows MT5 execution node."""

    def __init__(
        self,
        node_id: str = "win-node-mt5-demo-01",
        node_name: str = "Windows MT5 Demo Node",
        mt5_connected: bool = True,
        terminal_running: bool = True,
        authorized_tokens: Optional[set[str]] = None,
        symbols_available: Optional[list[str]] = None,
        mock_positions: Optional[list[PositionReadOnly]] = None,
        start_time: Optional[float] = None,
    ) -> None:
        self.identity = NodeIdentity(
            node_id=node_id,
            node_name=node_name,
            node_version="1.0.0",
            protocol_version=CURRENT_PROTOCOL_VERSION,
            environment="DEMO",
            host_os="Windows Server 2022",
        )
        self.mt5_connected = mt5_connected
        self.terminal_running = terminal_running
        self.authorized_tokens = authorized_tokens
        self.symbols_available = symbols_available if symbols_available is not None else ["EURUSD", "GBPUSD"]
        self.start_time = start_time or time.time()

        self.mock_positions = mock_positions if mock_positions is not None else [
            PositionReadOnly(
                ticket=10928371,
                symbol="EURUSD",
                type="BUY",
                volume=Decimal("0.10"),
                price_open=Decimal("1.14100"),
                sl=Decimal("1.13900"),
                tp=Decimal("1.14500"),
                price_current=Decimal("1.14120"),
                profit=Decimal("20.00"),
                time=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            )
        ]

    def get_identity(self) -> NodeIdentity:
        return self.identity

    def handle_request(self, request: NodeRequest) -> NodeResponse:
        # 1. HARD READ-ONLY FIREWALL: reject trading actions immediately
        if request.action in BLOCKED_TRADE_ACTIONS:
            logger.critical(f"BLOCKED TRADING ACTION ATTEMPTED ON NODE: {request.action}")
            raise TradingProhibitedError(
                f"Trading operation '{request.action.value}' is permanently prohibited on this read-only node."
            )

        # 2. Protocol Version Compatibility Check
        req_major = request.protocol_version.split(".")[0]
        node_major = self.identity.protocol_version.split(".")[0]
        if req_major != node_major:
            return NodeResponse(
                node_id=self.identity.node_id,
                protocol_version=self.identity.protocol_version,
                request_id=request.request_id,
                status=NodeFailureState.PROTOCOL_ERROR,
                error_message=(
                    f"Protocol version mismatch: client '{request.protocol_version}' vs node '{self.identity.protocol_version}'"
                ),
            )

        # 3. Authentication Check
        if self.authorized_tokens is not None:
            if not request.auth_token or request.auth_token not in self.authorized_tokens:
                return NodeResponse(
                    node_id=self.identity.node_id,
                    protocol_version=self.identity.protocol_version,
                    request_id=request.request_id,
                    status=NodeFailureState.AUTH_FAILED,
                    error_message="Authentication failed: invalid or missing bearer token.",
                )

        # 4. Check MT5 Connection for MT5-dependent operations
        if request.action != NodeAction.GET_HEALTH:
            if not self.mt5_connected or not self.terminal_running:
                return NodeResponse(
                    node_id=self.identity.node_id,
                    protocol_version=self.identity.protocol_version,
                    request_id=request.request_id,
                    status=NodeFailureState.MT5_OFFLINE,
                    error_message="MetaTrader 5 terminal is disconnected or offline on remote host.",
                )

        # 5. Route Action
        match request.action:
            case NodeAction.GET_HEALTH:
                health = HealthInfo(
                    status="HEALTHY" if (self.mt5_connected and self.terminal_running) else "DEGRADED",
                    mt5_connected=self.mt5_connected,
                    terminal_running=self.terminal_running,
                    uptime_seconds=time.time() - self.start_time,
                    latency_internal_ms=0.8,
                )
                return NodeResponse(
                    node_id=self.identity.node_id,
                    protocol_version=self.identity.protocol_version,
                    request_id=request.request_id,
                    status=NodeFailureState.SUCCESS,
                    payload=health.model_dump(),
                )

            case NodeAction.GET_TERMINAL_INFO:
                term_info = TerminalInfoReadOnly(
                    connected=self.mt5_connected,
                    trade_allowed=False,  # Enforce read-only
                    name="MetaTrader 5 Windows Node",
                    path="C:\\Program Files\\MetaTrader 5\\terminal64.exe",
                    data_path="C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\Instance",
                    company="Exness Technologies Ltd",
                    version="5.00",
                    build=4300,
                )
                return NodeResponse(
                    node_id=self.identity.node_id,
                    protocol_version=self.identity.protocol_version,
                    request_id=request.request_id,
                    status=NodeFailureState.SUCCESS,
                    payload=term_info.model_dump(),
                )

            case NodeAction.GET_ACCOUNT_INFO:
                acc_info = AccountInfoReadOnly(
                    login_masked="992****",
                    server="Exness-Demo",
                    currency="USD",
                    balance=Decimal("25000.00"),
                    equity=Decimal("25020.00"),
                    margin=Decimal("200.00"),
                    margin_free=Decimal("24820.00"),
                    margin_level=Decimal("12510.00"),
                    leverage=200,
                    trade_allowed=False,
                    trade_mode="DEMO",
                )
                # Convert Decimals to string/float for JSON-serializable payload
                return NodeResponse(
                    node_id=self.identity.node_id,
                    protocol_version=self.identity.protocol_version,
                    request_id=request.request_id,
                    status=NodeFailureState.SUCCESS,
                    payload=acc_info.model_dump(mode="json"),
                )

            case NodeAction.GET_SYMBOL_INFO:
                symbol = request.params.get("symbol", "").upper()
                if not symbol or symbol not in self.symbols_available:
                    return NodeResponse(
                        node_id=self.identity.node_id,
                        protocol_version=self.identity.protocol_version,
                        request_id=request.request_id,
                        status=NodeFailureState.SYMBOL_UNAVAILABLE,
                        error_message=f"Symbol '{symbol}' is not available or not visible on MT5 node.",
                    )
                sym_info = SymbolInfoReadOnly(
                    name=symbol,
                    visible=True,
                    bid=Decimal("1.14120"),
                    ask=Decimal("1.14132"),
                    spread=Decimal("0.00012"),
                    digits=5,
                    point=Decimal("0.00001"),
                    trade_mode=0,
                )
                return NodeResponse(
                    node_id=self.identity.node_id,
                    protocol_version=self.identity.protocol_version,
                    request_id=request.request_id,
                    status=NodeFailureState.SUCCESS,
                    payload=sym_info.model_dump(mode="json"),
                )

            case NodeAction.GET_TICK:
                symbol = request.params.get("symbol", "").upper()
                if not symbol or symbol not in self.symbols_available:
                    return NodeResponse(
                        node_id=self.identity.node_id,
                        protocol_version=self.identity.protocol_version,
                        request_id=request.request_id,
                        status=NodeFailureState.SYMBOL_UNAVAILABLE,
                        error_message=f"Symbol '{symbol}' is not available or not visible on MT5 node.",
                    )
                tick = TickReadOnly(
                    symbol=symbol,
                    time=datetime.now(timezone.utc),
                    bid=Decimal("1.14120"),
                    ask=Decimal("1.14132"),
                    last=Decimal("1.14125"),
                    spread=Decimal("0.00012"),
                    volume=Decimal("55"),
                )
                return NodeResponse(
                    node_id=self.identity.node_id,
                    protocol_version=self.identity.protocol_version,
                    request_id=request.request_id,
                    status=NodeFailureState.SUCCESS,
                    payload=tick.model_dump(mode="json"),
                )

            case NodeAction.GET_POSITIONS:
                positions_payload = [p.model_dump(mode="json") for p in self.mock_positions]
                return NodeResponse(
                    node_id=self.identity.node_id,
                    protocol_version=self.identity.protocol_version,
                    request_id=request.request_id,
                    status=NodeFailureState.SUCCESS,
                    payload={"positions": positions_payload},
                )

            case _:
                return NodeResponse(
                    node_id=self.identity.node_id,
                    protocol_version=self.identity.protocol_version,
                    request_id=request.request_id,
                    status=NodeFailureState.PROTOCOL_ERROR,
                    error_message=f"Unrecognized action '{request.action}'.",
                )
