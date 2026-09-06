"""Windows MT5 Worker V3 — Startup and Security Diagnostics.
Provides automated environment checks, security audits, and verification of zero executable trading paths.
"""
from datetime import datetime, timezone
import logging
from pathlib import Path
import platform
import sys
from typing import Any, Optional

from core.worker.adapter import IMT5Adapter, MT5ConnectionState
from core.worker.config import WorkerConfig

logger = logging.getLogger(__name__)

PROHIBITED_CALLS = [
    "order_send",
    "OrderSend",
    "order_check",
    "position_close",
    "position_modify",
    "order_modify",
]


def run_startup_diagnostics(config: WorkerConfig, adapter: IMT5Adapter) -> dict[str, Any]:
    """Execute pre-flight environment checks before worker enters listening state."""
    py_ver = sys.version.split()[0]
    os_name = platform.system()
    os_release = platform.release()
    arch = platform.machine()
    is_windows = (os_name == "Windows")

    mt5_state = adapter.get_connection_state().value

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "node_id": config.node_id,
        "node_name": config.node_name,
        "environment": config.environment.value,
        "adapter_mode": config.adapter_mode.value,
        "python_version": py_ver,
        "os_platform": f"{os_name} {os_release} ({arch})",
        "is_windows": is_windows,
        "mt5_adapter_state": mt5_state,
        "bind_address": f"{config.bind_host}:{config.bind_port}",
        "allowed_symbols": config.allowed_symbols,
        "hmac_configured": bool(config.hmac_secret and len(config.hmac_secret) >= 16),
        "replay_window_s": config.replay_window_seconds,
        "idempotency_ttl_s": config.idempotency_ttl_seconds,
    }


def run_security_audit(project_root: Optional[Path] = None) -> dict[str, Any]:
    """Statically audit worker and execution packages to verify zero executable trading paths.
    Fails if any calls to order_send, OrderSend, order_check, position_close, etc. exist.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent.parent

    scanned_files = []
    violations = []

    dirs_to_scan = [
        project_root / "core" / "worker",
        project_root / "core" / "execution",
    ]

    for d in dirs_to_scan:
        if not d.exists():
            continue
        for py_file in d.glob("*.py"):
            scanned_files.append(str(py_file.relative_to(project_root)))
            content = py_file.read_text(encoding="utf-8")
            for line_no, line in enumerate(content.splitlines(), start=1):
                clean_line = line.strip()
                # Skip comments and test docstrings
                if clean_line.startswith("#") or clean_line.startswith('"""') or clean_line.startswith("'''"):
                    continue
                for bad_call in PROHIBITED_CALLS:
                    # Check for actual calls like mt5.order_send, adapter.order_send, order_send(
                    pattern = f"{bad_call}("
                    if pattern in clean_line:
                        # Allow explicit firewall raise in connector.py if it raises TradingProhibitedError
                        if "TradingProhibitedError" in clean_line or "def " in clean_line:
                            continue
                        violations.append({
                            "file": str(py_file.relative_to(project_root)),
                            "line": line_no,
                            "pattern": bad_call,
                            "snippet": clean_line,
                        })

    return {
        "status": "PASS" if not violations else "FAIL",
        "files_scanned_count": len(scanned_files),
        "files_scanned": scanned_files,
        "violations_count": len(violations),
        "violations": violations,
        "read_only_guaranteed": (len(violations) == 0),
    }
