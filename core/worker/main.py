"""Windows MT5 Worker V3 — Application Entry Point.
Executable runner for the Windows MT5 Read-Only Worker service.
Supports CLI arguments, environment variable configuration, and graceful shutdown.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any

from dotenv import load_dotenv

from core.worker.adapter import IMT5Adapter, MockMT5Adapter, RealMT5Adapter
from core.worker.config import AdapterMode, ConfigurationError, WorkerConfig
from core.worker.diagnostics import run_security_audit, run_startup_diagnostics
from core.worker.transport import HTTPWorkerServer
from core.worker.worker import MT5WorkerV3

logger = logging.getLogger("core.worker")


class CredentialRedactionFilter(logging.Filter):
    """Logging filter to prevent accidental leakage of sensitive tokens."""

    def __init__(self, secret: str = "") -> None:
        super().__init__()
        self.secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.msg)
        if self.secret and self.secret in msg:
            record.msg = msg.replace(self.secret, "***REDACTED***")
        return True


def setup_logging(level_name: str = "INFO", secret: str = "") -> None:
    """Configure structured console logging with credential redaction."""
    numeric_level = getattr(logging, level_name.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    if secret:
        handler.addFilter(CredentialRedactionFilter(secret))

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()
    root_logger.addHandler(handler)


def build_adapter(config: WorkerConfig) -> IMT5Adapter:
    """Instantiate appropriate MT5 adapter based on configuration mode."""
    if config.adapter_mode == AdapterMode.REAL:
        logger.info("Initializing RealMT5Adapter for production Windows MT5...")
        return RealMT5Adapter(
            path=config.mt5_path,
            server=config.mt5_server,
            login=config.mt5_login,
            timeout_ms=config.mt5_timeout_ms,
        )
    else:
        logger.info("Initializing MockMT5Adapter for testing/development mode...")
        return MockMT5Adapter(symbols_available=config.allowed_symbols)


def main() -> int:
    """Main application loop."""
    parser = argparse.ArgumentParser(description="Trader Machine — Windows MT5 Worker V3 (Read-Only)")
    parser.add_argument("--env-file", type=str, default=".env", help="Path to .env configuration file")
    parser.add_argument("--diagnostics", action="store_true", help="Run startup diagnostics and exit")
    parser.add_argument("--audit", action="store_true", help="Run static security audit and exit")
    args = parser.parse_args()

    # Load environment file if present
    env_path = Path(args.env_file)
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)

    # If security audit requested
    if args.audit:
        audit_result = run_security_audit()
        print(json.dumps(audit_result, indent=2))
        return 0 if audit_result["status"] == "PASS" else 1

    # Load configuration
    try:
        config = WorkerConfig.from_env()
    except ConfigurationError as e:
        print(f"CONFIGURATION ERROR: {e}", file=sys.stderr)
        return 1

    setup_logging(config.log_level, config.hmac_secret)
    logger.info("Worker V3 Configuration loaded successfully. (Node: %s)", config.node_id)

    # Instantiate adapter
    adapter = build_adapter(config)

    # If diagnostics requested
    if args.diagnostics:
        diag = run_startup_diagnostics(config, adapter)
        print(json.dumps(diag, indent=2))
        return 0

    # Instantiate worker and transport
    worker = MT5WorkerV3(config=config, adapter=adapter)
    server = HTTPWorkerServer(worker=worker)

    # Setup signal handling for graceful shutdown
    stop_event = False

    def handle_signal(signum: int, frame: Any) -> None:
        nonlocal stop_event
        logger.info("Received termination signal (%s). Initiating graceful shutdown...", signum)
        stop_event = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Start worker and server
    worker.start()
    server.start()
    logger.info("Worker V3 HTTP Server listening on %s:%s", config.bind_host, config.bind_port)

    # Run event loop
    try:
        while not stop_event:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        server.stop()
        worker.stop()
        logger.info("Worker V3 shutdown completed cleanly.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
