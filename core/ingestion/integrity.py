"""Data Integrity Checker for raw market ticks."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from core.ingestion.contract import ValidatedTickRecord

class IntegrityIssue:
    def __init__(self, issue_type: str, message: str, index: int, timestamp: Optional[datetime] = None):
        self.issue_type = issue_type  # 'PRICE', 'TIMESTAMP', 'SYMBOL', 'VOLUME', 'GAP'
        self.message = message
        self.index = index
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return f"[{self.issue_type}] Row {self.index}: {self.message}"


class IntegrityChecker:
    """Performs deep sanity and integrity checks on validated ticks."""

    def __init__(self, gap_threshold_seconds: float = 3600.0):
        self.gap_threshold = timedelta(seconds=gap_threshold_seconds)

    def check(self, records: list[ValidatedTickRecord]) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        if not records:
            return issues

        prev_tick: Optional[ValidatedTickRecord] = None
        expected_symbol = records[0].symbol

        for idx, tick in enumerate(records):
            # 1. Price Checks
            if tick.bid <= Decimal("0"):
                issues.append(IntegrityIssue("PRICE", f"Non-positive bid: {tick.bid}", idx, tick.timestamp))
            if tick.ask <= Decimal("0"):
                issues.append(IntegrityIssue("PRICE", f"Non-positive ask: {tick.ask}", idx, tick.timestamp))
            if tick.ask < tick.bid:
                issues.append(IntegrityIssue("PRICE", f"Inverted spread: ask ({tick.ask}) < bid ({tick.bid})", idx, tick.timestamp))

            # 2. Volume Checks
            if tick.volume < Decimal("0"):
                issues.append(IntegrityIssue("VOLUME", f"Negative volume: {tick.volume}", idx, tick.timestamp))

            # 3. Symbol Consistency
            if tick.symbol != expected_symbol:
                issues.append(IntegrityIssue(
                    "SYMBOL",
                    f"Inconsistent symbol: found '{tick.symbol}', expected '{expected_symbol}'",
                    idx,
                    tick.timestamp,
                ))

            # 4. Sequential Checks (with previous tick)
            if prev_tick is not None:
                # Backward Timestamp check (DO NOT DELETE, REPORT IT)
                if tick.timestamp < prev_tick.timestamp:
                    time_diff = (prev_tick.timestamp - tick.timestamp).total_seconds()
                    issues.append(IntegrityIssue(
                        "TIMESTAMP",
                        f"Backward timestamp detected: current {tick.timestamp.isoformat()} < previous {prev_tick.timestamp.isoformat()} (delta: -{time_diff}s)",
                        idx,
                        tick.timestamp,
                    ))

                # Gap Check (observation only, NEVER fill fabricated data)
                elif (tick.timestamp - prev_tick.timestamp) >= self.gap_threshold:
                    gap_seconds = (tick.timestamp - prev_tick.timestamp).total_seconds()
                    issues.append(IntegrityIssue(
                        "GAP",
                        f"Market gap detected between {prev_tick.timestamp.isoformat()} and {tick.timestamp.isoformat()} ({gap_seconds / 3600:.2f} hours)",
                        idx,
                        tick.timestamp,
                    ))

            prev_tick = tick

        return issues
