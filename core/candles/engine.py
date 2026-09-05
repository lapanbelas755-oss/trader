"""Historical Candle Aggregation Engine for Trader Machine V1."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import text
from database.connection import get_engine
from core.candles.aggregator import CandleAggregator
from core.candles.contract import Timeframe
from core.candles.loader import CandleDatabaseLoader, CandleLoadResult

@dataclass
class AggregationSummary:
    symbol: str
    timeframe: Timeframe
    start_timestamp: Optional[datetime]
    end_timestamp: Optional[datetime]
    ticks_processed: int
    candles_generated: int
    load_result: CandleLoadResult

class CandleAggregationEngine:
    """Orchestrates chunked tick querying, aggregation, and database upsert."""

    def __init__(self, chunk_size: int = 5000):
        self.chunk_size = chunk_size
        self.loader = CandleDatabaseLoader()

    def aggregate_range(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_timestamp: datetime | None = None,
        end_timestamp: datetime | None = None,
        only_closed: bool = True,
    ) -> AggregationSummary:
        """
        Aggregate ticks for symbol and timeframe within [start_timestamp, end_timestamp].
        Queries market_ticks using index-backed range query.
        """
        clean_symbol = symbol.strip().upper()
        engine = get_engine()

        # Build query parameters
        params = {"symbol": clean_symbol}
        conditions = ["symbol = :symbol"]

        if start_timestamp is not None:
            ts_start = start_timestamp if start_timestamp.tzinfo else start_timestamp.replace(tzinfo=timezone.utc)
            conditions.append("timestamp >= :start_ts")
            params["start_ts"] = ts_start

        if end_timestamp is not None:
            ts_end = end_timestamp if end_timestamp.tzinfo else end_timestamp.replace(tzinfo=timezone.utc)
            conditions.append("timestamp <= :end_ts")
            params["end_ts"] = ts_end

        where_clause = " AND ".join(conditions)

        # Query ordered ticks from database
        query = text(f"""
            SELECT id, timestamp, symbol, bid, ask, last, volume
            FROM market_ticks
            WHERE {where_clause}
            ORDER BY timestamp ASC, id ASC
        """)

        ticks: list[dict] = []
        with engine.connect() as conn:
            result = conn.execute(query, params)
            for row in result:
                ticks.append({
                    "id": row.id,
                    "timestamp": row.timestamp,
                    "symbol": row.symbol,
                    "bid": row.bid,
                    "ask": row.ask,
                    "last": row.last,
                    "volume": row.volume,
                })

        ticks_count = len(ticks)
        if ticks_count == 0:
            return AggregationSummary(
                symbol=clean_symbol,
                timeframe=timeframe,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                ticks_processed=0,
                candles_generated=0,
                load_result=CandleLoadResult(),
            )

        aggregator = CandleAggregator(timeframe=timeframe, only_closed=only_closed)
        candles = aggregator.aggregate_ticks(ticks, data_end_time=end_timestamp)

        load_res = self.loader.upsert_candles(candles)

        return AggregationSummary(
            symbol=clean_symbol,
            timeframe=timeframe,
            start_timestamp=ticks[0]["timestamp"],
            end_timestamp=ticks[-1]["timestamp"],
            ticks_processed=ticks_count,
            candles_generated=len(candles),
            load_result=load_res,
        )
