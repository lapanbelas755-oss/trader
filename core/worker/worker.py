"""Windows MT5 Worker V3 — Core Worker Implementation.
Handles incoming cryptographically signed requests, validates nonces and replay windows,
enforces strict read-only action allowlists, queries MT5 adapter, and returns classified responses.
"""
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import logging
import time
from typing import Any, Optional, Union

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
from core.worker.adapter import IMT5Adapter, MT5ConnectionState
from core.worker.config import WorkerConfig

logger = logging.getLogger(__name__)

WORKER_V3_VERSION = "3.0.0"

ALLOWED_READONLY_ACTIONS = {
    "get_health",
    "get_terminal_info",
    "get_account_info",
    "get_symbol_info",
    "get_tick",
    "get_positions",
}

# Explicitly forbidden actions that must trigger immediate security alarms
PROHIBITED_TRADE_ACTIONS = {
    "send_order",
    "order_send",
    "OrderSend",
    "order_check",
    "position_close",
    "close_position",
    "position_modify",
    "modify_position",
    "order_modify",
    "modify_order",
    "buy",
    "sell",
}


class WorkerState(str, Enum):
    """Lifecycle state of Worker V3 instance."""
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class MT5WorkerV3:
    """Operational Read-Only Windows MT5 Worker V3.
    Provides deterministic MT5 telemetry with zero trading capabilities.
    """

    def __init__(self, config: WorkerConfig, adapter: IMT5Adapter) -> None:
        self.config = config
        self.adapter = adapter
        self.state = WorkerState.STOPPED
        self.start_time: Optional[float] = None

        # Cryptographic and replay validators
        self.signer = HMACRequestSigner()
        self.replay_validator = ReplayProtectionValidator(
            window_seconds=config.replay_window_seconds,
            max_future_skew_seconds=config.max_future_skew_seconds,
        )
        self.idempotency_cache = IdempotencyCache(
            ttl_seconds=config.idempotency_ttl_seconds,
        )

    def start(self) -> bool:
        """Start worker and initialize MT5 adapter."""
        logger.info("Starting Worker V3 (Node: %s, Mode: %s)", self.config.node_id, self.config.adapter_mode.value)
        self.state = WorkerState.STARTING
        self.start_time = time.time()

        init_ok = self.adapter.initialize()
        if init_ok:
            self.state = WorkerState.RUNNING
            logger.info("Worker V3 is RUNNING. Adapter state: %s", self.adapter.get_connection_state().value)
        else:
            # We still run even if MT5 is disconnected/unavailable, but report DEGRADED/OFFLINE
            self.state = WorkerState.RUNNING
            logger.warning(
                "Worker V3 started with MT5 offline or not initialized: %s",
                self.adapter.get_connection_state().value,
            )
        return True

    def stop(self) -> None:
        """Gracefully stop worker and release adapter resources."""
        logger.info("Stopping Worker V3 (Node: %s)...", self.config.node_id)
        self.state = WorkerState.STOPPING
        try:
            self.adapter.shutdown()
        except Exception as e:
            logger.error("Error shutting down MT5 adapter: %s", e)
        self.state = WorkerState.STOPPED
        logger.info("Worker V3 STOPPED.")

    def get_uptime_seconds(self) -> float:
        """Return worker uptime in seconds."""
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    def process_request(
        self,
        request: Union[dict[str, Any], SignedNodeRequest],
        current_time: Optional[float] = None,
    ) -> WorkerV2Response:
        """Process incoming request through full security and dispatch pipeline."""
        now_ts = current_time if current_time is not None else time.time()

        # Step 1: Parse and validate request schema
        if isinstance(request, dict):
            try:
                signed_req = SignedNodeRequest(**request)
            except Exception as e:
                logger.warning("Malformed request rejected: %s", e)
                return WorkerV2Response(
                    node_id=self.config.node_id,
                    request_id=request.get("request_id", "req_unknown"),
                    status=WorkerV2ErrorCode.PROTOCOL_ERROR,
                    error_message=f"Malformed request schema: {e}",
                )
        else:
            signed_req = request

        # Step 2: Protocol version check (Accepts 2.0.0 and 3.0.0)
        if signed_req.protocol_version not in ("2.0.0", "3.0.0"):
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=signed_req.request_id,
                status=WorkerV2ErrorCode.PROTOCOL_ERROR,
                error_message=f"Unsupported protocol version: '{signed_req.protocol_version}'. Required 2.0.0 or 3.0.0.",
            )

        # Step 3: Check Idempotency Cache
        if signed_req.idempotency_key:
            cached_resp = self.idempotency_cache.get(signed_req.idempotency_key, current_time=now_ts)
            if cached_resp is not None:
                logger.debug("Idempotent response returned for key: %s", signed_req.idempotency_key)
                return cached_resp

        # Step 4: HMAC Signature Verification
        if not signed_req.signature:
            logger.warning("Request %s rejected: missing HMAC signature", signed_req.request_id)
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=signed_req.request_id,
                status=WorkerV2ErrorCode.SIGNATURE_INVALID,
                error_message="Missing HMAC signature.",
            )

        if not HMACRequestSigner.verify_signature(signed_req, self.config.hmac_secret):
            logger.warning("Request %s rejected: signature verification failed", signed_req.request_id)
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=signed_req.request_id,
                status=WorkerV2ErrorCode.SIGNATURE_INVALID,
                error_message="Invalid HMAC-SHA256 signature.",
            )

        # Step 5: Replay Protection (Age window, future clock skew, nonce reuse)
        valid, err_code, err_msg = self.replay_validator.validate_request(signed_req, current_time=now_ts)
        if not valid:
            logger.warning("Request %s replay check failed: %s (%s)", signed_req.request_id, err_code, err_msg)
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=signed_req.request_id,
                status=err_code or WorkerV2ErrorCode.PROTOCOL_ERROR,
                error_message=err_msg,
            )

        # Step 6: Strict Action Allowlist & Read-Only Firewall
        action = signed_req.action.strip()
        if action in PROHIBITED_TRADE_ACTIONS:
            logger.critical("SECURITY ALERT: Prohibited trade action '%s' attempted on read-only worker!", action)
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=signed_req.request_id,
                status=WorkerV2ErrorCode.READ_ONLY_VIOLATION,
                error_message=f"Action '{action}' is a prohibited trade operation. Worker is strictly read-only.",
            )

        if action not in ALLOWED_READONLY_ACTIONS:
            logger.warning("Unknown action '%s' requested.", action)
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=signed_req.request_id,
                status=WorkerV2ErrorCode.PROTOCOL_ERROR,
                error_message=f"Unknown or unauthorized action: '{action}'.",
            )

        # Step 7: Dispatch to Action Handler
        response = self._dispatch_action(signed_req)

        # Step 8: Store in idempotency cache if key provided
        if signed_req.idempotency_key and response.status == WorkerV2ErrorCode.SUCCESS:
            self.idempotency_cache.store(signed_req.idempotency_key, response, current_time=now_ts)

        return response

    def _dispatch_action(self, req: SignedNodeRequest) -> WorkerV2Response:
        """Route authorized request to specific read-only handler."""
        action = req.action

        # Handle health check (allowed even if MT5 is disconnected)
        if action == "get_health":
            return self._handle_get_health(req)

        # For all other telemetry queries, MT5 must be connected
        if not self.adapter.is_connected():
            adapter_state = self.adapter.get_connection_state().value
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.MT5_OFFLINE,
                error_message=f"MT5 terminal is not connected (State: {adapter_state}).",
            )

        if action == "get_terminal_info":
            return self._handle_get_terminal_info(req)
        elif action == "get_account_info":
            return self._handle_get_account_info(req)
        elif action == "get_symbol_info":
            return self._handle_get_symbol_info(req)
        elif action == "get_tick":
            return self._handle_get_tick(req)
        elif action == "get_positions":
            return self._handle_get_positions(req)
        elif action in ("get_historical_rates", "get_bars"):
            return self._handle_get_historical_rates(req)

        return WorkerV2Response(
            node_id=self.config.node_id,
            request_id=req.request_id,
            status=WorkerV2ErrorCode.PROTOCOL_ERROR,
            error_message=f"Unhandled action: '{action}'",
        )

    def _handle_get_health(self, req: SignedNodeRequest) -> WorkerV2Response:
        mt5_state = self.adapter.get_connection_state()
        is_healthy = (self.state == WorkerState.RUNNING and mt5_state == MT5ConnectionState.MT5_CONNECTED)
        status_str = "HEALTHY" if is_healthy else ("DEGRADED" if self.state == WorkerState.RUNNING else "UNHEALTHY")

        payload = {
            "status": status_str,
            "worker_state": self.state.value,
            "mt5_connected": self.adapter.is_connected(),
            "mt5_state": mt5_state.value,
            "uptime_seconds": round(self.get_uptime_seconds(), 2),
            "adapter_mode": self.config.adapter_mode.value,
            "environment": self.config.environment.value,
            "allowed_symbols": self.config.allowed_symbols,
            "node_name": self.config.node_name,
            "worker_version": WORKER_V3_VERSION,
        }
        return WorkerV2Response(
            node_id=self.config.node_id,
            request_id=req.request_id,
            status=WorkerV2ErrorCode.SUCCESS,
            data_classification=InformationClassification.OBSERVED,
            payload=payload,
        )

    def _handle_get_terminal_info(self, req: SignedNodeRequest) -> WorkerV2Response:
        info = self.adapter.get_terminal_info()
        if not info:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.TERMINAL_CRASHED,
                error_message="Failed to retrieve terminal info from MT5.",
            )
        return WorkerV2Response(
            node_id=self.config.node_id,
            request_id=req.request_id,
            status=WorkerV2ErrorCode.SUCCESS,
            data_classification=InformationClassification.OBSERVED,
            payload=info.model_dump(),
        )

    def _handle_get_account_info(self, req: SignedNodeRequest) -> WorkerV2Response:
        acc = self.adapter.get_account_info()
        if not acc:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.BROKER_DISCONNECTED,
                error_message="Failed to retrieve account info from MT5.",
            )
        payload = acc.model_dump(mode="json")
        # Ensure credentials / passwords are never in payload
        if "password" in payload:
            del payload["password"]
        return WorkerV2Response(
            node_id=self.config.node_id,
            request_id=req.request_id,
            status=WorkerV2ErrorCode.SUCCESS,
            data_classification=InformationClassification.OBSERVED,
            payload=payload,
        )

    def _handle_get_symbol_info(self, req: SignedNodeRequest) -> WorkerV2Response:
        symbol = str(req.params.get("symbol", "")).strip().upper()
        if not symbol:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.PROTOCOL_ERROR,
                error_message="Parameter 'symbol' is required.",
            )
        if symbol not in self.config.allowed_symbols:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.SYMBOL_UNAVAILABLE,
                error_message=f"Symbol '{symbol}' is not in allowed symbols: {self.config.allowed_symbols}.",
            )

        sym_info = self.adapter.get_symbol_info(symbol)
        if not sym_info:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.SYMBOL_UNAVAILABLE,
                error_message=f"Symbol '{symbol}' not found or not visible in MT5.",
            )

        payload = sym_info.model_dump(mode="json")
        payload["_classification"] = {
            "bid": InformationClassification.OBSERVED.value,
            "ask": InformationClassification.OBSERVED.value,
            "spread": InformationClassification.DERIVED.value,
        }
        return WorkerV2Response(
            node_id=self.config.node_id,
            request_id=req.request_id,
            status=WorkerV2ErrorCode.SUCCESS,
            data_classification=InformationClassification.DERIVED,
            payload=payload,
        )

    def _handle_get_tick(self, req: SignedNodeRequest) -> WorkerV2Response:
        symbol = str(req.params.get("symbol", "")).strip().upper()
        if not symbol:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.PROTOCOL_ERROR,
                error_message="Parameter 'symbol' is required.",
            )
        if symbol not in self.config.allowed_symbols:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.SYMBOL_UNAVAILABLE,
                error_message=f"Symbol '{symbol}' is not in allowed symbols: {self.config.allowed_symbols}.",
            )

        tick = self.adapter.get_tick(symbol)
        if not tick:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.SYMBOL_UNAVAILABLE,
                error_message=f"No tick data available for symbol '{symbol}'.",
            )

        payload = tick.model_dump(mode="json")
        payload["_classification"] = {
            "bid": InformationClassification.OBSERVED.value,
            "ask": InformationClassification.OBSERVED.value,
            "spread": InformationClassification.DERIVED.value,
            "time": InformationClassification.OBSERVED.value,
            "volume_note": "Quote/tick count only. Not real traded volume.",
        }
        return WorkerV2Response(
            node_id=self.config.node_id,
            request_id=req.request_id,
            status=WorkerV2ErrorCode.SUCCESS,
            data_classification=InformationClassification.OBSERVED,
            payload=payload,
        )

    def _handle_get_positions(self, req: SignedNodeRequest) -> WorkerV2Response:
        raw_symbol = req.params.get("symbol")
        symbol = str(raw_symbol).strip().upper() if raw_symbol else None
        if symbol and symbol not in self.config.allowed_symbols:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.SYMBOL_UNAVAILABLE,
                error_message=f"Symbol '{symbol}' is not in allowed symbols: {self.config.allowed_symbols}.",
            )

        positions = self.adapter.get_positions(symbol)
        pos_list = [p.model_dump(mode="json") for p in positions]
        payload = {
            "count": len(pos_list),
            "positions": pos_list,
        }
        return WorkerV2Response(
            node_id=self.config.node_id,
            request_id=req.request_id,
            status=WorkerV2ErrorCode.SUCCESS,
            data_classification=InformationClassification.OBSERVED,
            payload=payload,
        )

    def _handle_get_historical_rates(self, req: SignedNodeRequest) -> WorkerV2Response:
        symbol = str(req.params.get("symbol", "")).strip().upper()
        timeframe = str(req.params.get("timeframe", "M5")).strip().upper()
        try:
            count = int(req.params.get("count", 80))
        except (ValueError, TypeError):
            count = 80

        if not symbol:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.PROTOCOL_ERROR,
                error_message="Parameter 'symbol' is required.",
            )
        if symbol not in self.config.allowed_symbols:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.SYMBOL_UNAVAILABLE,
                error_message=f"Symbol '{symbol}' is not in allowed symbols: {self.config.allowed_symbols}.",
            )

        valid_tfs = ("M1", "M5", "M15", "H1", "H4", "D1")
        if timeframe not in valid_tfs:
            return WorkerV2Response(
                node_id=self.config.node_id,
                request_id=req.request_id,
                status=WorkerV2ErrorCode.PROTOCOL_ERROR,
                error_message=f"Unsupported timeframe '{timeframe}'. Allowed: {valid_tfs}.",
            )

        raw_rates = self.adapter.get_historical_rates(symbol, timeframe, count)
        formatted = []
        for r in raw_rates:
            t = r.get("timestamp")
            iso_time = t.isoformat() if hasattr(t, "isoformat") else str(t)
            formatted.append({
                "time": iso_time,
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r.get("tick_volume", 0)),
            })

        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(formatted),
            "rates": formatted,
        }
        return WorkerV2Response(
            node_id=self.config.node_id,
            request_id=req.request_id,
            status=WorkerV2ErrorCode.SUCCESS,
            data_classification=InformationClassification.OBSERVED,
            payload=payload,
        )
