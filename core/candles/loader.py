"""Database Upsert and Loader for aggregated market candles."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence
from sqlalchemy import text
from database.connection import get_engine
from core.candles.contract import AggregatedCandle

@dataclass
class CandleLoadResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total_processed(self) -> int:
        return self.inserted + self.updated + self.unchanged


class CandleDatabaseLoader:
    """Loads and upserts AggregatedCandles into PostgreSQL market_candles table."""

    def __init__(self, batch_size: int = 500):
        self.batch_size = batch_size

    def upsert_candles(self, candles: Sequence[AggregatedCandle]) -> CandleLoadResult:
        """
        Idempotently upsert candles into market_candles.
        Detects INSERT vs UPDATE vs UNCHANGED deterministically.
        """
        result = CandleLoadResult()
        if not candles:
            return result

        engine = get_engine()

        with engine.begin() as conn:
            for i in range(0, len(candles), self.batch_size):
                batch = candles[i:i + self.batch_size]

                for candle in batch:
                    # Check if candle exists
                    check_sql = text("""
                        SELECT open, high, low, close, tick_volume, real_volume, spread
                        FROM market_candles
                        WHERE symbol = :symbol AND timeframe = :tf AND timestamp = :ts
                    """)
                    existing = conn.execute(
                        check_sql,
                        {
                            "symbol": candle.symbol,
                            "tf": candle.timeframe.value,
                            "ts": candle.timestamp,
                        }
                    ).fetchone()

                    if existing is None:
                        # INSERT
                        insert_sql = text("""
                            INSERT INTO market_candles (
                                symbol, timeframe, timestamp, open, high, low, close,
                                tick_volume, real_volume, spread
                            ) VALUES (
                                :symbol, :tf, :ts, :open, :high, :low, :close,
                                :tick_volume, :real_volume, :spread
                            );
                        """)
                        conn.execute(
                            insert_sql,
                            {
                                "symbol": candle.symbol,
                                "tf": candle.timeframe.value,
                                "ts": candle.timestamp,
                                "open": candle.open,
                                "high": candle.high,
                                "low": candle.low,
                                "close": candle.close,
                                "tick_volume": candle.tick_volume,
                                "real_volume": candle.real_volume,
                                "spread": candle.spread,
                            }
                        )
                        result.inserted += 1
                    else:
                        # Compare existing values with new values
                        ex_open, ex_high, ex_low, ex_close, ex_tvol, ex_rvol, ex_spd = existing
                        is_same = (
                            Decimal(str(ex_open)) == candle.open
                            and Decimal(str(ex_high)) == candle.high
                            and Decimal(str(ex_low)) == candle.low
                            and Decimal(str(ex_close)) == candle.close
                            and int(ex_tvol) == candle.tick_volume
                            and int(ex_rvol) == candle.real_volume
                            and Decimal(str(ex_spd)) == candle.spread
                        )

                        if is_same:
                            result.unchanged += 1
                        else:
                            # UPDATE
                            update_sql = text("""
                                UPDATE market_candles
                                SET open = :open,
                                    high = :high,
                                    low = :low,
                                    close = :close,
                                    tick_volume = :tick_volume,
                                    real_volume = :real_volume,
                                    spread = :spread
                                WHERE symbol = :symbol AND timeframe = :tf AND timestamp = :ts;
                            """)
                            conn.execute(
                                update_sql,
                                {
                                    "symbol": candle.symbol,
                                    "tf": candle.timeframe.value,
                                    "ts": candle.timestamp,
                                    "open": candle.open,
                                    "high": candle.high,
                                    "low": candle.low,
                                    "close": candle.close,
                                    "tick_volume": candle.tick_volume,
                                    "real_volume": candle.real_volume,
                                    "spread": candle.spread,
                                }
                            )
                            result.updated += 1

        return result
