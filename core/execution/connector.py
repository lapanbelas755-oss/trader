"""MT5 Connector Interface and Read-Only Implementations.
Enforces a strict read-only firewall: blocks order_send, order_check, position_close, etc.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
import logging
import time
from typing import Any, Optional

from core.execution.contract import (
    AccountInfoReadOnly,
    SymbolInfoReadOnly,
    TerminalInfoReadOnly,
    TickReadOnly,
    TradingProhibitedError,
)

logger = logging.getLogger(__name__)


class IMT5Connector(ABC):
    """Abstract interface for MetaTrader 5 terminal connectivity (Read-Only)."""

    @abstractmethod
    def initialize(self, path: Optional[str] = None, timeout: int = 5000) -> bool:
        """Initialize connection to MT5 terminal."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Close connection to MT5 terminal."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connection is active."""
        pass

    @abstractmethod
    def get_terminal_info(self) -> Optional[TerminalInfoReadOnly]:
        """Fetch read-only terminal status."""
        pass

    @abstractmethod
    def get_account_info(self) -> Optional[AccountInfoReadOnly]:
        """Fetch read-only account equity and balance with masked credentials."""
        pass

    @abstractmethod
    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfoReadOnly]:
        """Fetch read-only symbol specifications."""
        pass

    @abstractmethod
    def get_tick(self, symbol: str) -> Optional[TickReadOnly]:
        """Fetch latest price tick for an instrument."""
        pass

    # HARD TRADING FIREWALL: Prohibit trading operations unconditionally
    def order_send(self, *args: Any, **kwargs: Any) -> Any:
        raise TradingProhibitedError("order_send is permanently disabled in Trader Machine V1 execution probe.")

    def order_check(self, *args: Any, **kwargs: Any) -> Any:
        raise TradingProhibitedError("order_check is permanently disabled in Trader Machine V1 execution probe.")

    def position_close(self, *args: Any, **kwargs: Any) -> Any:
        raise TradingProhibitedError("position_close is permanently disabled in Trader Machine V1 execution probe.")

    def position_modify(self, *args: Any, **kwargs: Any) -> Any:
        raise TradingProhibitedError("position_modify is permanently disabled in Trader Machine V1 execution probe.")

    def order_modify(self, *args: Any, **kwargs: Any) -> Any:
        raise TradingProhibitedError("order_modify is permanently disabled in Trader Machine V1 execution probe.")


class MT5ReadOnlyConnector(IMT5Connector):
    """Real MT5 terminal read-only connector using MetaTrader5 package if available."""

    def __init__(self) -> None:
        self._connected = False
        self._mt5: Optional[Any] = None

    def initialize(self, path: Optional[str] = None, timeout: int = 5000) -> bool:
        try:
            import MetaTrader5 as mt5_module
            self._mt5 = mt5_module
        except ImportError:
            logger.warning("MetaTrader5 python package is not installed or not available on this platform.")
            return False

        init_kwargs: dict[str, Any] = {"timeout": timeout}
        if path:
            init_kwargs["path"] = path

        success = self._mt5.initialize(**init_kwargs)
        self._connected = bool(success)
        return self._connected

    def shutdown(self) -> None:
        if self._mt5 and self._connected:
            try:
                self._mt5.shutdown()
            except Exception as e:
                logger.error(f"Error during MT5 shutdown: {e}")
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

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


class MockMT5Connector(IMT5Connector):
    """Hermetic mock connector for unit and integration testing without live MT5."""

    def __init__(
        self,
        can_initialize: bool = True,
        is_running: bool = True,
        symbols_available: Optional[list[str]] = None,
        mock_account: Optional[AccountInfoReadOnly] = None,
        mock_ticks: Optional[dict[str, TickReadOnly]] = None,
        simulated_latency_ms: float = 1.5,
    ) -> None:
        self.can_initialize = can_initialize
        self.is_running = is_running
        self.symbols_available = symbols_available if symbols_available is not None else ["EURUSD"]
        self.simulated_latency_ms = simulated_latency_ms
        self._connected = False

        self._account = mock_account or AccountInfoReadOnly(
            login_masked=AccountInfoReadOnly.mask_login("8829104"),
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
                last=Decimal("1.10006"),
                spread=Decimal("0.00012"),
                volume=Decimal("45"),
            )
        }

    def initialize(self, path: Optional[str] = None, timeout: int = 5000) -> bool:
        time.sleep(self.simulated_latency_ms / 1000.0)
        if not self.is_running or not self.can_initialize:
            self._connected = False
            return False
        self._connected = True
        return True

    def shutdown(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_terminal_info(self) -> Optional[TerminalInfoReadOnly]:
        if not self._connected:
            return None
        return TerminalInfoReadOnly(
            connected=True,
            trade_allowed=False,  # Read-only probe
            name="MetaTrader 5 Mock",
            path="/Applications/MetaTrader 5.app",
            data_path="/Users/mock/Library/Application Support/MetaTrader 5",
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
        spread = ask - bid
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
        time.sleep(self.simulated_latency_ms / 1000.0)
        if not self._connected or symbol not in self.symbols_available:
            return None
        return self._ticks.get(symbol)
