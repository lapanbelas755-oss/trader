<#
.SYNOPSIS
    Trader Machine — Windows MT5 Worker V3 Service Launcher
.DESCRIPTION
    Launches the read-only Windows MT5 Worker V3 daemon on Windows.
    Performs pre-flight checks, verifies Python environment, inspects MT5 process,
    runs automated security audit, and begins telemetry serving.
.NOTES
    DO NOT RUN ON MACOS / LINUX.
    Designed specifically for Windows 10/11 or Windows Server 2022.
#>

[CmdletBinding()]
param (
    [string]$EnvFile = ".env",
    [switch]$CheckOnly,
    [switch]$SkipAudit
)

$ErrorActionPreference = "Stop"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  TRADER MACHINE — WINDOWS MT5 WORKER V3 LAUNCHER      " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Verify Operating System
if ($PSVersionTable.PSEdition -ne "Desktop" -and $PSVersionTable.Platform -eq "Unix") {
    Write-Error "ERROR: This script must ONLY be executed on Windows OS. Aborting."
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "[1/6] Validating Project Root: $ProjectRoot" -ForegroundColor Green

# 2. Locate Python Environment
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$GlobalPython = (Get-Command python -ErrorAction SilentlyContinue).Source

if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    Write-Host "[2/6] Using virtual environment Python: $PythonExe" -ForegroundColor Green
} elseif ($GlobalPython) {
    $PythonExe = $GlobalPython
    Write-Host "[2/6] Using system Python: $PythonExe" -ForegroundColor Yellow
} else {
    Write-Error "ERROR: Python 3.10+ executable not found. Please setup .venv."
    exit 1
}

# 3. Verify Configuration File (.env)
$FullEnvPath = Join-Path $ProjectRoot $EnvFile
if (-not (Test-Path $FullEnvPath)) {
    Write-Error "ERROR: Configuration file '$FullEnvPath' does not exist. Copy .env.example to .env and configure secrets."
    exit 1
}
Write-Host "[3/6] Configuration file found: $FullEnvPath" -ForegroundColor Green

# 4. Check for MetaTrader 5 Terminal Process
$Mt5Process = Get-Process "terminal64" -ErrorAction SilentlyContinue
if ($Mt5Process) {
    Write-Host "[4/6] MetaTrader 5 terminal process detected (PID: $($Mt5Process.Id))." -ForegroundColor Green
} else {
    Write-Host "[4/6] WARNING: 'terminal64.exe' process not currently running. Worker will start in MT5_DISCONNECTED state." -ForegroundColor Yellow
}

# 5. Execute Pre-Flight Security Audit
if (-not $SkipAudit) {
    Write-Host "[5/6] Running automated static security audit..." -ForegroundColor Cyan
    & $PythonExe -m core.worker.main --audit
    if ($LASTEXITCODE -ne 0) {
        Write-Error "CRITICAL SECURITY AUDIT FAILED: Prohibited trading routines detected in codebase!"
        exit 1
    }
    Write-Host "       Security audit PASS: Zero executable trading paths confirmed." -ForegroundColor Green
} else {
    Write-Host "[5/6] Skipping security audit (--SkipAudit specified)." -ForegroundColor Yellow
}

# 6. Execute Diagnostics or Start Daemon
if ($CheckOnly) {
    Write-Host "[6/6] Running diagnostic environment inspection..." -ForegroundColor Cyan
    & $PythonExe -m core.worker.main --env-file $FullEnvPath --diagnostics
    Write-Host "Diagnostic inspection complete. Exiting (--CheckOnly specified)." -ForegroundColor Green
    exit 0
}

Write-Host "[6/6] Starting Windows MT5 Worker V3 Daemon..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop worker." -ForegroundColor DarkGray
Write-Host "--------------------------------------------------------" -ForegroundColor DarkGray

& $PythonExe -m core.worker.main --env-file $FullEnvPath
