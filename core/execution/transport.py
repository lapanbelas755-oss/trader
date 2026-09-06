"""Secure Transport Abstraction for Remote MT5 Execution Node.
Provides a transport-agnostic interface allowing future HTTPS, WebSocket, SSH Tunnel,
Tailscale private network, or RPC implementations while providing a local mock transport for V1.
"""
from abc import ABC, abstractmethod
import logging
import time
from typing import Any, Callable, Optional

from core.execution.remote_protocol import (
    CURRENT_PROTOCOL_VERSION,
    NodeAction,
    NodeFailureState,
    NodeRequest,
    NodeResponse,
)

logger = logging.getLogger(__name__)


class ISecureTransport(ABC):
    """Abstract transport layer connecting Trader Machine to Remote MT5 Node."""

    @abstractmethod
    def send_request(self, request: NodeRequest, timeout_seconds: float = 5.0) -> NodeResponse:
        """Send a protocol request to the remote execution node and return the response."""
        pass


class LocalMockTransport(ISecureTransport):
    """Hermetic in-memory mock transport simulating network transmission, latency, and failure conditions."""

    def __init__(
        self,
        node_handler: Optional[Callable[[NodeRequest], NodeResponse]] = None,
        simulate_latency_ms: float = 2.0,
        force_timeout: bool = False,
        node_offline: bool = False,
    ) -> None:
        self.node_handler = node_handler
        self.simulate_latency_ms = simulate_latency_ms
        self.force_timeout = force_timeout
        self.node_offline = node_offline

    def send_request(self, request: NodeRequest, timeout_seconds: float = 5.0) -> NodeResponse:
        """Simulate sending request to remote node with configurable network behavior."""
        if self.simulate_latency_ms > 0:
            time.sleep(self.simulate_latency_ms / 1000.0)

        if self.force_timeout:
            return NodeResponse(
                node_id="unknown_node",
                protocol_version=request.protocol_version,
                request_id=request.request_id,
                status=NodeFailureState.TIMEOUT,
                error_message=f"Request timed out after {timeout_seconds}s.",
            )

        if self.node_offline:
            return NodeResponse(
                node_id="unknown_node",
                protocol_version=request.protocol_version,
                request_id=request.request_id,
                status=NodeFailureState.NODE_OFFLINE,
                error_message="Remote execution node is unreachable (NODE_OFFLINE).",
            )

        if not self.node_handler:
            return NodeResponse(
                node_id="mock_unconfigured",
                protocol_version=request.protocol_version,
                request_id=request.request_id,
                status=NodeFailureState.UNKNOWN_ERROR,
                error_message="No node handler registered for transport.",
            )

        try:
            return self.node_handler(request)
        except Exception as e:
            logger.error(f"Error during transport request processing: {e}")
            return NodeResponse(
                node_id="error_node",
                protocol_version=request.protocol_version,
                request_id=request.request_id,
                status=NodeFailureState.UNKNOWN_ERROR,
                error_message=f"Internal transport error: {e}",
            )
