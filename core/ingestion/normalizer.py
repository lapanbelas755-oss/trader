"""Deterministic and explainable normalizer for raw market data records.
Does NOT perform smoothing, filtering, interpolation, or synthetic fabrication.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

class TickNormalizer:
    """Normalizes raw dictionary fields to standard types and representations."""

    def __init__(self, default_symbol: str = "EURUSD", default_source: str = "MT5_EXNESS"):
        self.default_symbol = default_symbol.strip().upper()
        self.default_source = default_source.strip().upper()
        self._last_bid: Optional[Decimal] = None

    def normalize_timestamp(self, val: Any) -> datetime:
        """Deterministically parse and normalize timestamp to UTC timezone-aware datetime."""
        if val is None or val == "":
            raise ValueError("Timestamp value is null or empty")

        if isinstance(val, datetime):
            if val.tzinfo is None or val.tzinfo.utcoffset(val) is None:
                # If naive, localize to UTC deterministically
                return val.replace(tzinfo=timezone.utc)
            return val.astimezone(timezone.utc)

        if isinstance(val, (int, float)):
            # Epoch timestamp in seconds or milliseconds
            # If greater than 1e11, treat as milliseconds
            ts_sec = val / 1000.0 if val > 1e11 else float(val)
            return datetime.fromtimestamp(ts_sec, tz=timezone.utc)

        if isinstance(val, str):
            clean_str = val.strip()
            # Try ISO format
            try:
                dt = datetime.fromisoformat(clean_str)
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except ValueError:
                pass

            # Try common datetime formats
            for fmt in (
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y.%m.%d %H:%M:%S.%f",
                "%Y.%m.%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
            ):
                try:
                    dt = datetime.strptime(clean_str, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

        raise ValueError(f"Unparseable timestamp: {val!r}")

    def normalize_decimal(self, val: Any, field_name: str) -> Decimal:
        """Convert value to exact Decimal representation."""
        if val is None or val == "":
            raise ValueError(f"{field_name} is null or empty")
        try:
            return Decimal(str(val).strip())
        except (InvalidOperation, TypeError):
            raise ValueError(f"Invalid numeric format for {field_name}: {val!r}")

    def normalize_record(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Apply deterministic normalization to a single raw dictionary."""
        normalized: dict[str, Any] = {}

        # 1. Symbol
        raw_symbol = raw.get("symbol")
        if raw_symbol and str(raw_symbol).strip():
            normalized["symbol"] = str(raw_symbol).strip().upper()
        else:
            normalized["symbol"] = self.default_symbol

        # 2. Timestamp
        normalized["timestamp"] = self.normalize_timestamp(raw.get("timestamp") or raw.get("time"))

        # 3. Bid & Ask
        normalized["bid"] = self.normalize_decimal(raw.get("bid"), "bid")
        normalized["ask"] = self.normalize_decimal(raw.get("ask"), "ask")

        # 4. Last (optional)
        raw_last = raw.get("last")
        if raw_last is not None and str(raw_last).strip() != "":
            normalized["last"] = self.normalize_decimal(raw_last, "last")
        else:
            normalized["last"] = None

        # 5. Volume
        raw_vol = raw.get("volume") or raw.get("vol") or raw.get("tick_volume")
        if raw_vol is not None and str(raw_vol).strip() != "":
            normalized["volume"] = self.normalize_decimal(raw_vol, "volume")
        else:
            normalized["volume"] = Decimal("0")

        # 6. Source
        raw_source = raw.get("source")
        if raw_source and str(raw_source).strip():
            normalized["source"] = str(raw_source).strip().upper()
        else:
            normalized["source"] = self.default_source

        # 7. Tick ID
        raw_id = raw.get("tick_id") or raw.get("id")
        normalized["tick_id"] = str(raw_id).strip() if raw_id is not None and str(raw_id).strip() else None

        # 8. Tick Direction (Derived deterministically if not explicitly provided)
        raw_dir = raw.get("tick_direction") or raw.get("direction")
        if raw_dir and str(raw_dir).strip():
            normalized["tick_direction"] = str(raw_dir).strip().upper()
        else:
            if self._last_bid is not None:
                if normalized["bid"] > self._last_bid:
                    normalized["tick_direction"] = "UP"
                elif normalized["bid"] < self._last_bid:
                    normalized["tick_direction"] = "DOWN"
                else:
                    normalized["tick_direction"] = "FLAT"
            else:
                normalized["tick_direction"] = "FLAT"

        self._last_bid = normalized["bid"]
        return normalized
