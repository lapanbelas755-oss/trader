"""Explicit column and field mappings for external raw market data sources.
Prevents silent guesswork or ambiguous column resolution.
"""
from dataclasses import dataclass, field
from typing import Any, Optional
from core.data_source.contract import MarketDataType


class MappingError(ValueError):
    """Raised when column mapping is incomplete, ambiguous, or invalid."""
    pass


@dataclass(frozen=True)
class SourceColumnMapping:
    """Explicit mapping definition from source field names to canonical names."""
    data_type: MarketDataType
    timestamp_col: Optional[str] = None
    date_col: Optional[str] = None
    time_col: Optional[str] = None
    symbol_col: Optional[str] = None
    # OHLC fields
    open_col: Optional[str] = None
    high_col: Optional[str] = None
    low_col: Optional[str] = None
    close_col: Optional[str] = None
    volume_col: Optional[str] = None
    spread_col: Optional[str] = None
    # Tick fields
    bid_col: Optional[str] = None
    ask_col: Optional[str] = None
    last_col: Optional[str] = None

    def validate_schema(self, available_columns: set[str]) -> None:
        """Validate that all mapped source columns exist in available columns."""
        # Check timestamp
        if not self.timestamp_col and not (self.date_col and self.time_col):
            raise MappingError("Either 'timestamp_col' or both 'date_col' and 'time_col' must be specified.")

        if self.timestamp_col and self.timestamp_col not in available_columns:
            raise MappingError(f"Required timestamp column '{self.timestamp_col}' not found in source.")
        if self.date_col and self.date_col not in available_columns:
            raise MappingError(f"Required date column '{self.date_col}' not found in source.")
        if self.time_col and self.time_col not in available_columns:
            raise MappingError(f"Required time column '{self.time_col}' not found in source.")

        if self.symbol_col and self.symbol_col not in available_columns:
            raise MappingError(f"Specified symbol column '{self.symbol_col}' not found in source.")

        if self.data_type == MarketDataType.OHLC:
            required = {
                "open_col": self.open_col,
                "high_col": self.high_col,
                "low_col": self.low_col,
                "close_col": self.close_col,
            }
            for name, col in required.items():
                if not col:
                    raise MappingError(f"OHLC data requires mapping for '{name}'.")
                if col not in available_columns:
                    raise MappingError(f"Required OHLC column '{col}' not found in source columns: {available_columns}")

            if self.volume_col and self.volume_col not in available_columns:
                raise MappingError(f"Specified volume column '{self.volume_col}' not found in source.")
            if self.spread_col and self.spread_col not in available_columns:
                raise MappingError(f"Specified spread column '{self.spread_col}' not found in source.")

        elif self.data_type == MarketDataType.TICK:
            if not self.bid_col or self.bid_col not in available_columns:
                raise MappingError(f"Required bid column '{self.bid_col}' not found in source.")
            if not self.ask_col or self.ask_col not in available_columns:
                raise MappingError(f"Required ask column '{self.ask_col}' not found in source.")
            if self.last_col and self.last_col not in available_columns:
                raise MappingError(f"Specified last column '{self.last_col}' not found in source.")
            if self.volume_col and self.volume_col not in available_columns:
                raise MappingError(f"Specified volume column '{self.volume_col}' not found in source.")


# Pre-built standard mapping profiles
GENERIC_OHLC_MAPPING = SourceColumnMapping(
    data_type=MarketDataType.OHLC,
    timestamp_col="timestamp",
    symbol_col="symbol",
    open_col="open",
    high_col="high",
    low_col="low",
    close_col="close",
    volume_col="volume",
    spread_col="spread",
)

MT5_EXPORT_OHLC_MAPPING = SourceColumnMapping(
    data_type=MarketDataType.OHLC,
    date_col="<DATE>",
    time_col="<TIME>",
    open_col="<OPEN>",
    high_col="<HIGH>",
    low_col="<LOW>",
    close_col="<CLOSE>",
    volume_col="<TICKVOL>",
    spread_col="<SPREAD>",
)

DUKASCOPY_CSV_MAPPING = SourceColumnMapping(
    data_type=MarketDataType.OHLC,
    timestamp_col="Gmt time",
    open_col="Open",
    high_col="High",
    low_col="Low",
    close_col="Close",
    volume_col="Volume",
)

GENERIC_TICK_MAPPING = SourceColumnMapping(
    data_type=MarketDataType.TICK,
    timestamp_col="timestamp",
    symbol_col="symbol",
    bid_col="bid",
    ask_col="ask",
    last_col="last",
    volume_col="volume",
)
