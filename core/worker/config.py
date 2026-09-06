"""Windows MT5 Worker V3 — Configuration System.
Provides strongly typed, validated configuration loaded from environment variables.
Guarantees secret redaction in representations and logs.
"""
from enum import Enum
import os
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfigurationError(ValueError):
    """Raised when worker configuration is invalid or missing required secrets."""
    pass


class AdapterMode(str, Enum):
    """Worker MT5 adapter execution mode."""
    MOCK = "MOCK"
    REAL = "REAL"


class WorkerEnvironment(str, Enum):
    """Execution environment mode."""
    DEMO = "DEMO"
    RESEARCH = "RESEARCH"
    PRODUCTION_READONLY = "PRODUCTION_READONLY"


class WorkerConfig(BaseModel):
    """Immutable, validated configuration for Windows MT5 Worker V3."""
    model_config = ConfigDict(frozen=True)

    node_id: str = Field(default="win-mt5-worker-01")
    node_name: str = Field(default="Windows MT5 Worker V3")
    environment: WorkerEnvironment = Field(default=WorkerEnvironment.DEMO)
    adapter_mode: AdapterMode = Field(default=AdapterMode.MOCK)
    hmac_secret: str = Field(..., description="Pre-shared symmetric key for HMAC-SHA256 authentication.")
    bind_host: str = Field(default="127.0.0.1")
    bind_port: int = Field(default=8080)
    allowed_symbols: list[str] = Field(default_factory=lambda: ["EURUSD"])
    mt5_path: Optional[str] = None
    mt5_server: Optional[str] = None
    mt5_login: Optional[int] = None
    mt5_timeout_ms: int = Field(default=5000)
    replay_window_seconds: float = Field(default=30.0)
    max_future_skew_seconds: float = Field(default=5.0)
    idempotency_ttl_seconds: float = Field(default=60.0)
    log_level: str = Field(default="INFO")

    @field_validator("hmac_secret")
    @classmethod
    def validate_hmac_secret(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ConfigurationError("HMAC secret must not be empty.")
        if len(s) < 16:
            raise ConfigurationError(f"HMAC secret length ({len(s)}) is too short. Minimum 16 characters required.")
        return s

    @field_validator("bind_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ConfigurationError(f"Invalid port: {v}. Must be between 1 and 65535.")
        return v

    @field_validator("allowed_symbols")
    @classmethod
    def validate_symbols(cls, v: list[str]) -> list[str]:
        if not v:
            raise ConfigurationError("At least one symbol must be allowed.")
        return [sym.strip().upper() for sym in v if sym.strip()]

    def __repr__(self) -> str:
        """Never expose HMAC secret or credentials in repr."""
        d = self.model_dump()
        d["hmac_secret"] = "***REDACTED***"
        if d.get("mt5_login"):
            s_login = str(d["mt5_login"])
            d["mt5_login"] = s_login[:2] + "***" if len(s_login) > 2 else "***"
        return f"WorkerConfig({d})"

    def __str__(self) -> str:
        return self.__repr__()

    def safe_dict(self) -> dict[str, Any]:
        """Return dictionary safe for logging/telemetry with credentials redacted."""
        d = self.model_dump()
        d["hmac_secret"] = "***REDACTED***"
        if d.get("mt5_login"):
            s_login = str(d["mt5_login"])
            d["mt5_login"] = s_login[:2] + "***" if len(s_login) > 2 else "***"
        return d

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> "WorkerConfig":
        """Load and validate worker configuration from environment variables."""
        e = env if env is not None else os.environ

        raw_secret = e.get("WORKER_HMAC_SECRET", "").strip()
        if not raw_secret:
            raise ConfigurationError(
                "Environment variable 'WORKER_HMAC_SECRET' is required but not set."
            )

        adapter_mode_str = e.get("WORKER_ADAPTER_MODE", "MOCK").upper().strip()
        if adapter_mode_str not in ("MOCK", "REAL"):
            raise ConfigurationError(f"Invalid WORKER_ADAPTER_MODE: '{adapter_mode_str}'. Must be 'MOCK' or 'REAL'.")
        adapter_mode = AdapterMode(adapter_mode_str)

        if adapter_mode == AdapterMode.REAL and "replace_with" in raw_secret.lower():
            raise ConfigurationError("Cannot use placeholder HMAC secret in REAL production adapter mode.")

        env_mode_str = e.get("WORKER_ENVIRONMENT", "DEMO").upper().strip()
        if env_mode_str not in ("DEMO", "RESEARCH", "PRODUCTION_READONLY"):
            raise ConfigurationError(f"Invalid WORKER_ENVIRONMENT: '{env_mode_str}'.")
        worker_env = WorkerEnvironment(env_mode_str)

        raw_symbols = e.get("WORKER_ALLOWED_SYMBOLS", "EURUSD")
        allowed_symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]

        try:
            port = int(e.get("WORKER_BIND_PORT", "8080"))
        except ValueError:
            raise ConfigurationError("WORKER_BIND_PORT must be an integer.")

        try:
            mt5_login_val = int(e["WORKER_MT5_LOGIN"]) if e.get("WORKER_MT5_LOGIN") else None
        except ValueError:
            raise ConfigurationError("WORKER_MT5_LOGIN must be an integer.")

        try:
            timeout_ms = int(e.get("WORKER_MT5_TIMEOUT_MS", "5000"))
        except ValueError:
            raise ConfigurationError("WORKER_MT5_TIMEOUT_MS must be an integer.")

        try:
            replay_window = float(e.get("WORKER_REPLAY_WINDOW_SECONDS", "30.0"))
            future_skew = float(e.get("WORKER_MAX_FUTURE_SKEW_SECONDS", "5.0"))
            idempotency_ttl = float(e.get("WORKER_IDEMPOTENCY_TTL_SECONDS", "60.0"))
        except ValueError:
            raise ConfigurationError("Timing parameters must be valid numeric values.")

        return cls(
            node_id=e.get("WORKER_NODE_ID", "win-mt5-worker-01").strip(),
            node_name=e.get("WORKER_NODE_NAME", "Windows MT5 Worker V3").strip(),
            environment=worker_env,
            adapter_mode=adapter_mode,
            hmac_secret=raw_secret,
            bind_host=e.get("WORKER_BIND_HOST", "127.0.0.1").strip(),
            bind_port=port,
            allowed_symbols=allowed_symbols,
            mt5_path=e.get("WORKER_MT5_PATH"),
            mt5_server=e.get("WORKER_MT5_SERVER"),
            mt5_login=mt5_login_val,
            mt5_timeout_ms=timeout_ms,
            replay_window_seconds=replay_window,
            max_future_skew_seconds=future_skew,
            idempotency_ttl_seconds=idempotency_ttl,
            log_level=e.get("WORKER_LOG_LEVEL", "INFO").strip().upper(),
        )
