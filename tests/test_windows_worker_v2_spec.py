"""Tests for Windows MT5 Worker V2 Specification, Cryptographic Protocols, and Contracts.
All tests run hermetically without requiring Windows, MT5, or live broker connections.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest

from core.execution.contract import TradingProhibitedError
from core.execution.v2_spec import (
    HMACRequestSigner,
    IdempotencyCache,
    InformationClassification,
    ReplayProtectionValidator,
    SignedNodeRequest,
    V2_PROTOCOL_VERSION,
    WorkerV2ErrorCode,
    WorkerV2Response,
)


SECRET_KEY = "test-pre-shared-key-32-bytes-long!"


# 1. Information classification contract
def test_information_classification_contract():
    assert InformationClassification.OBSERVED.value == "OBSERVED"
    assert InformationClassification.DERIVED.value == "DERIVED"
    assert InformationClassification.INFERRED.value == "INFERRED"
    assert InformationClassification.UNKNOWN.value == "UNKNOWN"

    resp = WorkerV2Response(
        node_id="win-mt5-node-01",
        request_id="req_01",
        status=WorkerV2ErrorCode.SUCCESS,
        data_classification=InformationClassification.OBSERVED,
        payload={"bid": "1.14120", "ask": "1.14132"},
    )
    assert resp.data_classification == InformationClassification.OBSERVED


# 2. HMAC request signing & verification
def test_hmac_request_signing_and_verification():
    req = SignedNodeRequest(
        request_id="req_test_sign_1",
        action="get_tick",
        params={"symbol": "EURUSD"},
    )
    assert req.signature == ""

    # Sign request
    signed_req = HMACRequestSigner.sign_request(req, SECRET_KEY)
    assert signed_req.signature != ""
    assert len(signed_req.signature) == 64  # SHA-256 hex digest

    # Verify signature
    assert HMACRequestSigner.verify_signature(signed_req, SECRET_KEY) is True

    # Tampered key should fail
    assert HMACRequestSigner.verify_signature(signed_req, "wrong-key-value-12345") is False

    # Tampered payload should fail
    tampered_dict = signed_req.model_dump()
    tampered_dict["params"] = {"symbol": "GBPUSD"}
    tampered_req = SignedNodeRequest(**tampered_dict)
    assert HMACRequestSigner.verify_signature(tampered_req, SECRET_KEY) is False


# 3. Replay protection — duplicate nonce
def test_replay_protection_duplicate_nonce():
    validator = ReplayProtectionValidator(window_seconds=30.0)
    now = datetime.now(timezone.utc)

    req1 = SignedNodeRequest(
        request_id="req_1",
        action="get_tick",
        nonce="nonce_unique_123",
        timestamp_utc=now,
    )

    # First attempt: PASS
    ok, err, msg = validator.validate_request(req1, current_time=now.timestamp())
    assert ok is True
    assert err is None

    # Second attempt with same nonce: REPLAY_ATTACK_DETECTED
    ok2, err2, msg2 = validator.validate_request(req1, current_time=now.timestamp())
    assert ok2 is False
    assert err2 == WorkerV2ErrorCode.REPLAY_ATTACK_DETECTED
    assert "Replay attack detected" in msg2


# 4. Replay protection — expired timestamp
def test_replay_protection_expired_timestamp():
    validator = ReplayProtectionValidator(window_seconds=30.0)
    now = datetime.now(timezone.utc)
    expired_time = now - timedelta(seconds=45)

    req = SignedNodeRequest(
        request_id="req_expired",
        action="get_tick",
        nonce="nonce_expired_1",
        timestamp_utc=expired_time,
    )

    ok, err, msg = validator.validate_request(req, current_time=now.timestamp())
    assert ok is False
    assert err == WorkerV2ErrorCode.TIMEOUT
    assert "Request expired" in msg


# 5. Replay protection — future clock skew
def test_replay_protection_future_clock_skew():
    validator = ReplayProtectionValidator(window_seconds=30.0, max_future_skew_seconds=5.0)
    now = datetime.now(timezone.utc)
    future_time = now + timedelta(seconds=15)

    req = SignedNodeRequest(
        request_id="req_future",
        action="get_tick",
        nonce="nonce_future_1",
        timestamp_utc=future_time,
    )

    ok, err, msg = validator.validate_request(req, current_time=now.timestamp())
    assert ok is False
    assert err == WorkerV2ErrorCode.CLOCK_SKEW_DETECTED
    assert "Clock skew detected" in msg


# 6. Idempotency cache
def test_idempotency_cache():
    cache = IdempotencyCache(ttl_seconds=60.0)
    resp = WorkerV2Response(
        node_id="win-node-01",
        request_id="req_idem_1",
        status=WorkerV2ErrorCode.SUCCESS,
        payload={"data": 123},
    )

    cache.store("idem_key_abc", resp, current_time=100.0)
    cached = cache.get("idem_key_abc", current_time=110.0)
    assert cached is not None
    assert cached.request_id == "req_idem_1"

    # Expired entry (ttl = 60s, checking at 170s)
    expired = cache.get("idem_key_abc", current_time=170.0)
    assert expired is None


# 7. Error taxonomy completeness
def test_error_taxonomy_completeness():
    expected_errors = [
        "SUCCESS",
        "NODE_OFFLINE",
        "MT5_OFFLINE",
        "AUTH_FAILED",
        "SIGNATURE_INVALID",
        "REPLAY_ATTACK_DETECTED",
        "CLOCK_SKEW_DETECTED",
        "SYMBOL_UNAVAILABLE",
        "TIMEOUT",
        "PROTOCOL_ERROR",
        "READ_ONLY_VIOLATION",
        "TERMINAL_CRASHED",
        "BROKER_DISCONNECTED",
        "UNKNOWN_ERROR",
    ]
    for err in expected_errors:
        assert err in WorkerV2ErrorCode.__members__


# 8. Protocol version compatibility
def test_protocol_version_compatibility():
    req = SignedNodeRequest(
        request_id="req_v2",
        action="get_health",
        protocol_version=V2_PROTOCOL_VERSION,
    )
    assert req.protocol_version == "2.0.0"


# 9. Specification documentation existence and completeness
def test_spec_document_sections():
    spec_path = Path(__file__).parent.parent / "docs" / "windows_mt5_worker_v2_spec.md"
    assert spec_path.exists(), "Specification document docs/windows_mt5_worker_v2_spec.md must exist."

    content = spec_path.read_text(encoding="utf-8")
    assert "OBSERVED" in content
    assert "DERIVED" in content
    assert "INFERRED" in content
    assert "UNKNOWN" in content
    assert "Tailscale" in content or "WireGuard" in content
    assert "HMAC-SHA256" in content
    assert "Idempotency" in content
    assert "Replay Protection" in content


# 10. Critical safety audit: zero order execution in execution package
def test_critical_safety_audit():
    execution_dir = Path(__file__).parent.parent / "core" / "execution"
    for py_file in execution_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "mt5.order_send(" not in text
        assert "mt5.OrderSend(" not in text
        assert "mt5.order_check(" not in text
        assert "mt5.position_close(" not in text
