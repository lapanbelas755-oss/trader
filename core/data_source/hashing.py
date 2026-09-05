"""Deterministic canonical hashing for market datasets.
Guarantees bitwise reproducibility and row-order independence for identical semantic content.
"""
import hashlib
from decimal import Decimal
from typing import Iterable, Sequence, Union
from core.data_source.contract import ValidatedCandleRecord, ValidatedTickRecord


class CanonicalHasher:
    """Computes deterministic SHA-256 hashes over canonical market records."""

    @staticmethod
    def canonical_candle_row(record: ValidatedCandleRecord) -> str:
        """Format a candle record into a canonical pipe-delimited string representation.
        
        Canonical formatting:
        - Timestamp: ISO 8601 UTC strictly with 'Z' suffix (e.g. 2026-02-01T00:00:00Z)
        - Symbol: uppercase string
        - Timeframe: uppercase string
        - Prices: fixed 6-decimal precision
        - Volume: fixed 4-decimal precision
        """
        ts_str = record.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        open_str = f"{Decimal(str(record.open)):.6f}"
        high_str = f"{Decimal(str(record.high)):.6f}"
        low_str = f"{Decimal(str(record.low)):.6f}"
        close_str = f"{Decimal(str(record.close)):.6f}"
        vol_str = f"{Decimal(str(record.volume)):.4f}"
        spread_str = f"{Decimal(str(record.spread)):.2f}" if record.spread is not None else "NONE"
        return f"{ts_str}|{record.symbol.upper()}|{record.timeframe.upper()}|{open_str}|{high_str}|{low_str}|{close_str}|{vol_str}|{spread_str}"

    @staticmethod
    def canonical_tick_row(record: ValidatedTickRecord) -> str:
        """Format a tick record into a canonical pipe-delimited string representation."""
        ts_str = record.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        bid_str = f"{Decimal(str(record.bid)):.6f}"
        ask_str = f"{Decimal(str(record.ask)):.6f}"
        last_str = f"{Decimal(str(record.last)):.6f}" if record.last is not None else "NONE"
        vol_str = f"{Decimal(str(record.volume)):.4f}"
        return f"{ts_str}|{record.symbol.upper()}|{bid_str}|{ask_str}|{last_str}|{vol_str}"

    @classmethod
    def compute_hash(
        cls, 
        records: Sequence[Union[ValidatedCandleRecord, ValidatedTickRecord]]
    ) -> str:
        """Compute order-independent deterministic SHA-256 hash over records.
        
        To ensure identical content produces the exact same hash regardless of file row ordering:
        1. Convert each record to its canonical row string.
        2. Sort all canonical row strings lexicographically.
        3. Feed the sorted sequence into SHA-256 separated by newlines.
        """
        if not records:
            return hashlib.sha256(b"EMPTY_DATASET").hexdigest()

        canonical_rows: list[str] = []
        for r in records:
            if isinstance(r, ValidatedCandleRecord):
                canonical_rows.append(cls.canonical_candle_row(r))
            elif isinstance(r, ValidatedTickRecord):
                canonical_rows.append(cls.canonical_tick_row(r))
            else:
                raise TypeError(f"Unsupported record type for canonical hashing: {type(r)}")

        canonical_rows.sort()

        hasher = hashlib.sha256()
        for row in canonical_rows:
            hasher.update(row.encode("utf-8"))
            hasher.update(b"\n")

        return hasher.hexdigest()
