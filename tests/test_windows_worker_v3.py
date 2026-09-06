"""Comprehensive Unit and Integration Tests for Windows MT5 Worker V3.
All tests run hermetically on macOS / CI without requiring Windows or live MT5.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
import time
import urllib.request
import pytest

from core.execution.contract import AccountInfoReadOnly, TickReadOnly
from core.execution.v2_spec import (
    HMACRequestSigner,
    InformationClassification,
    SignedNodeRequest,
    WorkerV2ErrorCode,
)
from core.worker.adapter import (
    IMT5Adapter,
    MockMT5Adapter,
    MT5ConnectionState,
    RealMT5Adapter,
)
from core.worker.config import (
    AdapterMode,
    ConfigurationError,
    WorkerConfig,
    WorkerEnvironment,
)
from core.worker.diagnostics import run_security_audit, run_startup_diagnostics
from core.worker.transport import HTTPWorkerServer, LoopbackWorkerTransport
from core.worker.worker import MT5WorkerV3, WorkerState

TEST_SECRET = "super_secure_pre_shared_key_32_bytes!"


def create_test_worker(
    initial_state: MT5ConnectionState = MT5ConnectionState.MT5_CONNECTED,
    allowed_symbols: list[str] = None,
    secret: str = TEST_SECRET,
) -> MT5WorkerV3:
    symbols = allowed_symbols or ["EURUSD"]
    config = WorkerConfig(
        node_id="test-win-worker-01",
        node_name="Test Worker",
        environment=WorkerEnvironment.DEMO,
        adapter_mode=AdapterMode.MOCK,
        hmac_secret=secret,
        allowed_symbols=symbols,
        bind_host="127.0.0.1",
        bind_port=8099,
        replay_window_seconds=30.0,
        max_future_skew_seconds=5.0,
        idempotency_ttl_seconds=60.0,
    )
    adapter = MockMT5Adapter(
        initial_state=initial_state,
        symbols_available=symbols,
    )
    worker = MT5WorkerV3(config=config, adapter=adapter)
    worker.start()
    return worker


# 1. Configuration Validation Tests
def test_configuration_validation_success():
    cfg = WorkerConfig(
        hmac_secret="valid_secret_longer_than_16_chars!",
        bind_port=9000,
        allowed_symbols=["EURUSD", "GBPUSD"],
    )
    assert cfg.bind_port == 9000
    assert "EURUSD" in cfg.allowed_symbols
    assert "GBPUSD" in cfg.allowed_symbols
    # Secret must be redacted in repr
    assert "valid_secret" not in repr(cfg)
    assert "***REDACTED***" in repr(cfg)


def test_configuration_validation_missing_or_short_secret():
    with pytest.raises(ValueError, match="too short"):
        WorkerConfig(hmac_secret="short")

    with pytest.raises(ValueError, match="empty"):
        WorkerConfig(hmac_secret="   ")


def test_configuration_validation_invalid_port():
    with pytest.raises(ValueError, match="Invalid port"):
        WorkerConfig(hmac_secret="valid_secret_key_16_chars", bind_port=70000)


def test_configuration_from_env_success():
    env = {
        "WORKER_HMAC_SECRET": "env_test_secret_32_characters_long",
        "WORKER_BIND_PORT": "8888",
        "WORKER_ALLOWED_SYMBOLS": "EURUSD,USDJPY",
        "WORKER_ADAPTER_MODE": "MOCK",
    }
    cfg = WorkerConfig.from_env(env)
    assert cfg.bind_port == 8888
    assert cfg.allowed_symbols == ["EURUSD", "USDJPY"]
    assert cfg.adapter_mode == AdapterMode.MOCK


def test_configuration_from_env_rejects_placeholder_in_real_mode():
    env = {
        "WORKER_HMAC_SECRET": "replace_with_secure_key",
        "WORKER_ADAPTER_MODE": "REAL",
    }
    with pytest.raises(ConfigurationError, match="Cannot use placeholder"):
        WorkerConfig.from_env(env)


# 2. Worker Lifecycle & State
def test_worker_lifecycle():
    worker = create_test_worker()
    assert worker.state == WorkerState.RUNNING
    assert worker.get_uptime_seconds() >= 0.0

    worker.stop()
    assert worker.state == WorkerState.STOPPED


# 3. HMAC Authentication & Replay Protection
def test_valid_signed_request():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_health_01",
        action="get_health",
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.SUCCESS
    assert resp.request_id == "req_health_01"
    assert resp.payload["status"] == "HEALTHY"
    assert resp.payload["mt5_connected"] is True


def test_invalid_signature_rejected():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_invalid_sig",
        action="get_health",
    )
    signed_req = HMACRequestSigner.sign_request(req, "wrong_secret_key_that_does_not_match")
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.SIGNATURE_INVALID
    assert "Invalid HMAC" in resp.error_message


def test_missing_signature_rejected():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_no_sig",
        action="get_health",
        signature="",
    )
    resp = worker.process_request(req)
    assert resp.status == WorkerV2ErrorCode.SIGNATURE_INVALID


def test_replay_attack_duplicate_nonce_rejected():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_nonce_1",
        action="get_health",
        nonce="duplicate_nonce_12345",
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)

    # First attempt: PASS
    resp1 = worker.process_request(signed_req)
    assert resp1.status == WorkerV2ErrorCode.SUCCESS

    # Second attempt: REPLAY_ATTACK_DETECTED
    resp2 = worker.process_request(signed_req)
    assert resp2.status == WorkerV2ErrorCode.REPLAY_ATTACK_DETECTED


def test_expired_timestamp_rejected():
    worker = create_test_worker()
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(seconds=45)

    req = SignedNodeRequest(
        request_id="req_expired",
        action="get_health",
        timestamp_utc=old_time,
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req, current_time=now.timestamp())

    assert resp.status == WorkerV2ErrorCode.TIMEOUT


def test_future_clock_skew_rejected():
    worker = create_test_worker()
    now = datetime.now(timezone.utc)
    future_time = now + timedelta(seconds=15)

    req = SignedNodeRequest(
        request_id="req_skew",
        action="get_health",
        timestamp_utc=future_time,
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req, current_time=now.timestamp())

    assert resp.status == WorkerV2ErrorCode.CLOCK_SKEW_DETECTED


# 4. Idempotency Caching
def test_idempotent_request_caching():
    worker = create_test_worker()
    req1 = SignedNodeRequest(
        request_id="req_idem_1",
        action="get_health",
        idempotency_key="idem_uuid_999",
    )
    signed_req1 = HMACRequestSigner.sign_request(req1, TEST_SECRET)
    resp1 = worker.process_request(signed_req1)
    assert resp1.status == WorkerV2ErrorCode.SUCCESS

    # Send identical request with same idempotency key
    resp2 = worker.process_request(signed_req1)
    assert resp2.status == WorkerV2ErrorCode.SUCCESS
    assert resp2.request_id == resp1.request_id


# 5. Strict Read-Only Action Allowlist & Prohibited Trade Actions
@pytest.mark.parametrize("bad_action", [
    "send_order",
    "order_send",
    "OrderSend",
    "buy",
    "sell",
    "close_position",
    "position_close",
    "modify_order",
])
def test_prohibited_trade_actions_rejected(bad_action: str):
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id=f"req_bad_{bad_action}",
        action=bad_action,
        params={"symbol": "EURUSD", "volume": 0.1},
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.READ_ONLY_VIOLATION
    assert "prohibited trade operation" in resp.error_message


def test_unknown_action_rejected():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_unknown_action",
        action="do_random_thing",
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.PROTOCOL_ERROR
    assert "Unknown or unauthorized action" in resp.error_message


# 6. Read-Only Telemetry Query Handlers
def test_get_terminal_info():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_term_01",
        action="get_terminal_info",
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.SUCCESS
    assert resp.data_classification == InformationClassification.OBSERVED
    assert resp.payload["name"] == "MetaTrader 5 Mock"
    assert resp.payload["build"] == 4200
    assert resp.payload["trade_allowed"] is False


def test_get_account_info_credentials_redacted():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_acc_01",
        action="get_account_info",
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.SUCCESS
    assert resp.data_classification == InformationClassification.OBSERVED
    payload = resp.payload
    assert payload["login_masked"] == "882***"
    assert "password" not in payload
    assert payload["trade_mode"] == "DEMO"
    assert Decimal(str(payload["balance"])) == Decimal("10000.00")


def test_get_symbol_info_derived_spread():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_sym_01",
        action="get_symbol_info",
        params={"symbol": "EURUSD"},
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.SUCCESS
    assert resp.data_classification == InformationClassification.DERIVED
    payload = resp.payload
    assert payload["name"] == "EURUSD"
    assert Decimal(str(payload["bid"])) == Decimal("1.10000")
    assert Decimal(str(payload["ask"])) == Decimal("1.10012")
    assert Decimal(str(payload["spread"])) == Decimal("0.00012")
    assert payload["_classification"]["spread"] == "DERIVED"


def test_get_symbol_info_unsupported_symbol():
    worker = create_test_worker(allowed_symbols=["EURUSD"])
    req = SignedNodeRequest(
        request_id="req_sym_unsupported",
        action="get_symbol_info",
        params={"symbol": "BTCUSD"},
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.SYMBOL_UNAVAILABLE
    assert "not in allowed symbols" in resp.error_message


def test_get_tick_data_classification():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_tick_01",
        action="get_tick",
        params={"symbol": "EURUSD"},
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.SUCCESS
    payload = resp.payload
    assert payload["symbol"] == "EURUSD"
    assert Decimal(str(payload["bid"])) == Decimal("1.10000")
    assert Decimal(str(payload["ask"])) == Decimal("1.10012")
    assert payload["_classification"]["volume_note"] == "Quote/tick count only. Not real traded volume."


def test_get_positions():
    worker = create_test_worker()
    req = SignedNodeRequest(
        request_id="req_pos_01",
        action="get_positions",
    )
    signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)
    resp = worker.process_request(signed_req)

    assert resp.status == WorkerV2ErrorCode.SUCCESS
    assert resp.payload["count"] == 1
    pos = resp.payload["positions"][0]
    assert pos["symbol"] == "EURUSD"
    assert pos["type"] == "BUY"


# 7. MT5 Disconnected State Handling
def test_mt5_disconnected_state():
    worker = create_test_worker()
    worker.adapter.shutdown()

    # Health check returns DEGRADED
    req_health = HMACRequestSigner.sign_request(
        SignedNodeRequest(request_id="req_h_disc", action="get_health"),
        TEST_SECRET,
    )
    resp_health = worker.process_request(req_health)
    assert resp_health.status == WorkerV2ErrorCode.SUCCESS
    assert resp_health.payload["status"] == "DEGRADED"
    assert resp_health.payload["mt5_connected"] is False

    # Tick query returns MT5_OFFLINE
    req_tick = HMACRequestSigner.sign_request(
        SignedNodeRequest(request_id="req_t_disc", action="get_tick", params={"symbol": "EURUSD"}),
        TEST_SECRET,
    )
    resp_tick = worker.process_request(req_tick)
    assert resp_tick.status == WorkerV2ErrorCode.MT5_OFFLINE


# 8. Real Adapter Non-Windows Safety Test
def test_real_mt5_adapter_on_mac_reports_not_installed():
    adapter = RealMT5Adapter()
    ok = adapter.initialize()
    # On macOS Apple Silicon, this must be False and state MT5_NOT_INSTALLED
    assert ok is False
    assert adapter.get_connection_state() == MT5ConnectionState.MT5_NOT_INSTALLED
    assert adapter.is_connected() is False
    assert adapter.get_terminal_info() is None


# 9. Transport Abstraction Tests (Loopback & HTTP)
def test_loopback_transport():
    worker = create_test_worker()
    transport = LoopbackWorkerTransport(worker)
    assert transport.is_running() is False

    transport.start()
    assert transport.is_running() is True

    req = HMACRequestSigner.sign_request(
        SignedNodeRequest(request_id="req_loop_1", action="get_health"),
        TEST_SECRET,
    )
    resp = transport.send_request(req)
    assert resp.status == WorkerV2ErrorCode.SUCCESS

    transport.stop()
    assert transport.is_running() is False


def test_http_worker_server_live_roundtrip():
    # Use a high random port to avoid conflicts
    worker = create_test_worker()
    server = HTTPWorkerServer(worker)
    server.start()
    time.sleep(0.1)

    port = worker.config.bind_port
    host = worker.config.bind_host

    try:
        # Test 1: GET /api/v3/health (Unauthenticated ping)
        url_health = f"http://{host}:{port}/api/v3/health"
        with urllib.request.urlopen(url_health, timeout=2.0) as r:
            assert r.status == 200
            data = json.loads(r.read().decode("utf-8"))
            assert data["status"] == "ONLINE"
            assert data["node_id"] == "test-win-worker-01"

        # Test 2: POST /api/v3/request (Authenticated query)
        url_req = f"http://{host}:{port}/api/v3/request"
        req = SignedNodeRequest(request_id="req_http_01", action="get_tick", params={"symbol": "EURUSD"})
        signed_req = HMACRequestSigner.sign_request(req, TEST_SECRET)

        req_bytes = signed_req.model_dump_json().encode("utf-8")
        http_req = urllib.request.Request(
            url_req,
            data=req_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(http_req, timeout=2.0) as r:
            assert r.status == 200
            resp_data = json.loads(r.read().decode("utf-8"))
            assert resp_data["status"] == "SUCCESS"
            assert resp_data["payload"]["symbol"] == "EURUSD"
    finally:
        server.stop()


# 10. Startup Diagnostics Test
def test_startup_diagnostics():
    worker = create_test_worker()
    diag = run_startup_diagnostics(worker.config, worker.adapter)
    assert diag["node_id"] == "test-win-worker-01"
    assert diag["adapter_mode"] == "MOCK"
    assert diag["hmac_configured"] is True
    assert "EURUSD" in diag["allowed_symbols"]


# 11. CRITICAL STATIC SECURITY AUDIT
def test_critical_security_audit_zero_trading_paths():
    """Verify that there are ZERO executable trading calls across all worker and execution production code."""
    audit_res = run_security_audit()
    assert audit_res["status"] == "PASS", f"Security audit failed: {audit_res['violations']}"
    assert audit_res["violations_count"] == 0
    assert audit_res["read_only_guaranteed"] is True
    assert audit_res["files_scanned_count"] >= 10
