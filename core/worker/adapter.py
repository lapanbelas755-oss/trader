"""Windows MT5 Worker V3 — Adapter Interface and Implementations.
Defines IMT5Adapter, MockMT5Adapter (for local/Mac hermetic testing), and RealMT5Adapter (for Windows).
Strictly read-only: contains zero order execution routines.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import logging
import platform
import time
from typing import Any, Optional

from core.execution.contract import (
    AccountInfoReadOnly,
    SymbolInfoReadOnly,
    TerminalInfoReadOnly,
    TickReadOnly,
)
from core.execution.remote_protocol import PositionReadOnly

logger = logging.getLogger(__name__)


class MT5ConnectionState(str, Enum):
    """Explicit connection states for MT5 terminal."""
    MT5_CONNECTED = "MT5_CONNECTED"
    MT5_DISCONNECTED = "MT5_DISCONNECTED"
    MT5_NOT_INSTALLED = "MT5_NOT_INSTALLED"
    MT5_INITIALIZATION_FAILED = "MT5_INITIALIZATION_FAILED"


class IMT5Adapter(ABC):
    """Abstract interface for MT5 telemetry adapter.
    Contains strictly read-only observation queries.
    """

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize connection to local MT5 terminal."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Safely disconnect and release MT5 terminal resources."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if terminal connection is currently active."""
        pass

    @abstractmethod
    def get_connection_state(self) -> MT5ConnectionState:
        """Return the current MT5ConnectionState enum."""
        pass

    @abstractmethod
    def get_terminal_info(self) -> Optional[TerminalInfoReadOnly]:
        """Query read-only terminal build, status, and environment."""
        pass

    @abstractmethod
    def get_account_info(self) -> Optional[AccountInfoReadOnly]:
        """Query read-only account equity, balance, and margin with masked login."""
        pass

    @abstractmethod
    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfoReadOnly]:
        """Query read-only instrument specification and current quote."""
        pass

    @abstractmethod
    def get_tick(self, symbol: str) -> Optional[TickReadOnly]:
        """Query latest price tick for an instrument."""
        pass

    @abstractmethod
    def get_positions(self, symbol: Optional[str] = None) -> list[PositionReadOnly]:
        """Query current open positions."""
        pass

    @abstractmethod
    def get_historical_rates(self, symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        """Query historical OHLC rates for a specific timeframe."""
        pass


class MockMT5Adapter(IMT5Adapter):
    """Hermetic mock MT5 adapter for macOS Apple Silicon and automated CI testing.
    Never connects to network or external processes.
    """

    def __init__(
        self,
        initial_state: MT5ConnectionState = MT5ConnectionState.MT5_CONNECTED,
        symbols_available: Optional[list[str]] = None,
        mock_account: Optional[AccountInfoReadOnly] = None,
        mock_ticks: Optional[dict[str, TickReadOnly]] = None,
        mock_positions: Optional[list[PositionReadOnly]] = None,
    ) -> None:
        self._state = initial_state
        self._connected = (initial_state == MT5ConnectionState.MT5_CONNECTED)
        self.symbols_available = symbols_available if symbols_available is not None else ["EURUSD"]

        self._account = mock_account or AccountInfoReadOnly(
            login_masked="882***",
            server="Exness-Demo",
            currency="USD",
            balance=Decimal("10000.00"),
            equity=Decimal("10000.00"),
            margin=Decimal("0.00"),
            margin_free=Decimal("10000.00"),
            margin_level=Decimal("0.00"),
            leverage=100,
            trade_allowed=False,
            trade_mode="DEMO",
        )

        self._ticks = mock_ticks or {
            "EURUSD": TickReadOnly(
                symbol="EURUSD",
                time=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
                bid=Decimal("1.10000"),
                ask=Decimal("1.10012"),
                last=None,
                spread=Decimal("0.00012"),
                volume=Decimal("45"),
            )
        }

        self._positions = mock_positions or [
            PositionReadOnly(
                ticket=1001,
                symbol="EURUSD",
                type="BUY",
                volume=Decimal("0.10"),
                price_open=Decimal("1.09800"),
                sl=Decimal("1.09500"),
                tp=Decimal("1.10400"),
                price_current=Decimal("1.10000"),
                profit=Decimal("20.00"),
                time=datetime(2026, 7, 1, 10, 30, 0, tzinfo=timezone.utc),
            )
        ]

    def set_state(self, state: MT5ConnectionState) -> None:
        """Update mock state for testing failure scenarios."""
        self._state = state
        self._connected = (state == MT5ConnectionState.MT5_CONNECTED)

    def initialize(self) -> bool:
        if self._state == MT5ConnectionState.MT5_INITIALIZATION_FAILED:
            self._connected = False
            return False
        if self._state == MT5ConnectionState.MT5_NOT_INSTALLED:
            self._connected = False
            return False
        self._state = MT5ConnectionState.MT5_CONNECTED
        self._connected = True
        return True

    def shutdown(self) -> None:
        self._connected = False
        self._state = MT5ConnectionState.MT5_DISCONNECTED

    def is_connected(self) -> bool:
        return self._connected

    def get_connection_state(self) -> MT5ConnectionState:
        return self._state

    def get_terminal_info(self) -> Optional[TerminalInfoReadOnly]:
        if not self._connected:
            return None
        return TerminalInfoReadOnly(
            connected=True,
            trade_allowed=False,
            name="MetaTrader 5 Mock",
            path="C:\\Program Files\\MetaTrader 5\\terminal64.exe",
            data_path="C:\\Users\\Mock\\AppData\\Roaming\\MetaQuotes\\Terminal",
            company="MetaQuotes Software Corp.",
            version="5.00",
            build=4200,
        )

    def get_account_info(self) -> Optional[AccountInfoReadOnly]:
        if not self._connected:
            return None
        return self._account

    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfoReadOnly]:
        if not self._connected or symbol not in self.symbols_available:
            return None
        tick = self._ticks.get(symbol)
        bid = tick.bid if tick else Decimal("1.10000")
        ask = tick.ask if tick else Decimal("1.10012")
        spread = ask - bid if ask >= bid else Decimal("0")
        return SymbolInfoReadOnly(
            name=symbol,
            visible=True,
            bid=bid,
            ask=ask,
            spread=spread,
            digits=5,
            point=Decimal("0.00001"),
            trade_mode=0,
        )

    def get_tick(self, symbol: str) -> Optional[TickReadOnly]:
        if not self._connected or symbol not in self.symbols_available:
            return None
        return self._ticks.get(symbol)

    def get_positions(self, symbol: Optional[str] = None) -> list[PositionReadOnly]:
        if not self._connected:
            return []
        if symbol:
            return [p for p in self._positions if p.symbol == symbol]
        return list(self._positions)

    def get_historical_rates(self, symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        if not self._connected or symbol not in self.symbols_available:
            return []
        # Return mock historical data
        now = datetime.now(timezone.utc)
        rates = []
        for i in range(count):
            t = datetime.fromtimestamp(now.timestamp() - (count - i) * 300, tz=timezone.utc)
            rates.append({
                "timestamp": t,
                "open": Decimal("1.10000"),
                "high": Decimal("1.10100"),
                "low": Decimal("1.09900"),
                "close": Decimal("1.10050"),
                "tick_volume": 100,
                "spread": 12,
            })
        return rates


class RealMT5Adapter(IMT5Adapter):
    """Production MT5 adapter for Windows environments utilizing MetaTrader5 Python package.
    Never silently falls back to mock mode.
    On non-Windows platforms, cleanly marks MT5_NOT_INSTALLED.
    """

    def __init__(
        self,
        path: Optional[str] = None,
        server: Optional[str] = None,
        login: Optional[int] = None,
        password: Optional[str] = None,
        timeout_ms: int = 5000,
    ) -> None:
        self._path = path
        self._server = server
        self._login = login
        self._password = password
        self._timeout_ms = timeout_ms
        self._state = MT5ConnectionState.MT5_DISCONNECTED
        self._connected = False
        self._mt5: Optional[Any] = None

    def initialize(self) -> bool:
        # Step 1: Detect Operating System
        if platform.system() != "Windows":
            logger.info("RealMT5Adapter requires Windows OS. Current OS: %s", platform.system())
            self._state = MT5ConnectionState.MT5_NOT_INSTALLED
            self._connected = False
            return False

        # Step 2: Try importing official MetaTrader5 package
        try:
            import MetaTrader5 as mt5_module
            self._mt5 = mt5_module
        except ImportError:
            logger.warning("MetaTrader5 python package is not installed.")
            self._state = MT5ConnectionState.MT5_NOT_INSTALLED
            self._connected = False
            return False

        # Step 3: Initialize MT5 terminal
        init_kwargs: dict[str, Any] = {"timeout": self._timeout_ms}
        if self._path:
            init_kwargs["path"] = self._path
        if self._server:
            init_kwargs["server"] = self._server
        if self._login:
            init_kwargs["login"] = self._login
        if self._password:
            init_kwargs["password"] = self._password

        try:
            success = self._mt5.initialize(**init_kwargs)
            if success:
                self._state = MT5ConnectionState.MT5_CONNECTED
                self._connected = True
                logger.info("RealMT5Adapter successfully connected to MT5 terminal.")
                return True
            else:
                err = self._mt5.last_error()
                logger.error("RealMT5Adapter initialize failed with error: %s", err)
                self._state = MT5ConnectionState.MT5_INITIALIZATION_FAILED
                self._connected = False
                return False
        except Exception as e:
            logger.error("Exception during RealMT5Adapter initialize: %s", e)
            self._state = MT5ConnectionState.MT5_INITIALIZATION_FAILED
            self._connected = False
            return False

    def shutdown(self) -> None:
        if self._mt5 and self._connected:
            try:
                self._mt5.shutdown()
            except Exception as e:
                logger.error("Exception during RealMT5Adapter shutdown: %s", e)
        self._connected = False
        self._state = MT5ConnectionState.MT5_DISCONNECTED

    def is_connected(self) -> bool:
        return self._connected

    def get_connection_state(self) -> MT5ConnectionState:
        return self._state

    def get_terminal_info(self) -> Optional[TerminalInfoReadOnly]:
        if not self._connected or not self._mt5:
            return None
        info = self._mt5.terminal_info()
        if not info:
            return None
        return TerminalInfoReadOnly(
            connected=bool(getattr(info, "connected", False)),
            trade_allowed=bool(getattr(info, "trade_allowed", False)),
            name=str(getattr(info, "name", "MetaTrader 5")),
            path=str(getattr(info, "path", "")),
            data_path=str(getattr(info, "data_path", "")),
            company=str(getattr(info, "company", "")),
            version=str(getattr(info, "version", "")),
            build=int(getattr(info, "build", 0)),
        )

    def get_account_info(self) -> Optional[AccountInfoReadOnly]:
        if not self._connected or not self._mt5:
            return None
        acc = self._mt5.account_info()
        if not acc:
            return None
        raw_login = getattr(acc, "login", 0)
        return AccountInfoReadOnly(
            login_masked=AccountInfoReadOnly.mask_login(raw_login),
            server=str(getattr(acc, "server", "UNKNOWN")),
            currency=str(getattr(acc, "currency", "USD")),
            balance=Decimal(str(getattr(acc, "balance", 0))),
            equity=Decimal(str(getattr(acc, "equity", 0))),
            margin=Decimal(str(getattr(acc, "margin", 0))),
            margin_free=Decimal(str(getattr(acc, "margin_free", 0))),
            margin_level=Decimal(str(getattr(acc, "margin_level", 0))) if getattr(acc, "margin_level", None) is not None else None,
            leverage=int(getattr(acc, "leverage", 1)),
            trade_allowed=bool(getattr(acc, "trade_allowed", False)),
            trade_mode="DEMO" if getattr(acc, "trade_mode", 0) == 0 else "REAL",
        )

    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfoReadOnly]:
        if not self._connected or not self._mt5:
            return None
        sym = self._mt5.symbol_info(symbol)
        if not sym:
            return None
        bid = Decimal(str(getattr(sym, "bid", 0)))
        ask = Decimal(str(getattr(sym, "ask", 0)))
        spread = ask - bid if ask >= bid else Decimal("0")
        return SymbolInfoReadOnly(
            name=str(getattr(sym, "name", symbol)),
            visible=bool(getattr(sym, "visible", False)),
            bid=bid,
            ask=ask,
            spread=spread,
            digits=int(getattr(sym, "digits", 5)),
            point=Decimal(str(getattr(sym, "point", "0.00001"))),
            trade_mode=int(getattr(sym, "trade_mode", 0)),
        )

    def get_tick(self, symbol: str) -> Optional[TickReadOnly]:
        if not self._connected or not self._mt5:
            return None
        tick = self._mt5.symbol_info_tick(symbol)
        if not tick:
            return None
        bid = Decimal(str(getattr(tick, "bid", 0)))
        ask = Decimal(str(getattr(tick, "ask", 0)))
        last_val = getattr(tick, "last", None)
        last_dec = Decimal(str(last_val)) if last_val is not None and last_val > 0 else None
        spread = ask - bid if ask >= bid else Decimal("0")
        epoch_sec = getattr(tick, "time", None)
        if epoch_sec is not None:
            t = datetime.fromtimestamp(epoch_sec, tz=timezone.utc)
        else:
            t = datetime.now(timezone.utc)
        vol = Decimal(str(getattr(tick, "volume", 0)))
        return TickReadOnly(
            symbol=symbol,
            time=t,
            bid=bid,
            ask=ask,
            last=last_dec,
            spread=spread,
            volume=vol,
        )

    def get_positions(self, symbol: Optional[str] = None) -> list[PositionReadOnly]:
        if not self._connected or not self._mt5:
            return []
        raw_positions = self._mt5.positions_get(symbol=symbol) if symbol else self._mt5.positions_get()
        if not raw_positions:
            return []

        results = []
        for pos in raw_positions:
            pos_type = "BUY" if getattr(pos, "type", 0) == 0 else "SELL"
            epoch_sec = getattr(pos, "time", None)
            pos_time = datetime.fromtimestamp(epoch_sec, tz=timezone.utc) if epoch_sec else datetime.now(timezone.utc)
            sl_val = getattr(pos, "sl", None)
            tp_val = getattr(pos, "tp", None)
            results.append(
                PositionReadOnly(
                    ticket=int(getattr(pos, "ticket", 0)),
                    symbol=str(getattr(pos, "symbol", "")),
                    type=pos_type,
                    volume=Decimal(str(getattr(pos, "volume", 0))),
                    price_open=Decimal(str(getattr(pos, "price_open", 0))),
                    sl=Decimal(str(sl_val)) if sl_val is not None and sl_val > 0 else None,
                    tp=Decimal(str(tp_val)) if tp_val is not None and tp_val > 0 else None,
                    price_current=Decimal(str(getattr(pos, "price_current", 0))),
                    profit=Decimal(str(getattr(pos, "profit", 0))),
                    time=pos_time,
                )
            )
        return results

    def get_historical_rates(self, symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        if not self._connected or not self._mt5:
            return []
        
        # Map timeframe string to MT5 constant
        tf_map = {
            "M1": self._mt5.TIMEFRAME_M1,
            "M5": self._mt5.TIMEFRAME_M5,
            "M15": self._mt5.TIMEFRAME_M15,
            "H1": self._mt5.TIMEFRAME_H1,
            "H4": self._mt5.TIMEFRAME_H4,
            "D1": self._mt5.TIMEFRAME_D1,
        }
        mt5_tf = tf_map.get(timeframe.upper())
        if mt5_tf is None:
            logger.error("Unsupported timeframe %s for get_historical_rates", timeframe)
            return []
            
        rates = self._mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
        if rates is None or len(rates) == 0:
            logger.error("Failed to fetch rates for %s %s. Check symbol and terminal data.", symbol, timeframe)
            return []
            
        results = []
        for r in rates:
            dt = datetime.fromtimestamp(int(r['time']), tz=timezone.utc)
            results.append({
                "timestamp": dt,
                "open": Decimal(str(r['open'])),
                "high": Decimal(str(r['high'])),
                "low": Decimal(str(r['low'])),
                "close": Decimal(str(r['close'])),
                "tick_volume": int(r['tick_volume']),
                "spread": int(r['spread']),
            })
        return results
