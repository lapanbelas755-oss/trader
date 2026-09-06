"""Tests for Remote MT5 Execution Node V1 Architecture & Protocol.
All tests run hermetically in-memory with zero live broker connectivity.
"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import pytest

from core.execution.contract import (
    AccountInfoReadOnly,
    TradingProhibitedError,
)
from core.execution.remote_protocol import (
    CURRENT_PROTOCOL_VERSION,
    HealthInfo,
    NodeAction,
    NodeFailureState,
    NodeIdentity,
    NodeRequest,
    NodeResponse,
    PositionReadOnly,
    generate_request_id,
)
from core.execution.transport import LocalMockTransport
from core.execution.remote_node import MockExecutionNode
from core.execution.client import RemoteExecutionClient, RemoteExecutionError
from core.execution.service import ExecutionService


@pytest.fixture
def mock_node():
    return MockExecutionNode(
        node_id="win-test-node-01",
        node_name="Windows Test MT5 Node",
        authorized_tokens={"auth-token-123"},
        symbols_available=["EURUSD", "GBPUSD"],
    )


@pytest.fixture
def mock_client(mock_node):
    transport = LocalMockTransport(node_handler=mock_node.handle_request)
    return RemoteExecutionClient(transport=transport, auth_token="auth-token-123")


# 1. Protocol request
def test_protocol_request():
    req = NodeRequest(
        request_id="req_test_01",
        action=NodeAction.GET_HEALTH,
        params={"detail": True},
        protocol_version=CURRENT_PROTOCOL_VERSION,
        auth_token="token-xyz",
    )
    assert req.request_id == "req_test_01"
    assert req.action == NodeAction.GET_HEALTH
    assert req.params == {"detail": True}
    assert req.timestamp_utc.tzinfo == timezone.utc


# 2. Protocol response
def test_protocol_response():
    resp = NodeResponse(
        node_id="win-node-01",
        protocol_version=CURRENT_PROTOCOL_VERSION,
        request_id="req_test_01",
        status=NodeFailureState.SUCCESS,
        payload={"result": "ok"},
    )
    assert resp.node_id == "win-node-01"
    assert resp.status == NodeFailureState.SUCCESS
    assert resp.payload == {"result": "ok"}
    assert resp.timestamp_utc.tzinfo == timezone.utc


# 3. Request ID
def test_request_id():
    req_id1 = generate_request_id(NodeAction.GET_TICK, seq=1)
    req_id2 = generate_request_id(NodeAction.GET_TICK, seq=2)
    assert req_id1.startswith("req_get_tick_")
    assert req_id1.endswith("_1")
    assert req_id2.endswith("_2")
    assert req_id1 != req_id2


# 4. Node identity
def test_node_identity(mock_node):
    identity = mock_node.get_identity()
    assert identity.node_id == "win-test-node-01"
    assert identity.node_name == "Windows Test MT5 Node"
    assert identity.protocol_version == CURRENT_PROTOCOL_VERSION
    assert identity.host_os == "Windows Server 2022"


# 5. Health check
def test_health_check(mock_client):
    health = mock_client.get_health()
    assert health.status == "HEALTHY"
    assert health.mt5_connected is True
    assert health.terminal_running is True
    assert health.uptime_seconds >= 0


# 6. Terminal info
def test_terminal_info(mock_client):
    term = mock_client.get_terminal_info()
    assert term.connected is True
    assert term.trade_allowed is False  # Read-only probe
    assert "MetaTrader 5" in term.name
    assert term.build > 0


# 7. Account info
def test_account_info(mock_client):
    acc = mock_client.get_account_info()
    assert acc.balance == Decimal("25000.00")
    assert acc.equity == Decimal("25020.00")
    assert acc.currency == "USD"
    assert acc.trade_allowed is False
    assert acc.trade_mode == "DEMO"
    assert "992" in acc.login_masked
    assert "****" in acc.login_masked


# 8. Symbol info
def test_symbol_info(mock_client):
    sym = mock_client.get_symbol_info("EURUSD")
    assert sym.name == "EURUSD"
    assert sym.visible is True
    assert sym.bid > Decimal("0")
    assert sym.ask > Decimal("0")
    assert sym.spread == sym.ask - sym.bid


# 9. Tick retrieval
def test_tick_retrieval(mock_client):
    tick = mock_client.get_tick("EURUSD")
    assert tick.symbol == "EURUSD"
    assert tick.bid > Decimal("0")
    assert tick.ask >= tick.bid
    assert tick.spread == tick.ask - tick.bid
    assert tick.time.tzinfo == timezone.utc


# 10. Position retrieval
def test_position_retrieval(mock_client):
    positions = mock_client.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.ticket == 10928371
    assert pos.symbol == "EURUSD"
    assert pos.type == "BUY"
    assert pos.volume == Decimal("0.10")
    assert pos.profit == Decimal("20.00")
    assert pos.time.tzinfo == timezone.utc


# 11. Timeout
def test_timeout():
    transport = LocalMockTransport(force_timeout=True)
    client = RemoteExecutionClient(transport=transport)
    with pytest.raises(RemoteExecutionError) as exc:
        client.get_health()
    assert exc.value.status == NodeFailureState.TIMEOUT
    assert "timed out" in str(exc.value)


# 12. Node offline
def test_node_offline():
    transport = LocalMockTransport(node_offline=True)
    client = RemoteExecutionClient(transport=transport)
    with pytest.raises(RemoteExecutionError) as exc:
        client.get_health()
    assert exc.value.status == NodeFailureState.NODE_OFFLINE
    assert "NODE_OFFLINE" in str(exc.value)


# 13. MT5 offline
def test_mt5_offline():
    node = MockExecutionNode(mt5_connected=False)
    transport = LocalMockTransport(node_handler=node.handle_request)
    client = RemoteExecutionClient(transport=transport)
    with pytest.raises(RemoteExecutionError) as exc:
        client.get_terminal_info()
    assert exc.value.status == NodeFailureState.MT5_OFFLINE
    assert "MT5_OFFLINE" in str(exc.value)


# 14. Authentication failure
def test_authentication_failure():
    node = MockExecutionNode(authorized_tokens={"valid-secret-token"})
    transport = LocalMockTransport(node_handler=node.handle_request)
    # Provide wrong token
    client = RemoteExecutionClient(transport=transport, auth_token="wrong-token")
    with pytest.raises(RemoteExecutionError) as exc:
        client.get_account_info()
    assert exc.value.status == NodeFailureState.AUTH_FAILED
    assert "AUTH_FAILED" in str(exc.value)


# 15. Protocol failure
def test_protocol_failure(mock_node):
    # Send request with symbol unavailable
    req = NodeRequest(
        request_id="req_unavail",
        action=NodeAction.GET_SYMBOL_INFO,
        params={"symbol": "NONEXISTENT"},
        auth_token="auth-token-123",
    )
    resp = mock_node.handle_request(req)
    assert resp.status == NodeFailureState.SYMBOL_UNAVAILABLE
    assert "not available" in resp.error_message


# 16. Credential redaction
def test_credential_redaction(mock_client):
    acc = mock_client.get_account_info()
    assert acc.login_masked == "992****"
    # Ensure no raw passwords or secret keys exist in the model
    fields = AccountInfoReadOnly.model_fields.keys()
    assert "password" not in fields
    assert "api_secret" not in fields


# 17. Read-only enforcement
def test_read_only_enforcement(mock_node):
    # Prohibit blocked trade actions directly at node level
    req = NodeRequest(
        request_id="req_trade",
        action=NodeAction.SEND_ORDER,
        params={"symbol": "EURUSD", "volume": 0.1},
        auth_token="auth-token-123",
    )
    with pytest.raises(TradingProhibitedError, match="permanently prohibited"):
        mock_node.handle_request(req)


# 18. send_order blocked
def test_send_order_blocked(mock_client):
    with pytest.raises(TradingProhibitedError, match="send_order is permanently disabled"):
        mock_client.send_order(symbol="EURUSD", volume=0.1)


# 19. modify_order blocked
def test_modify_order_blocked(mock_client):
    with pytest.raises(TradingProhibitedError, match="modify_order is permanently disabled"):
        mock_client.modify_order(ticket=123, sl=1.1400)


# 20. close_position blocked
def test_close_position_blocked(mock_client):
    with pytest.raises(TradingProhibitedError, match="close_position is permanently disabled"):
        mock_client.close_position(ticket=123)


# 21. Mock node
def test_mock_node(mock_node):
    assert mock_node.identity.node_id == "win-test-node-01"
    assert mock_node.mt5_connected is True
    assert mock_node.symbols_available == ["EURUSD", "GBPUSD"]


# 22. Deterministic request/response
def test_deterministic_request_response(mock_client):
    req_id_1 = generate_request_id(NodeAction.GET_HEALTH, seq=99)
    req_id_2 = generate_request_id(NodeAction.GET_HEALTH, seq=99)
    # Both have same deterministic structure: req_{action}_{ms}_{seq}
    assert req_id_1.startswith("req_get_health_")
    assert req_id_1.endswith("_99")
    assert req_id_2.endswith("_99")


# 23. Timestamp UTC
def test_timestamp_utc(mock_client):
    health = mock_client.get_health()
    assert health.timestamp_utc.tzinfo == timezone.utc

    tick = mock_client.get_tick("EURUSD")
    assert tick.time.tzinfo == timezone.utc

    positions = mock_client.get_positions()
    for p in positions:
        assert p.time.tzinfo == timezone.utc


# 24. Protocol version compatibility
def test_protocol_version_compatibility(mock_node):
    # Incompatible major version "2.0.0" vs node "1.0.0"
    req = NodeRequest(
        request_id="req_compat",
        action=NodeAction.GET_HEALTH,
        protocol_version="2.0.0",
        auth_token="auth-token-123",
    )
    resp = mock_node.handle_request(req)
    assert resp.status == NodeFailureState.PROTOCOL_ERROR
    assert "version mismatch" in resp.error_message


# 25. Critical security audit
def test_critical_security_audit():
    execution_dir = Path(__file__).parent.parent / "core" / "execution"
    for py_file in execution_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "mt5.order_send(" not in text
        assert "mt5.OrderSend(" not in text
        assert "mt5.order_check(" not in text
        assert "mt5.position_close(" not in text
