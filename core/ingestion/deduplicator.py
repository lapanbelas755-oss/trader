"""Deterministic deduplication engine for market ticks."""
from typing import Tuple
from core.ingestion.contract import ValidatedTickRecord

class TickDeduplicator:
    """Deduplicates tick records based on multi-field signatures or explicit tick IDs."""

    def __init__(self):
        self.seen_signatures: set[Tuple] = set()

    def make_signature(self, tick: ValidatedTickRecord) -> Tuple:
        """Create a deterministic unique signature for a tick."""
        if tick.tick_id:
            # If explicit source tick_id is available, use it as unique identifier
            return (tick.source, tick.symbol, tick.tick_id)
        # Otherwise, combine all essential factual dimensions
        return (
            tick.symbol,
            tick.timestamp.isoformat(),
            str(tick.bid),
            str(tick.ask),
            str(tick.last) if tick.last is not None else None,
            str(tick.volume),
            tick.source,
        )

    def deduplicate(self, records: list[ValidatedTickRecord]) -> tuple[list[ValidatedTickRecord], int]:
        """
        Deduplicate a list of validated records.
        Returns:
            (unique_records, duplicate_count)
        """
        unique_records: list[ValidatedTickRecord] = []
        duplicate_count = 0

        for record in records:
            sig = self.make_signature(record)
            if sig in self.seen_signatures:
                duplicate_count += 1
            else:
                self.seen_signatures.add(sig)
                unique_records.append(record)

        return unique_records, duplicate_count

    def reset(self) -> None:
        """Reset internal seen signatures cache."""
        self.seen_signatures.clear()
