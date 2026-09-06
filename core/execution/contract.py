"""Contracts and Data Models for Read-Only MT5 Connectivity Probe V1.
Strictly read-only interface. Prohibits any trading or broker execution operations.
"""
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConnectivityStatus(str, Enum):
    """High-level connectivity states for MT5 terminal probe."""
    CONNECTED_READ_ONLY = "CONNECTED_READ_ONLY"
    MT5_NOT_RUNNING = "MT5_NOT_RUNNING"
    MT5_NOT_INSTALLED = "MT5_NOT_INSTALLED"
    PYTHON_PACKAGE_UNAVAILABLE = "PYTHON_PACKAGE_UNAVAILABLE"
    PLATFORM_INCOMPATIBLE = "PLATFORM_INCOMPATIBLE"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    SYMBOL_UNAVAILABLE = "SYMBOL_UNAVAILABLE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class TradingProhibitedError(RuntimeError):
    """Raised if any trading or order execution function is attempted."""
    pass


class PlatformInfo(BaseModel):
    """Runtime platform and architecture diagnostics."""
    model_config = ConfigDict(frozen=True)

    system: str  # e.g., "Darwin"
    os_name: str  # e.g., "macOS"
    os_version: str  # e.g., "24.6.0"
    architecture: str  # e.g., "arm64"
    python_version: str  # e.g., "3.12.8"
    is_apple_silicon: bool
    is_windows: bool
    is_natively_supported: bool  # MetaTrader5 package is Windows-native only
    notes: str


class TerminalInfoReadOnly(BaseModel):
    """Terminal state and metadata without trade capabilities."""
    model_config = ConfigDict(frozen=True)

    connected: bool
    trade_allowed: bool
    name: str
    path: Optional[str] = None
    data_path: Optional[str] = None
    company: str
    version: str
    build: int


class AccountInfoReadOnly(BaseModel):
    """Read-only account financial status with strict credential redaction."""
    model_config = ConfigDict(frozen=True)

    login_masked: str  # Redacted: e.g., "123***"
    server: str
    currency: str
    balance: Decimal
    equity: Decimal
    margin: Decimal
    margin_free: Decimal
    margin_level: Optional[Decimal] = None
    leverage: int = 1
    trade_allowed: bool = False
    trade_mode: str = "DEMO"

    @classmethod
    def mask_login(cls, login_raw: Any) -> str:
        """Safely redact account login identifiers."""
        s = str(login_raw).strip()
        if len(s) <= 3:
            return "***"
        return s[:3] + "*" * (len(s) - 3)


class SymbolInfoReadOnly(BaseModel):
    """Read-only symbol quote state and visibility."""
    model_config = ConfigDict(frozen=True)

    name: str
    visible: bool
    bid: Decimal
    ask: Decimal
    spread: Decimal  # Points or price difference
    digits: int
    point: Decimal
    trade_mode: int = 0  # Read-only enum integer


class TickReadOnly(BaseModel):
    """Read-only price snapshot for an instrument."""
    model_config = ConfigDict(frozen=True)

    symbol: str
    time: datetime  # Guaranteed UTC
    bid: Decimal
    ask: Decimal
    last: Optional[Decimal] = None
    spread: Decimal
    volume: Decimal = Field(default=Decimal("0"), description="Quote/tick activity only. Not real traded volume.")

    @field_validator("time")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class ProbeReport(BaseModel):
    """Consolidated MT5 probe diagnostic and audit record."""
    model_config = ConfigDict(frozen=True)

    status: ConnectivityStatus
    platform: PlatformInfo
    mt5_package_available: bool
    mt5_installed: bool
    mt5_running: bool
    terminal_path: Optional[str] = None
    terminal_info: Optional[TerminalInfoReadOnly] = None
    account_info: Optional[AccountInfoReadOnly] = None
    symbol_info: Optional[SymbolInfoReadOnly] = None
    tick_info: Optional[TickReadOnly] = None
    connection_latency_ms: Optional[float] = None
    tick_latency_ms: Optional[float] = None
    errors: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
