# TRADER MACHINE — WINDOWS MT5 WORKER V2 SPECIFICATION
## Non-Trading Remote Execution Bridge & Telemetry Interface

---

## 1. System Overview & Core Principles

The **Windows MT5 Worker V2** serves exclusively as the remote "hands and eyes" of Trader Machine. It is an unprivileged, read-only telemetry bridge running on a dedicated Windows node that interfaces directly with a locally running MetaTrader 5 terminal.

```
+-------------------------------------------------------------+
|                      macOS HOST                             |
|  Trader Machine Core (Analytics, Features, Setups, Backtest)|
+-------------------------------------------------------------+
                              |
                              | Encrypted Mesh (Tailscale/WireGuard)
                              | HMAC-SHA256 Signed JSON-RPC
                              v
+-------------------------------------------------------------+
|                   WINDOWS WORKER NODE                       |
|  +-------------------------------------------------------+  |
|  | Windows Service: tm-worker-v2 (Non-Privileged User)   |  |
|  |   - Auth / Signature Verifier                         |  |
|  |   - Replay Protection & Idempotency Cache             |  |
|  |   - Hard Read-Only Safety Barrier                     |  |
|  +-------------------------------------------------------+  |
|                              | Local Win32 IPC              |
|                              v                              |
|  +-------------------------------------------------------+  |
|  | MetaTrader 5 Terminal (terminal64.exe)                |  |
|  |   - Logged into Exness DEMO Server                    |  |
|  +-------------------------------------------------------+  |
+-------------------------------------------------------------+
```

### Core Constraints
1. **Zero Trading Intelligence**: The worker contains no models, heuristics, strategy logic, indicators, or setup detectors.
2. **Strictly Read-Only**: The worker has no executable trading path. Any trading interface is hard-blocked and unconditionally prohibited.
3. **No Inference Privilege**: The worker reports only what is directly measurable.

---

## 2. Rigorous Information Classification

To prevent data fabrication and unfounded assumptions, all fields produced or handled by the worker are classified into four strict epistemic categories:

| Classification | Definition | Examples | Permitted on Worker V2 |
| :--- | :--- | :--- | :--- |
| **OBSERVED** | Raw data directly returned by the MT5 terminal API via broker quote feeds or terminal state. | Bid quote, Ask quote, Tick timestamp, Account balance, Terminal connection status, Position tickets. | **YES** |
| **DERIVED** | Deterministic mathematical or geometric calculations computed strictly from observed data without external assumptions. | Spread ($\text{Ask} - \text{Bid}$), Floating Equity ($\text{Balance} + \text{Profit}$), Margin Level ($\frac{\text{Equity}}{\text{Margin}} \times 100$). | **YES** (Must document derivation formula) |
| **INFERRED** | Probabilistic interpretations, beliefs, or speculative claims regarding market intent or order flow. | *"Bank is buying"*, *"Institutional accumulation"*, *"Liquidity sweep occurred"*, *"Smart money footprint"*. | **STRICTLY PROHIBITED** |
| **UNKNOWN** | Any variable, metric, or entity not directly measurable within the local terminal instance. | Global interbank volume, specific participant identity, aggregate liquidity outside broker book. | **STRICTLY PROHIBITED** |

---

## 3. Specification Architecture (38 Focus Areas)

### 1. Windows Worker Architecture
- Operates as a stateless request-reply server coupled to a local background health/telemetry monitor.
- Binds strictly to a private overlay network IP (Tailscale/WireGuard interface), never `0.0.0.0` or public internet interfaces.
- Uses standard Python 3.12+ 64-bit on Windows, linking to the official `MetaTrader5` PyPI package.

### 2. Process Model
- **Supervision**: Managed as a Windows Service (`tm-worker-v2`) via NSSM (Non-Sucking Service Manager) or native Windows Service API.
- **Privilege Separation**: Executes under a dedicated standard user account (`tm-runner`), strictly denying `Administrator` or `LocalSystem` privileges.
- **Child Processes**: Does not spawn external shells (`cmd.exe`, `powershell.exe`) or interactive processes.

### 3. Service Lifecycle
- `SERVICE_START`: Initializes cryptographic verifier, checks MT5 process presence, binds to Tailscale IP.
- `SERVICE_RUNNING`: Dispatches read-only requests, runs heartbeat background thread.
- `SERVICE_STOPPING`: Completes active read-only queries, closes MT5 IPC session (`mt5.shutdown()`), shuts down transport listener.
- `SERVICE_STOPPED`: Clean termination with exit code 0.

### 4. MT5 Terminal Lifecycle Detection
- Continuously polls Windows Process Table via `EnumProcesses` / Win32 API to detect `terminal64.exe`.
- Distinguishes between:
  - Terminal process missing (`MT5_NOT_INSTALLED` / `MT5_OFFLINE`)
  - Terminal process present but IPC uninitialized
  - Terminal IPC initialized and broker session synchronized (`CONNECTED_READ_ONLY`)

### 5. Node Registration
- Upon startup, the worker registers with the macOS Trader Machine via an announcement payload:
  `{ node_id: "win-mt5-node-01", protocol_version: "2.0.0", host: "Windows Server 2022", environment: "DEMO", capabilities: ["READ_ONLY"] }`

### 6. Authentication
- Mutual authentication using Pre-Shared Keys (PSK) and asymmetric identity verification over WireGuard/Tailscale.
- Every HTTP/WebSocket frame carries an `Authorization: Bearer <HMAC-Signature>` header.
- Plaintext passwords and broker credentials are never transmitted over the wire.

### 7. Request Signing
- All requests must be cryptographically signed using HMAC-SHA256:
  $$\text{Signature} = \text{HMAC-SHA256}(K_{\text{psk}}, \text{CanonicalBytes}(\text{Request}))$$
- Canonical format: Sorted-key JSON containing `request_id`, `action`, `params`, `nonce`, `timestamp_iso`, `idempotency_key`, `protocol_version`.

### 8. Replay Protection
- Every request carries a unique UUID4 `nonce` and a UTC timestamp `timestamp_utc`.
- Nonces are held in an in-memory sliding window cache for $30\text{ seconds}$.
- Requests with timestamps older than $30\text{ seconds}$ or future clock skew $> 5\text{ seconds}$ are rejected with `REPLAY_ATTACK_DETECTED` or `CLOCK_SKEW_DETECTED`.

### 9. Heartbeat
- Worker maintains a periodic $5\text{-second}$ heartbeat ping returning `HealthInfo`.
- If macOS Trader Machine misses 3 consecutive heartbeats ($15\text{s}$), the node is marked `NODE_OFFLINE`.

### 10. Timeout Policy
- Default request-reply timeout is set to $5.0\text{ seconds}$.
- Individual MT5 Win32 IPC calls enforce a hard $2.0\text{-second}$ internal deadline to prevent thread hanging.

### 11. Retry Policy
- Client-side exponential backoff: $250\text{ms}, 500\text{ms}, 1000\text{ms}$ up to a maximum of 3 retries.
- Retries are permitted ONLY for read-only operations and must supply the identical `idempotency_key`.

### 12. Idempotency
- Worker maintains an `IdempotencyCache` with a $60\text{-second}$ TTL.
- Duplicate requests bearing the same `idempotency_key` return the identical cached `WorkerV2Response` without re-querying MT5.

### 13. Request/Response Schema
- Standardized request (`SignedNodeRequest`) and envelope (`WorkerV2Response`):
  ```json
  {
    "node_id": "win-mt5-node-01",
    "protocol_version": "2.0.0",
    "request_id": "req_get_tick_1725586971000_1",
    "timestamp_utc": "2026-09-06T01:42:51.000Z",
    "status": "SUCCESS",
    "data_classification": "OBSERVED",
    "payload": { "symbol": "EURUSD", "bid": "1.14120", "ask": "1.14132" },
    "error_message": null
  }
  ```

### 14. Error Taxonomy
Exhaustive error enumeration in `WorkerV2ErrorCode`:
- `SUCCESS`, `NODE_OFFLINE`, `MT5_OFFLINE`, `AUTH_FAILED`, `SIGNATURE_INVALID`, `REPLAY_ATTACK_DETECTED`, `CLOCK_SKEW_DETECTED`, `SYMBOL_UNAVAILABLE`, `TIMEOUT`, `PROTOCOL_ERROR`, `READ_ONLY_VIOLATION`, `TERMINAL_CRASHED`, `BROKER_DISCONNECTED`, `UNKNOWN_ERROR`.

### 15. MT5 Connection States
Strictly tracked terminal connection states:
- `DISCONNECTED`: `terminal64.exe` is closed or IPC failed.
- `CONNECTING`: Process active, establishing broker handshake.
- `CONNECTED_NO_TRADING`: Account connected, trade server synchronized, trade permissions disabled (desired state).
- `CONNECTED_READ_ONLY`: Full read-only quote telemetry available.

### 16. Broker/Account State
- Queries broker server name, demo mode flag, leverage, currency, balance, equity, margin, free margin.
- Masked login identifier: Raw logins are masked as `XXX****`.
- Password fields are completely omitted from all contracts.

### 17. Symbol State
- Verifies instrument existence in MarketWatch.
- Reports visibility (`visible: bool`), point size (`point: Decimal`), price digits (`digits: int`), contract size, and trade mode (must remain disabled/read-only).

### 18. Tick Retrieval Contract
- Directly reads `symbol_info_tick(symbol)` from MT5.
- Fields: `symbol`, `time` (UTC), `bid` (OBSERVED), `ask` (OBSERVED), `last` (OBSERVED or null), `spread` (DERIVED: $\text{Ask} - \text{Bid}$), `volume` (OBSERVED tick activity count, with disclaimer that it is NOT real traded volume).

### 19. Position Retrieval Contract
- Queries active positions via `positions_get()`.
- Fields: `ticket`, `symbol`, `type` (`BUY`/`SELL`), `volume`, `price_open`, `sl`, `tp`, `price_current`, `profit`, `time` (UTC).

### 20. Account Retrieval Contract
- Read-only data model `AccountInfoReadOnly` with zero mutable credentials.

### 21. Terminal Information Contract
- Queries `terminal_info()`: path, data path, build number, company, `trade_allowed: bool` (verified `False`).

### 22. Health-Check Contract
- Fast lightweight ping returning `HealthInfo`: `status` (`HEALTHY`/`DEGRADED`/`UNHEALTHY`), `mt5_connected`, `terminal_running`, `uptime_seconds`, `latency_internal_ms`.

### 23. Audit Logging
- Structured NDJSON logging to rotating local files: `logs/worker_audit_%Y%m%d.jsonl`.
- Every entry logs: `timestamp_utc`, `request_id`, `action`, `client_ip`, `status`, `latency_ms`.
- Strict credential filter: regex and structural redaction masks any tokens or keys.

### 24. Credential Isolation
- Broker demo login details are configured directly inside MT5 terminal profile or encrypted Windows Credential Manager.
- Worker process memory never contains broker passwords in plaintext Python strings.

### 25. Secret Management
- Worker HMAC Pre-Shared Key (PSK) is loaded from Windows Environment Variable `TM_WORKER_PSK` or Windows DPAPI-encrypted file.
- Never checked into git or hardcoded.

### 26. Network Isolation
- Windows Firewall configured with strict default-deny inbound rules:
  - Inbound allowed ONLY on WireGuard/Tailscale adapter interface (`100.x.y.z`).
  - Block all inbound connections on public Ethernet/Wi-Fi adapters.

### 27. Tailscale / WireGuard Compatibility
- Worker binds explicitly to Tailscale MagicDNS / IP.
- Point-to-point WireGuard encryption guarantees integrity and confidentiality across WAN/Internet.

### 28. Windows Restart Behavior
- Service registered with Windows Service Control Manager set to `StartupType: Automatic (Delayed Start)`.
- Reconnects automatically to Tailscale and MT5 without manual operator intervention.

### 29. MT5 Restart Behavior
- If `terminal64.exe` exits or crashes, the worker marks `MT5_OFFLINE`.
- Exponential retry watchdog checks terminal health every $5\text{ seconds}$ and re-initializes IPC when terminal restarts.

### 30. Worker Crash Recovery
- Stateless design ensures immediate crash recovery without persistent state corruption.
- In-flight requests timeout safely on client; client resends with idempotency key.

### 31. Clock Synchronization
- Windows host must configure `w32tm` (Windows Time Service) synchronized via NTP to `pool.ntp.org` or `time.windows.com`.
- Skew must remain $< 500\text{ms}$ relative to UTC.

### 32. UTC Timestamp Rules
- Every timestamp generated or consumed by the worker is ISO-8601 UTC with explicit `+00:00` or `Z` offset. Naive timestamps are rejected.

### 33. Version Compatibility
- SemVer tracking: Worker V2 enforces major version match (`2.x.x`). Mismatches return `PROTOCOL_ERROR`.

### 34. Protocol Compatibility
- Forward/backward compatibility managed via JSON-RPC / REST schemas. Unknown parameters are ignored; missing required fields return `PROTOCOL_ERROR`.

### 35. Security Threat Model
- **Threat 1: Man-in-the-Middle (MITM)** $\rightarrow$ Mitigated by WireGuard point-to-point encryption + HMAC-SHA256 signature verification.
- **Threat 2: Replay Attack** $\rightarrow$ Mitigated by sliding window timestamp check ($30\text{s}$) and non-repeating nonces.
- **Threat 3: Unauthorized Action Injection** $\rightarrow$ Mitigated by pre-shared key signature verification.
- **Threat 4: Accidental Order Execution** $\rightarrow$ Mitigated by permanent architectural code-level absence of order execution methods (`TradingProhibitedError`).

### 36. Failure Scenarios
1. Broker Server Maintenance $\rightarrow$ Worker returns `BROKER_DISCONNECTED`.
2. Symbol Delisted/Hidden $\rightarrow$ Worker returns `SYMBOL_UNAVAILABLE`.
3. Network Glitch $\rightarrow$ Client triggers timeout ($5\text{s}$) and idempotent retry.
4. Windows Host Reboot $\rightarrow$ Client reports `NODE_OFFLINE` until service restarts.

### 37. Observability
- Emits Prometheus metrics or structured JSON stats:
  - `tm_worker_requests_total{action, status}`
  - `tm_worker_latency_seconds{action}`
  - `tm_worker_mt5_connected_gauge`

### 38. Test Strategy
- Hermetic Python unit tests for:
  - HMAC signing and verification
  - Replay protection (expired timestamps, clock skew, duplicate nonces)
  - Idempotency caching
  - Error code taxonomy
  - Source code audit ensuring no order execution paths exist

---

## 4. Hard Read-Only Safety Protocol

```python
# PERMANENT ARCHITECTURAL FIREWALL
def send_order(*args, **kwargs):
    raise TradingProhibitedError("order_send is permanently prohibited on Windows MT5 Worker V2.")

def order_check(*args, **kwargs):
    raise TradingProhibitedError("order_check is permanently prohibited on Windows MT5 Worker V2.")

def position_close(*args, **kwargs):
    raise TradingProhibitedError("position_close is permanently prohibited on Windows MT5 Worker V2.")
```

---
*Trader Machine V2 Specification Document — Research / Demo Only.*
