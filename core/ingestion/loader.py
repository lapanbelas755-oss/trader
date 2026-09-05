"""Transactional Database Loader for validated market ticks."""
from typing import Sequence
from sqlalchemy import text
from database.connection import get_engine
from core.ingestion.contract import ValidatedTickRecord

class DatabaseLoader:
    """Loads validated tick records into PostgreSQL market_ticks table with atomic transaction and rollback support."""

    def __init__(self, batch_size: int = 500):
        self.batch_size = batch_size

    def load_ticks(self, records: Sequence[ValidatedTickRecord]) -> int:
        """
        Insert validated records in batches into market_ticks table.
        Wraps entire operation in a single atomic transaction.
        Rolls back automatically if any batch fails.
        Returns total inserted row count.
        """
        if not records:
            return 0

        engine = get_engine()
        insert_sql = text("""
            INSERT INTO market_ticks (
                timestamp, symbol, bid, ask, last, volume, tick_direction, source
            ) VALUES (
                :timestamp, :symbol, :bid, :ask, :last, :volume, :tick_direction, :source
            );
        """)

        total_inserted = 0

        # Execute in atomic transaction block
        with engine.begin() as conn:
            for i in range(0, len(records), self.batch_size):
                batch = records[i:i + self.batch_size]
                params = [
                    {
                        "timestamp": r.timestamp,
                        "symbol": r.symbol,
                        "bid": r.bid,
                        "ask": r.ask,
                        "last": r.last,
                        "volume": r.volume,
                        "tick_direction": r.tick_direction,
                        "source": r.source,
                    }
                    for r in batch
                ]
                conn.execute(insert_sql, params)
                total_inserted += len(batch)

        return total_inserted
