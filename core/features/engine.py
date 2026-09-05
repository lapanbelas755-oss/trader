"""Feature Engine Orchestrator for Trader Machine V1."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import text
from database.connection import get_engine
from core.features.calculator import FeatureCalculator
from core.features.contract import CalculatedFeatureRecord
from core.features.loader import FeatureDatabaseLoader, FeatureLoadResult

@dataclass
class FeatureEngineSummary:
    symbol: str
    timeframe: str
    candles_processed: int
    features_calculated: int
    load_result: FeatureLoadResult

class MarketFeatureEngine:
    """Orchestrates candle retrieval, feature calculation, and idempotent persistence."""

    def __init__(self, baseline_window: int = 100, atr_period: int = 14):
        self.calculator = FeatureCalculator(baseline_window=baseline_window, atr_period=atr_period)
        self.loader = FeatureDatabaseLoader()

    def process_range(
        self,
        symbol: str,
        timeframe: str,
        start_timestamp: datetime | None = None,
        end_timestamp: datetime | None = None,
    ) -> FeatureEngineSummary:
        """
        Process features for given symbol and timeframe.
        Fetches candles from market_candles table, calculates features, and upserts them.
        """
        clean_symbol = symbol.strip().upper()
        clean_tf = timeframe.strip().upper()
        engine = get_engine()

        params = {"symbol": clean_symbol, "tf": clean_tf}
        conditions = ["symbol = :symbol", "timeframe = :tf"]

        if start_timestamp is not None:
            ts_start = start_timestamp if start_timestamp.tzinfo else start_timestamp.replace(tzinfo=timezone.utc)
            conditions.append("timestamp >= :start_ts")
            params["start_ts"] = ts_start

        if end_timestamp is not None:
            ts_end = end_timestamp if end_timestamp.tzinfo else end_timestamp.replace(tzinfo=timezone.utc)
            conditions.append("timestamp <= :end_ts")
            params["end_ts"] = ts_end

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT symbol, timeframe, timestamp, open, high, low, close, tick_volume, real_volume, spread
            FROM market_candles
            WHERE {where_clause}
            ORDER BY timestamp ASC
        """)

        candles: list[dict] = []
        with engine.connect() as conn:
            rows = conn.execute(query, params)
            for r in rows:
                candles.append({
                    "symbol": r.symbol,
                    "timeframe": r.timeframe,
                    "timestamp": r.timestamp,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "tick_volume": r.tick_volume,
                    "real_volume": r.real_volume,
                    "spread": r.spread,
                })

        if not candles:
            return FeatureEngineSummary(
                symbol=clean_symbol,
                timeframe=clean_tf,
                candles_processed=0,
                features_calculated=0,
                load_result=FeatureLoadResult(),
            )

        calculated = self.calculator.calculate_features(candles)
        load_res = self.loader.upsert_features(calculated)

        return FeatureEngineSummary(
            symbol=clean_symbol,
            timeframe=clean_tf,
            candles_processed=len(candles),
            features_calculated=len(calculated),
            load_result=load_res,
        )
