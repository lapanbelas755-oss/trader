"""Windows MT5 Worker V3 Package.
Operational Read-Only Worker for MetaTrader 5 telemetry.
"""
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
from core.worker.diagnostics import (
    run_security_audit,
    run_startup_diagnostics,
)
from core.worker.transport import (
    HTTPWorkerServer,
    IWorkerTransport,
    LoopbackWorkerTransport,
)
from core.worker.worker import (
    ALLOWED_READONLY_ACTIONS,
    MT5WorkerV3,
    PROHIBITED_TRADE_ACTIONS,
    WorkerState,
    WORKER_V3_VERSION,
)

__all__ = [
    "IMT5Adapter",
    "MockMT5Adapter",
    "MT5ConnectionState",
    "RealMT5Adapter",
    "AdapterMode",
    "ConfigurationError",
    "WorkerConfig",
    "WorkerEnvironment",
    "run_security_audit",
    "run_startup_diagnostics",
    "HTTPWorkerServer",
    "IWorkerTransport",
    "LoopbackWorkerTransport",
    "ALLOWED_READONLY_ACTIONS",
    "MT5WorkerV3",
    "PROHIBITED_TRADE_ACTIONS",
    "WorkerState",
    "WORKER_V3_VERSION",
]
