"""Unit and integration tests for MT5 Read-Only Connectivity Probe V1.
All tests run hermetically with zero broker or live network connectivity.
"""
from datetime import datetime, timezone
from decimal import Decimal
import inspect
from pathlib import Path
from unittest.mock import patch
import pytest

from core.execution.connector import (
    IMT5Connector,
    MockMT5Connector,
    MT5ReadOnlyConnector,
)
from core.execution.contract import (
    AccountInfoReadOnly,
    ConnectivityStatus,
    PlatformInfo,
    ProbeReport,
    SymbolInfoReadOnly,
    TerminalInfoReadOnly,
    TickReadOnly,
    TradingProhibitedError,
)
from core.execution.mt5_probe import MT5ConnectivityProbe


# 1. Connector interface
def test_connector_interface():
    # Verify that IMT5Connector defines required read-only methods
    abstract_methods = IMT5Connector.__abstractmethods__
    expected = {
        "initialize",
        "shutdown",
        "is_connected",
        "get_terminal_info",
        "get_account_info",
        "get_symbol_info",
        "get_tick",
    }
    assert expected.issubset(abstract_methods)


# 2. Unavailable MT5
def test_unavailable_mt5():
    with patch.object(MT5ConnectivityProbe, "detect_platform") as mock_plat, \
         patch.object(MT5ConnectivityProbe, "is_package_available", return_value=True), \
         patch.object(MT5ConnectivityProbe, "find_terminal_path", return_value=None), \
         patch.object(MT5ConnectivityProbe, "is_terminal_running", return_value=False):

        mock_plat.return_value = PlatformInfo(
            system="Windows",
            os_name="Windows",
            os_version="11",
            architecture="x86_64",
            python_version="3.12.0",
            is_apple_silicon=False,
            is_windows=True,
            is_natively_supported=True,
            notes="Windows test",
        )

        report = MT5ConnectivityProbe.probe()
        assert report.status == ConnectivityStatus.MT5_NOT_INSTALLED
        assert not report.mt5_installed
        assert "MT5_NOT_INSTALLED" in report.errors[0]


# 3. Unavailable Python package
def test_unavailable_python_package():
    with patch.object(MT5ConnectivityProbe, "is_package_available", return_value=False):
        report = MT5ConnectivityProbe.probe(prefer_package_status=True)
        assert report.status == ConnectivityStatus.PYTHON_PACKAGE_UNAVAILABLE
        assert not report.mt5_package_available
        assert "PACKAGE_NOT_AVAILABLE" in report.errors[0]


# 4. Terminal not running
def test_terminal_not_running():
    with patch.object(MT5ConnectivityProbe, "detect_platform") as mock_plat, \
         patch.object(MT5ConnectivityProbe, "is_package_available", return_value=True), \
         patch.object(MT5ConnectivityProbe, "find_terminal_path", return_value="/opt/mt5/terminal64.exe"), \
         patch.object(MT5ConnectivityProbe, "is_terminal_running", return_value=False):

        mock_plat.return_value = PlatformInfo(
            system="Windows",
            os_name="Windows",
            os_version="11",
            architecture="x86_64",
            python_version="3.12.0",
            is_apple_silicon=False,
            is_windows=True,
            is_natively_supported=True,
            notes="Windows test",
        )

        report = MT5ConnectivityProbe.probe()
        assert report.status == ConnectivityStatus.MT5_NOT_RUNNING
        assert report.mt5_installed
        assert not report.mt5_running
        assert "MT5_NOT_RUNNING" in report.errors[0]


# 5. Successful mock connection
def test_successful_mock_connection():
    mock_conn = MockMT5Connector(can_initialize=True, is_running=True)
    report = MT5ConnectivityProbe.probe(connector=mock_conn, target_symbol="EURUSD")

    assert report.status == ConnectivityStatus.CONNECTED_READ_ONLY
    assert report.terminal_info is not None
    assert report.terminal_info.connected is True
    assert report.account_info is not None
    assert report.account_info.balance == Decimal("10000.00")
    assert report.symbol_info is not None
    assert report.symbol_info.name == "EURUSD"
    assert report.tick_info is not None
    assert report.tick_info.symbol == "EURUSD"
    assert report.connection_latency_ms is not None
    assert report.tick_latency_ms is not None
    assert len(report.errors) == 0


# 6. EURUSD unavailable
def test_eurusd_unavailable():
    # Mock connector where EURUSD is not in symbols_available
    mock_conn = MockMT5Connector(can_initialize=True, is_running=True, symbols_available=["GBPUSD"])
    report = MT5ConnectivityProbe.probe(connector=mock_conn, target_symbol="EURUSD")

    assert report.status == ConnectivityStatus.SYMBOL_UNAVAILABLE
    assert report.symbol_info is None
    assert any("SYMBOL_UNAVAILABLE" in e for e in report.errors)


# 7. Tick parsing
def test_tick_parsing():
    now_utc = datetime(2026, 7, 1, 14, 30, 0, tzinfo=timezone.utc)
    tick = TickReadOnly(
        symbol="EURUSD",
        time=now_utc,
        bid=Decimal("1.14120"),
        ask=Decimal("1.14132"),
        last=Decimal("1.14125"),
        spread=Decimal("0.00012"),
        volume=Decimal("120"),
    )
    assert tick.symbol == "EURUSD"
    assert tick.time.tzinfo == timezone.utc
    assert tick.bid == Decimal("1.14120")
    assert tick.ask == Decimal("1.14132")
    assert tick.last == Decimal("1.14125")
    assert tick.spread == Decimal("0.00012")
    assert tick.volume == Decimal("120")


# 8. Bid/Ask extraction
def test_bid_ask_extraction():
    mock_conn = MockMT5Connector()
    assert mock_conn.initialize() is True
    tick = mock_conn.get_tick("EURUSD")
    assert tick is not None
    assert tick.bid > Decimal("0")
    assert tick.ask > Decimal("0")
    assert tick.ask >= tick.bid


# 9. Spread calculation
def test_spread_calculation():
    mock_conn = MockMT5Connector()
    assert mock_conn.initialize() is True
    sym = mock_conn.get_symbol_info("EURUSD")
    assert sym is not None
    expected_spread = sym.ask - sym.bid
    assert sym.spread == expected_spread
    assert sym.spread >= Decimal("0")


# 10. No-trade enforcement (CRITICAL SAFETY TEST)
def test_no_trade_enforcement():
    connectors: list[IMT5Connector] = [MockMT5Connector(), MT5ReadOnlyConnector()]

    for conn in connectors:
        with pytest.raises(TradingProhibitedError, match="order_send is permanently disabled"):
            conn.order_send()

        with pytest.raises(TradingProhibitedError, match="order_check is permanently disabled"):
            conn.order_check()

        with pytest.raises(TradingProhibitedError, match="position_close is permanently disabled"):
            conn.position_close()

        with pytest.raises(TradingProhibitedError, match="position_modify is permanently disabled"):
            conn.position_modify()

        with pytest.raises(TradingProhibitedError, match="order_modify is permanently disabled"):
            conn.order_modify()


# 11. Credential redaction
def test_credential_redaction():
    masked_1 = AccountInfoReadOnly.mask_login("8829104")
    assert masked_1 == "882****"
    assert "8829104" not in masked_1

    masked_short = AccountInfoReadOnly.mask_login("12")
    assert masked_short == "***"

    # Verify AccountInfoReadOnly requires login_masked and has no password field
    fields = AccountInfoReadOnly.model_fields.keys()
    assert "login_masked" in fields
    assert "password" not in fields
    assert "api_key" not in fields
    assert "token" not in fields


# 12. Platform detection
def test_platform_detection():
    plat = MT5ConnectivityProbe.detect_platform()
    assert plat.system in ("Darwin", "Linux", "Windows")
    assert plat.python_version.startswith("3.")

    if plat.system == "Darwin":
        assert plat.os_name == "macOS"
        if plat.architecture == "arm64":
            assert plat.is_apple_silicon is True
            assert plat.is_natively_supported is False
            assert "Apple Silicon" in plat.notes


# 13. Source code safety audit
def test_source_code_safety_audit():
    execution_dir = Path(__file__).parent.parent / "core" / "execution"
    for py_file in execution_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        # Ensure no active live order execution
        assert "mt5.order_send(" not in content, f"Forbidden order_send call in {py_file.name}"
        assert "mt5.OrderSend(" not in content, f"Forbidden OrderSend call in {py_file.name}"
