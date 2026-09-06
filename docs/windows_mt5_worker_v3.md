# Trader Machine — Windows MT5 Worker V3 (Read-Only)
## Operational Implementation and Telemetry Guide

---

## 1. Architecture Overview

Trader Machine Windows Worker V3 is an operational, standalone daemon designed to run on a dedicated Windows host (local workstation or secure VPS) running MetaTrader 5 connected to Exness DEMO. It acts exclusively as the **read-only sensory organs ("eyes")** of Trader Machine, while all trading logic, decision making, setup detection, and risk management remain on macOS.

```
┌────────────────────────────────────────────────────────┐
│               Mac Trader Machine (macOS)               │
│   Research Pipeline | Decision Engine | PostgreSQL     │
└───────────────────────────┬────────────────────────────┘
                            │
                            │ Encrypted Private Network
                            │ (Tailscale / WireGuard)
                            │ Signed HMAC-SHA256 RPC
                            ▼
┌────────────────────────────────────────────────────────┐
│            Windows MT5 Worker V3 (tm-worker-v3)         │
│   - HMAC Verification & Replay Protection              │
│   - Strict Read-Only Action Allowlist                  │
│   - Epistemic Data Classifier (OBSERVED / DERIVED)     │
│   - Zero Trading Routines Firewalled                  │
└───────────────────────────┬────────────────────────────┘
                            │
                            │ MetaTrader5 Python API (IPC)
                            ▼
┌────────────────────────────────────────────────────────┐
│            MetaTrader 5 Terminal (terminal64)          │
└───────────────────────────┬────────────────────────────┘
                            │
                            │ Broker Protocol
                            ▼
┌────────────────────────────────────────────────────────┐
│                  Exness DEMO Server                    │
└────────────────────────────────────────────────────────┘
```

### Core Architecture Axioms:
1. **Unidirectional Control Flow:** Mac issues signed queries $\rightarrow$ Worker validates and queries MT5 $\rightarrow$ Worker returns classified telemetry.
2. **Zero Intelligence on Worker:** The worker contains zero models, zero predictive logic, and zero strategy parameters.
3. **Hermetic Testing Support:** On macOS/Linux, `MockMT5Adapter` allows 100% test coverage without live MT5. In production on Windows, `RealMT5Adapter` communicates directly with MetaTrader 5.

---

## 2. Installation Requirements

### Hardware / Virtualization:
- **Operating System:** Windows 10 (64-bit), Windows 11 (64-bit), or Windows Server 2022.
- **CPU:** 2 vCPU minimum (4 vCPU recommended).
- **RAM:** 4 GB minimum (8 GB recommended for stable MT5 memory headroom).
- **Disk Space:** 10 GB available SSD storage.

### Software Stack:
- **Python:** Version 3.10, 3.11, or 3.12 (64-bit `amd64`).
- **MetaTrader 5 Terminal:** Official build from Exness or MetaQuotes.
- **Python Packages:**
  - `MetaTrader5 >= 5.0.45` (Windows native package)
  - `pydantic >= 2.6.0`
  - `python-dotenv >= 1.0.1`

---

## 3. Configuration System

Configuration is loaded from environment variables (typically via `.env` file). Secrets are strictly redacted from `repr`, string formatting, and log outputs.

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `WORKER_NODE_ID` | `string` | `win-mt5-worker-01` | Unique node identifier. |
| `WORKER_NODE_NAME` | `string` | `Windows MT5 Worker V3` | Human-readable node label. |
| `WORKER_ENVIRONMENT` | `string` | `DEMO` | `DEMO`, `RESEARCH`, or `PRODUCTION_READONLY`. |
| `WORKER_ADAPTER_MODE` | `string` | `MOCK` | `MOCK` (testing) or `REAL` (Windows live MT5). |
| `WORKER_HMAC_SECRET` | `string` | *Required* | Pre-shared key for HMAC-SHA256 (min 16 chars). |
| `WORKER_BIND_HOST` | `string` | `127.0.0.1` | IP address to bind HTTP listener (e.g. Tailscale IP). |
| `WORKER_BIND_PORT` | `integer` | `8080` | Port for HTTP listener. |
| `WORKER_ALLOWED_SYMBOLS` | `string` | `EURUSD` | Comma-delimited list of permitted instruments. |
| `WORKER_MT5_PATH` | `string` | `None` | Path to `terminal64.exe` (optional if in PATH). |
| `WORKER_MT5_SERVER` | `string` | `None` | MT5 broker server name (e.g. `Exness-Demo`). |
| `WORKER_MT5_LOGIN` | `integer` | `None` | Account login ID. |
| `WORKER_MT5_TIMEOUT_MS` | `integer` | `5000` | Terminal IPC connection timeout. |
| `WORKER_REPLAY_WINDOW_SECONDS` | `float` | `30.0` | Max age window for incoming requests. |
| `WORKER_MAX_FUTURE_SKEW_SECONDS` | `float` | `5.0` | Max allowed forward clock drift. |
| `WORKER_IDEMPOTENCY_TTL_SECONDS` | `float` | `60.0` | Cache TTL for deduplicating retried requests. |
| `WORKER_LOG_LEVEL` | `string` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

---

## 4. Startup & Daemon Execution

### Manual Startup (Interactive Shell):
```powershell
# From project root in PowerShell:
.\scripts\start_worker_windows.ps1
```

### Pre-Flight Diagnostics Check:
```powershell
.\scripts\start_worker_windows.ps1 -CheckOnly
```

### Automated Service Deployment (via NSSM):
```cmd
nssm install TraderMachineWorker "C:\trader-machine\.venv\Scripts\python.exe" "-m core.worker.main --env-file C:\trader-machine\.env"
nssm set TraderMachineWorker AppDirectory "C:\trader-machine"
nssm set TraderMachineWorker AppStdout "C:\trader-machine\logs\worker.log"
nssm set TraderMachineWorker AppStderr "C:\trader-machine\logs\worker_err.log"
nssm set TraderMachineWorker Start SERVICE_AUTO_START
nssm start TraderMachineWorker
```

---

## 5. Health Checks & Diagnostics

### Unauthenticated Health Ping (`GET /api/v3/health`):
Allows Tailscale or system monitoring agents to check liveness without exposing sensitive state:
```bash
curl http://127.0.0.1:8080/api/v3/health
```
```json
{
  "node_id": "win-mt5-worker-01",
  "node_name": "Windows MT5 Worker V3",
  "status": "ONLINE",
  "worker_state": "RUNNING",
  "mt5_state": "MT5_CONNECTED",
  "uptime_seconds": 341.2
}
```

### Authenticated Detailed Health (`POST /api/v3/request` with `get_health`):
Returns comprehensive diagnostics including environment mode, allowed symbols, and terminal connection status.

---

## 6. MT5 Connection States

The worker transitions deterministically across four connection states:

| State | Meaning | Operational Consequence |
| :--- | :--- | :--- |
| `MT5_CONNECTED` | Terminal IPC established; quotes and account queryable. | All read-only commands functional. |
| `MT5_DISCONNECTED` | Terminal process stopped or closed IPC socket. | `get_health` returns `DEGRADED`; quote queries return `MT5_OFFLINE`. |
| `MT5_NOT_INSTALLED` | Python `MetaTrader5` package missing or non-Windows OS. | Worker runs in offline diagnostics mode. |
| `MT5_INITIALIZATION_FAILED` | Terminal failed to launch or broker connection timed out. | Worker logs error and rejects queries with `MT5_OFFLINE`. |

---

## 7. Security & Cryptographic Model

### 1. Authentication (HMAC-SHA256):
- Every request includes a cryptographic signature: `HMAC-SHA256(canonical_bytes, secret_key)`.
- Canonical bytes serialize: `request_id`, `action`, `params`, `nonce`, `timestamp_iso`, `idempotency_key`, `protocol_version` in sorted JSON.
- Verified using constant-time comparison (`hmac.compare_digest`).

### 2. Replay Protection:
- **Timestamp Window:** Requests older than 30 seconds are rejected with `TIMEOUT`.
- **Clock Skew Check:** Requests with timestamps more than 5 seconds in the future are rejected with `CLOCK_SKEW_DETECTED`.
- **Nonce Tracking:** Every request has a unique random nonce. Reused nonces within the window trigger `REPLAY_ATTACK_DETECTED`.

### 3. Idempotency:
- If a request includes `idempotency_key`, identical retries within the 60-second TTL return the cached response immediately without re-querying MT5.

### 4. Credential Isolation:
- Account passwords are never stored in memory longer than terminal initialization.
- Account login numbers are automatically masked (e.g. `882***`).
- Logging filter redacts HMAC secrets and passwords.

---

## 8. API & Request Examples

### Allowed Commands (Strict Allowlist):
- `get_health`
- `get_terminal_info`
- `get_account_info`
- `get_symbol_info`
- `get_tick`
- `get_positions`

### Example Python Client Query (`get_tick`):
```python
from core.execution.v2_spec import HMACRequestSigner, SignedNodeRequest
import requests

secret = "your_32_byte_secret_key_here!"
req = SignedNodeRequest(
    request_id="req_tick_01",
    action="get_tick",
    params={"symbol": "EURUSD"},
)
signed_req = HMACRequestSigner.sign_request(req, secret)

resp = requests.post("http://127.0.0.1:8080/api/v3/request", json=signed_req.model_dump(mode="json"))
print(resp.json())
```

### Response Payload:
```json
{
  "node_id": "win-mt5-worker-01",
  "protocol_version": "2.0.0",
  "request_id": "req_tick_01",
  "timestamp_utc": "2026-09-06T08:50:00Z",
  "status": "SUCCESS",
  "data_classification": "OBSERVED",
  "payload": {
    "symbol": "EURUSD",
    "time": "2026-09-06T08:49:59.120Z",
    "bid": "1.14205",
    "ask": "1.14217",
    "spread": "0.00012",
    "volume": "42",
    "_classification": {
      "bid": "OBSERVED",
      "ask": "OBSERVED",
      "spread": "DERIVED",
      "time": "OBSERVED",
      "volume_note": "Quote/tick count only. Not real traded volume."
    }
  }
}
```

---

## 9. Troubleshooting & Recovery

| Symptom | Probable Cause | Action |
| :--- | :--- | :--- |
| `SIGNATURE_INVALID` | Mismatched secret or payload tampered in transit. | Verify `WORKER_HMAC_SECRET` in both Mac client and Windows `.env`. |
| `CLOCK_SKEW_DETECTED` | Windows NTP clock drift. | Resync Windows time: `w32tm /resync /force`. |
| `MT5_OFFLINE` | MT5 closed or restarted. | Restart `terminal64.exe` or restart Windows Worker service. |
| `SYMBOL_UNAVAILABLE` | Symbol not in `WORKER_ALLOWED_SYMBOLS` or not in MT5 MarketWatch. | Add symbol to MT5 MarketWatch and update `.env`. |
| `READ_ONLY_VIOLATION` | Non-allowlisted or trading action requested. | Inspect client request. Trader Machine prohibits trade execution. |

---

## 10. Windows Deployment Procedure (Exness DEMO)

1. **Provision Windows Host:** Launch Windows 10/11 or Windows Server.
2. **Install Exness MT5:** Install MetaTrader 5 and log into your **Exness DEMO** account. Uncheck "Save password" if preferred. Ensure EURUSD is added to Market Watch.
3. **Install Python 64-bit:** Install Python 3.11 or 3.12 (check "Add python.exe to PATH").
4. **Deploy Repository:** Clone `trader-machine` repository onto Windows host.
5. **Setup Virtual Environment:**
   ```cmd
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   pip install MetaTrader5
   ```
6. **Configure Secrets:** Copy `.env.example` to `.env` and set `WORKER_HMAC_SECRET`, `WORKER_ADAPTER_MODE=REAL`.
7. **Join Tailscale Mesh:** Install Tailscale on Windows and Mac. Note the Tailscale IP of Windows node and set `WORKER_BIND_HOST=100.x.y.z`.
8. **Run Pre-Flight Check:** Run `.\scripts\start_worker_windows.ps1 -CheckOnly`.
9. **Start Worker:** Run `.\scripts\start_worker_windows.ps1` or install as NSSM service.

---

## 11. Read-Only Guarantees & Static Safety Audit

Trader Machine Windows Worker V3 provides cryptographic and architectural read-only guarantees:
1. **Strict Action Allowlist:** Only 6 query commands exist. All other commands are rejected with `READ_ONLY_VIOLATION`.
2. **Zero Trading Routines:** Neither `core/worker/adapter.py`, `core/worker/worker.py`, nor `core/worker/main.py` contain any calls to:
   - `order_send`
   - `OrderSend`
   - `order_check`
   - `position_close`
   - `position_modify`
   - `order_modify`
3. **Automated Static Audit:** The worker includes `run_security_audit()` which scans every file in `core/worker` and `core/execution` to guarantee that zero trading calls exist. If any appear, the build and startup fail immediately.

---

## 12. Known Limitations

1. **Windows Dependency:** Real MT5 connectivity requires Windows OS and the 64-bit MetaTrader 5 desktop terminal. macOS development uses `MockMT5Adapter`.
2. **Historical Depth:** The worker provides real-time snapshot telemetry (ticks, quotes, terminal state). Deep multi-year historical bars are acquired via Dukascopy/TrueFX pipelines.
3. **No Execution:** This worker cannot open, modify, or close positions. Trade execution is deferred until out-of-sample forward testing is authorized.
