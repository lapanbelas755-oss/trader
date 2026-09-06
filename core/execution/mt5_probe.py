"""MT5 Connectivity Probe V1.
Executes non-invasive, strictly read-only diagnostics of MetaTrader 5 on the local system.
Detects macOS Apple Silicon architecture, Python package availability, terminal status,
and measures read-only query latency without placing any orders.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Optional

from core.execution.connector import IMT5Connector, MT5ReadOnlyConnector
from core.execution.contract import (
    AccountInfoReadOnly,
    ConnectivityStatus,
    PlatformInfo,
    ProbeReport,
    SymbolInfoReadOnly,
    TerminalInfoReadOnly,
    TickReadOnly,
)

COMMON_MAC_MT5_PATHS = [
    Path("/Applications/MetaTrader 5.app"),
    Path("/Applications/Exness MetaTrader 5.app"),
    Path("/Applications/MetaTrader 5 Terminal.app"),
    Path.home() / "Applications" / "MetaTrader 5.app",
]


class MT5ConnectivityProbe:
    """Safe, read-only connectivity and diagnostic probe for MetaTrader 5."""

    @staticmethod
    def detect_platform() -> PlatformInfo:
        """Detect operating system, CPU architecture, and MT5 native compatibility."""
        system_name = platform.system()
        machine = platform.machine()
        version_str = platform.release()
        py_ver = platform.python_version()

        is_apple_silicon = (system_name == "Darwin" and machine == "arm64")
        is_windows = (system_name == "Windows")
        # MetaQuotes official MetaTrader5 Python package only ships pre-compiled wheels for Windows
        is_natively_supported = is_windows

        if is_apple_silicon:
            notes = (
                "macOS Apple Silicon (Darwin arm64) detected. "
                "The official MetaTrader5 Python package from MetaQuotes is compiled only for Windows (x86_64 DLL). "
                "Native Python-to-MT5 terminal IPC is not natively supported on macOS."
            )
        elif system_name == "Darwin":
            notes = (
                "macOS Intel (Darwin x86_64) detected. "
                "MetaTrader5 Python package is Windows-native only."
            )
        elif is_windows:
            notes = "Windows platform detected. MetaTrader5 Python package is natively supported."
        else:
            notes = f"{system_name} platform detected. MetaTrader5 Python package requires Windows or an IPC bridge."

        return PlatformInfo(
            system=system_name,
            os_name="macOS" if system_name == "Darwin" else system_name,
            os_version=version_str,
            architecture=machine,
            python_version=py_ver,
            is_apple_silicon=is_apple_silicon,
            is_windows=is_windows,
            is_natively_supported=is_natively_supported,
            notes=notes,
        )

    @staticmethod
    def is_package_available() -> bool:
        """Check if the MetaTrader5 Python package can be imported."""
        try:
            import MetaTrader5  # noqa: F401
            return True
        except ImportError:
            return False

    @classmethod
    def find_terminal_path(cls, custom_path: Optional[str] = None) -> Optional[str]:
        """Locate an installed MetaTrader 5 terminal executable or application bundle."""
        if custom_path and Path(custom_path).exists():
            return str(Path(custom_path).resolve())

        for p in COMMON_MAC_MT5_PATHS:
            if p.exists():
                return str(p.resolve())

        return None

    @staticmethod
    def is_terminal_running() -> bool:
        """Check if an MT5 terminal process is currently active."""
        system_name = platform.system()
        try:
            if system_name == "Darwin":
                # Check for metatrader or terminal processes on macOS
                cmd = ["pgrep", "-if", "metatrader|terminal64|metatrader 5"]
                res = subprocess.run(cmd, capture_output=True, text=True)
                return res.returncode == 0 and bool(res.stdout.strip())
            elif system_name == "Windows":
                cmd = ["tasklist", "/FI", "IMAGENAME eq terminal64.exe"]
                res = subprocess.run(cmd, capture_output=True, text=True)
                return "terminal64.exe" in res.stdout
            else:
                cmd = ["pgrep", "-i", "terminal64"]
                res = subprocess.run(cmd, capture_output=True, text=True)
                return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def probe(
        cls,
        connector: Optional[IMT5Connector] = None,
        target_symbol: str = "EURUSD",
        terminal_path: Optional[str] = None,
        prefer_package_status: bool = False,
    ) -> ProbeReport:
        """Execute non-invasive read-only connectivity test and compile diagnostic report."""
        platform_info = cls.detect_platform()
        pkg_available = cls.is_package_available()
        discovered_path = cls.find_terminal_path(terminal_path)
        is_installed = discovered_path is not None
        is_running = cls.is_terminal_running()

        errors: list[str] = []

        # 1. Evaluate environment if using live connector
        if connector is None:
            if not platform_info.is_natively_supported and not prefer_package_status:
                errors.append(
                    f"PLATFORM_INCOMPATIBLE: {platform_info.os_name} ({platform_info.architecture}) "
                    "cannot run Windows-native MetaTrader5 C-extension. Package is unavailable on this OS."
                )
                return ProbeReport(
                    status=ConnectivityStatus.PLATFORM_INCOMPATIBLE,
                    platform=platform_info,
                    mt5_package_available=pkg_available,
                    mt5_installed=is_installed,
                    mt5_running=is_running,
                    terminal_path=discovered_path,
                    errors=errors,
                )

            if not pkg_available:
                errors.append(
                    "PACKAGE_NOT_AVAILABLE: MetaTrader5 python package is not installed or importable."
                )
                return ProbeReport(
                    status=ConnectivityStatus.PYTHON_PACKAGE_UNAVAILABLE,
                    platform=platform_info,
                    mt5_package_available=False,
                    mt5_installed=is_installed,
                    mt5_running=is_running,
                    terminal_path=discovered_path,
                    errors=errors,
                )

            if not is_installed:
                errors.append("MT5_NOT_INSTALLED: No MetaTrader 5 terminal application found at standard locations.")
                return ProbeReport(
                    status=ConnectivityStatus.MT5_NOT_INSTALLED,
                    platform=platform_info,
                    mt5_package_available=True,
                    mt5_installed=False,
                    mt5_running=is_running,
                    terminal_path=discovered_path,
                    errors=errors,
                )

            if not is_running:
                errors.append("MT5_NOT_RUNNING: MetaTrader 5 terminal is installed but not currently executing.")
                return ProbeReport(
                    status=ConnectivityStatus.MT5_NOT_RUNNING,
                    platform=platform_info,
                    mt5_package_available=True,
                    mt5_installed=True,
                    mt5_running=False,
                    terminal_path=discovered_path,
                    errors=errors,
                )

            # Instantiation of real connector
            active_connector = MT5ReadOnlyConnector()
        else:
            active_connector = connector

        # 2. Attempt Connection
        start_conn = time.perf_counter()
        connected = active_connector.initialize(path=discovered_path)
        conn_latency_ms = (time.perf_counter() - start_conn) * 1000.0

        if not connected:
            errors.append("CONNECTION_ERROR: Failed to establish IPC connection with MetaTrader 5 terminal.")
            return ProbeReport(
                status=ConnectivityStatus.CONNECTION_ERROR,
                platform=platform_info,
                mt5_package_available=pkg_available or (connector is not None),
                mt5_installed=is_installed or (connector is not None),
                mt5_running=is_running or (connector is not None),
                terminal_path=discovered_path,
                connection_latency_ms=conn_latency_ms,
                errors=errors,
            )

        try:
            # 3. Read Terminal Info
            term_info = active_connector.get_terminal_info()

            # 4. Read Account Info (read-only, masked)
            acc_info = active_connector.get_account_info()

            # 5. Check Target Symbol (EURUSD)
            sym_info = active_connector.get_symbol_info(target_symbol)
            if not sym_info or not sym_info.visible:
                errors.append(f"SYMBOL_UNAVAILABLE: Symbol '{target_symbol}' is not visible or unavailable in terminal.")
                return ProbeReport(
                    status=ConnectivityStatus.SYMBOL_UNAVAILABLE,
                    platform=platform_info,
                    mt5_package_available=True,
                    mt5_installed=True,
                    mt5_running=True,
                    terminal_path=discovered_path,
                    terminal_info=term_info,
                    account_info=acc_info,
                    symbol_info=sym_info,
                    connection_latency_ms=conn_latency_ms,
                    errors=errors,
                )

            # 6. Read Latest Tick (Bid, Ask, Spread)
            start_tick = time.perf_counter()
            tick_info = active_connector.get_tick(target_symbol)
            tick_latency_ms = (time.perf_counter() - start_tick) * 1000.0

            if not tick_info:
                errors.append(f"SYMBOL_UNAVAILABLE: Unable to retrieve current price tick for '{target_symbol}'.")
                return ProbeReport(
                    status=ConnectivityStatus.SYMBOL_UNAVAILABLE,
                    platform=platform_info,
                    mt5_package_available=True,
                    mt5_installed=True,
                    mt5_running=True,
                    terminal_path=discovered_path,
                    terminal_info=term_info,
                    account_info=acc_info,
                    symbol_info=sym_info,
                    connection_latency_ms=conn_latency_ms,
                    tick_latency_ms=tick_latency_ms,
                    errors=errors,
                )

            return ProbeReport(
                status=ConnectivityStatus.CONNECTED_READ_ONLY,
                platform=platform_info,
                mt5_package_available=True,
                mt5_installed=True,
                mt5_running=True,
                terminal_path=discovered_path,
                terminal_info=term_info,
                account_info=acc_info,
                symbol_info=sym_info,
                tick_info=tick_info,
                connection_latency_ms=conn_latency_ms,
                tick_latency_ms=tick_latency_ms,
                errors=errors,
            )
        finally:
            active_connector.shutdown()
