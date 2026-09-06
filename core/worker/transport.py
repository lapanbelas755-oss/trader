"""Windows MT5 Worker V3 — Transport Abstraction and HTTP Server.
Provides local loopback and zero-dependency HTTP server over Python standard library.
Ensures network isolation: binds only to local or private VPN/Tailscale interfaces.
"""
from abc import ABC, abstractmethod
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import threading
from typing import Any, Optional

from core.execution.v2_spec import (
    SignedNodeRequest,
    WorkerV2ErrorCode,
    WorkerV2Response,
)
from core.worker.worker import MT5WorkerV3

logger = logging.getLogger(__name__)


class IWorkerTransport(ABC):
    """Abstract interface for worker transports."""

    @abstractmethod
    def start(self) -> bool:
        """Start transport listener."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop transport listener."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Return True if transport is actively serving."""
        pass


class LoopbackWorkerTransport(IWorkerTransport):
    """Direct in-memory transport for integration testing without opening OS sockets."""

    def __init__(self, worker: MT5WorkerV3) -> None:
        self.worker = worker
        self._running = False

    def start(self) -> bool:
        self._running = True
        return True

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def send_request(self, request: SignedNodeRequest) -> WorkerV2Response:
        """Directly dispatch request to worker."""
        if not self._running:
            return WorkerV2Response(
                node_id=self.worker.config.node_id,
                request_id=request.request_id,
                status=WorkerV2ErrorCode.NODE_OFFLINE,
                error_message="Loopback transport is not running.",
            )
        return self.worker.process_request(request)


class WorkerHTTPRequestHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP handler for Worker V3 JSON-RPC / REST requests."""

    server: "HTTPWorkerServer"  # Type annotation for reference to custom server

    def log_message(self, format: str, *args: Any) -> None:
        # Route standard library server logs to standard logger
        logger.debug("Worker HTTP: %s", format % args)

    def do_GET(self) -> None:
        """Handle unauthenticated health ping."""
        if self.path in ("/api/v3/health", "/health"):
            worker = self.server.worker
            uptime = round(worker.get_uptime_seconds(), 2)
            body = json.dumps({
                "node_id": worker.config.node_id,
                "node_name": worker.config.node_name,
                "status": "ONLINE",
                "worker_state": worker.state.value,
                "mt5_state": worker.adapter.get_connection_state().value,
                "uptime_seconds": uptime,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404, "Endpoint not found.")

    def do_POST(self) -> None:
        """Handle authenticated, signed worker requests."""
        if self.path != "/api/v3/request":
            self.send_error(404, "Unknown endpoint. Use /api/v3/request.")
            return

        content_len_header = self.headers.get("Content-Length")
        if not content_len_header:
            self.send_error(411, "Length Required.")
            return

        try:
            content_length = int(content_len_header)
        except ValueError:
            self.send_error(400, "Invalid Content-Length header.")
            return

        # DoS protection: limit request body to 64 KB
        if content_length > 65536:
            self.send_error(413, "Payload Too Large (max 64KB).")
            return

        body = self.rfile.read(content_length)
        try:
            raw_data = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._send_worker_response(
                WorkerV2Response(
                    node_id=self.server.worker.config.node_id,
                    request_id="req_malformed",
                    status=WorkerV2ErrorCode.PROTOCOL_ERROR,
                    error_message=f"Invalid JSON payload: {e}",
                )
            )
            return

        # Process through worker security pipeline
        response = self.server.worker.process_request(raw_data)
        self._send_worker_response(response)

    def _send_worker_response(self, response: WorkerV2Response) -> None:
        """Serialize and send WorkerV2Response JSON."""
        resp_json = response.model_dump_json()
        resp_bytes = resp_json.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.send_header("X-Request-Id", response.request_id)
        self.send_header("X-Node-Id", response.node_id)
        self.end_headers()
        self.wfile.write(resp_bytes)


class HTTPWorkerServer(HTTPServer, IWorkerTransport):
    """Local / Private HTTP server binding strictly to configured host/port."""

    def __init__(self, worker: MT5WorkerV3) -> None:
        self.worker = worker
        host = worker.config.bind_host
        port = worker.config.bind_port
        super().__init__((host, port), WorkerHTTPRequestHandler)
        self._thread: Optional[threading.Thread] = None
        self._is_serving = False

    def start(self) -> bool:
        if self._is_serving:
            return True
        logger.info("Starting HTTPWorkerServer on %s:%s", self.worker.config.bind_host, self.worker.config.bind_port)
        self._is_serving = True
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self._is_serving:
            return
        logger.info("Stopping HTTPWorkerServer...")
        self._is_serving = False
        self.shutdown()
        self.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("HTTPWorkerServer stopped.")

    def is_running(self) -> bool:
        return self._is_serving
