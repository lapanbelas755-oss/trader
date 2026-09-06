"""Remote MT5 Execution Node Protocol V1.
Defines message schemas, failure states, node identity, and read-only payload structures.
"""
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import time
from typing import Any, Optional, Union
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.execution.contract import TradingProhibitedError

CURRENT_PROTOCOL_VERSION = "1.0.0"


class NodeFailureState(str, Enum):
    """Explicit remote execution node failure states."""
    SUCCESS = "SUCCESS"
    NODE_OFFLINE = "NODE_OFFLINE"
    MT5_OFFLINE = "MT5_OFFLINE"
    AUTH_FAILED = "AUTH_FAILED"
    SYMBOL_UNAVAILABLE = "SYMBOL_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class NodeAction(str, Enum):
    """Allowed actions on remote MT5 execution node."""
    # Read-Only Operations
    GET_HEALTH = "get_health"
    GET_TERMINAL_INFO = "get_terminal_info"
    GET_ACCOUNT_INFO = "get_account_info"
    GET_SYMBOL_INFO = "get_symbol_info"
    GET_TICK = "get_tick"
    GET_POSITIONS = "get_positions"

    # Blocked Future Trade Operations (Permanently Blocked in V1)
    SEND_ORDER = "send_order"
    MODIFY_ORDER = "modify_order"
    CLOSE_POSITION = "close_position"


BLOCKED_TRADE_ACTIONS = {
    NodeAction.SEND_ORDER,
    NodeAction.MODIFY_ORDER,
    NodeAction.CLOSE_POSITION,
}


class NodeIdentity(BaseModel):
    """Remote MT5 execution node identification."""
    model_config = ConfigDict(frozen=True)

    node_id: str
    node_name: str
    node_version: str = "1.0.0"
    protocol_version: str = CURRENT_PROTOCOL_VERSION
    environment: str = "DEMO"
    host_os: str = "Windows"


class PositionReadOnly(BaseModel):
    """Read-only representation of an open broker position."""
    model_config = ConfigDict(frozen=True)

    ticket: int
    symbol: str
    type: str  # "BUY" or "SELL"
    volume: Decimal
    price_open: Decimal
    sl: Optional[Decimal] = None
    tp: Optional[Decimal] = None
    price_current: Decimal
    profit: Decimal
    time: datetime

    @field_validator("time")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class HealthInfo(BaseModel):
    """Health check diagnostic payload."""
    model_config = ConfigDict(frozen=True)

    status: str  # "HEALTHY", "DEGRADED", "UNHEALTHY"
    mt5_connected: bool
    terminal_running: bool
    uptime_seconds: float
    latency_internal_ms: float
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def generate_request_id(action: Union[NodeAction, str], seq: Optional[int] = None) -> str:
    """Deterministic format request ID: req_{action}_{timestamp_ms}_{uuid/seq}."""
    action_str = action.value if isinstance(action, NodeAction) else str(action)
    ts_ms = int(time.time() * 1000)
    suffix = str(seq) if seq is not None else uuid.uuid4().hex[:8]
    return f"req_{action_str}_{ts_ms}_{suffix}"


class NodeRequest(BaseModel):
    """Transport-agnostic request message sent to remote execution node."""
    model_config = ConfigDict(frozen=True)

    request_id: str
    action: NodeAction
    params: dict[str, Any] = Field(default_factory=dict)
    protocol_version: str = CURRENT_PROTOCOL_VERSION
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    auth_token: Optional[str] = None  # Secure bearer token/HMAC signature; never plaintext credentials

    @field_validator("timestamp_utc")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class NodeResponse(BaseModel):
    """Standardized response from remote execution node."""
    model_config = ConfigDict(frozen=True)

    node_id: str
    protocol_version: str
    request_id: str
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: NodeFailureState
    payload: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None

    @field_validator("timestamp_utc")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
