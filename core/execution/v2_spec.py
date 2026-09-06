"""Windows MT5 Worker V2 — Specification Contracts and Cryptographic Protocol Helpers.
Implements request signing (HMAC-SHA256), replay protection (nonces + timestamp window),
idempotency tracking, explicit information classification, and error taxonomy.
Strictly read-only.
"""
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import hmac
import json
import time
from typing import Any, Optional, Union
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.execution.contract import TradingProhibitedError

V2_PROTOCOL_VERSION = "2.0.0"


class InformationClassification(str, Enum):
    """Rigorous classification of market data and worker claims.
    Prevents the worker from ever confusing observed facts with mathematical derivations or unfounded inferences.
    """
    OBSERVED = "OBSERVED"  # Directly provided by MT5 terminal API (e.g. Bid, Ask, Tick Time, Account Balance)
    DERIVED = "DERIVED"    # Computed mathematically from observed data (e.g. Spread = Ask - Bid)
    INFERRED = "INFERRED"  # Probabilistic or subjective inference (PROHIBITED on Worker)
    UNKNOWN = "UNKNOWN"    # Unknowable parameters (e.g. bank order flow, participant identities)


class WorkerV2ErrorCode(str, Enum):
    """Exhaustive error taxonomy for Windows MT5 Worker V2."""
    SUCCESS = "SUCCESS"
    NODE_OFFLINE = "NODE_OFFLINE"
    MT5_OFFLINE = "MT5_OFFLINE"
    AUTH_FAILED = "AUTH_FAILED"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    REPLAY_ATTACK_DETECTED = "REPLAY_ATTACK_DETECTED"
    CLOCK_SKEW_DETECTED = "CLOCK_SKEW_DETECTED"
    SYMBOL_UNAVAILABLE = "SYMBOL_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    READ_ONLY_VIOLATION = "READ_ONLY_VIOLATION"
    TERMINAL_CRASHED = "TERMINAL_CRASHED"
    BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class SignedNodeRequest(BaseModel):
    """Cryptographically signed, replay-protected request message for Worker V2."""
    model_config = ConfigDict(frozen=True)

    request_id: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    idempotency_key: Optional[str] = None
    protocol_version: str = V2_PROTOCOL_VERSION
    signature: str = ""

    @field_validator("timestamp_utc")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    def canonical_bytes(self) -> bytes:
        """Serialize request canonical form for signature hashing."""
        payload = {
            "request_id": self.request_id,
            "action": self.action,
            "params": self.params,
            "nonce": self.nonce,
            "timestamp_iso": self.timestamp_utc.isoformat(),
            "idempotency_key": self.idempotency_key or "",
            "protocol_version": self.protocol_version,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class WorkerV2Response(BaseModel):
    """Standardized response envelope for Windows MT5 Worker V2."""
    model_config = ConfigDict(frozen=True)

    node_id: str
    protocol_version: str = V2_PROTOCOL_VERSION
    request_id: str
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: WorkerV2ErrorCode
    data_classification: InformationClassification = InformationClassification.OBSERVED
    payload: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None

    @field_validator("timestamp_utc")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class HMACRequestSigner:
    """Computes and validates HMAC-SHA256 request signatures using pre-shared symmetric keys."""

    @staticmethod
    def sign_request(request: SignedNodeRequest, secret_key: Union[str, bytes]) -> SignedNodeRequest:
        """Sign request with HMAC-SHA256 and return new instance with signature attached."""
        key_bytes = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
        canonical = request.canonical_bytes()
        sig = hmac.new(key_bytes, canonical, hashlib.sha256).hexdigest()
        data = request.model_dump()
        data["signature"] = sig
        return SignedNodeRequest(**data)

    @staticmethod
    def verify_signature(request: SignedNodeRequest, secret_key: Union[str, bytes]) -> bool:
        """Verify HMAC-SHA256 signature using constant-time comparison."""
        if not request.signature:
            return False
        key_bytes = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
        canonical = request.canonical_bytes()
        expected = hmac.new(key_bytes, canonical, hashlib.sha256).hexdigest()
        return hmac.compare_digest(request.signature, expected)


class ReplayProtectionValidator:
    """Enforces non-repetition and timestamp window validation against replay attacks."""

    def __init__(self, window_seconds: float = 30.0, max_future_skew_seconds: float = 5.0) -> None:
        self.window_seconds = window_seconds
        self.max_future_skew_seconds = max_future_skew_seconds
        # Maps nonce -> expiry epoch seconds
        self._seen_nonces: dict[str, float] = {}

    def _prune(self, current_time: float) -> None:
        expired = [n for n, exp in self._seen_nonces.items() if exp <= current_time]
        for n in expired:
            del self._seen_nonces[n]

    def validate_request(self, request: SignedNodeRequest, current_time: Optional[float] = None) -> tuple[bool, Optional[WorkerV2ErrorCode], str]:
        """Validate timestamp age, future clock skew, and nonce uniqueness."""
        now = current_time if current_time is not None else time.time()
        self._prune(now)

        req_time = request.timestamp_utc.timestamp()

        # Check future skew
        if req_time > now + self.max_future_skew_seconds:
            return False, WorkerV2ErrorCode.CLOCK_SKEW_DETECTED, (
                f"Clock skew detected: request timestamp {request.timestamp_utc.isoformat()} is in the future."
            )

        # Check expiration / age
        if req_time < now - self.window_seconds:
            return False, WorkerV2ErrorCode.TIMEOUT, (
                f"Request expired: timestamp age is {now - req_time:.2f}s, exceeding maximum window of {self.window_seconds}s."
            )

        # Check nonce uniqueness
        if request.nonce in self._seen_nonces:
            return False, WorkerV2ErrorCode.REPLAY_ATTACK_DETECTED, (
                f"Replay attack detected: nonce '{request.nonce}' has already been processed."
            )

        # Record nonce with expiry at (req_time + window)
        self._seen_nonces[request.nonce] = now + self.window_seconds
        return True, None, "OK"


class IdempotencyCache:
    """Maintains deduplicated idempotent response cache for safe retries."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, WorkerV2Response]] = {}

    def _prune(self, now: float) -> None:
        expired = [k for k, (exp, _) in self._cache.items() if exp <= now]
        for k in expired:
            del self._cache[k]

    def get(self, idempotency_key: str, current_time: Optional[float] = None) -> Optional[WorkerV2Response]:
        now = current_time if current_time is not None else time.time()
        self._prune(now)
        entry = self._cache.get(idempotency_key)
        if entry:
            return entry[1]
        return None

    def store(self, idempotency_key: str, response: WorkerV2Response, current_time: Optional[float] = None) -> None:
        now = current_time if current_time is not None else time.time()
        self._prune(now)
        self._cache[idempotency_key] = (now + self.ttl_seconds, response)
