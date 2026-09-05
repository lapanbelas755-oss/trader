"""Database Upsert and Loader for calculated market features."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence
from sqlalchemy import text
from database.connection import get_engine
from core.features.contract import CalculatedFeatureRecord

@dataclass
class FeatureLoadResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total_processed(self) -> int:
        return self.inserted + self.updated + self.unchanged

class FeatureDatabaseLoader:
    """Loads and upserts CalculatedFeatureRecords into PostgreSQL market_features table."""

    def __init__(self, batch_size: int = 500):
        self.batch_size = batch_size

    def upsert_features(self, features: Sequence[CalculatedFeatureRecord]) -> FeatureLoadResult:
        """
        Idempotently upsert features into market_features.
        Detects INSERT vs UPDATE vs UNCHANGED deterministically.
        """
        result = FeatureLoadResult()
        if not features:
            return result

        engine = get_engine()

        with engine.begin() as conn:
            for i in range(0, len(features), self.batch_size):
                batch = features[i:i + self.batch_size]

                for feat in batch:
                    # Check if feature row exists
                    check_sql = text("""
                        SELECT atr, range, body, price_change, movement_efficiency,
                               effort, result, effort_result_ratio, volatility,
                               volatility_zscore, activity_zscore, price_response_zscore,
                               is_anomaly_candidate, is_strong_anomaly,
                               movement_speed, range_per_second, price_change_per_second,
                               feature_status
                        FROM market_features
                        WHERE symbol = :symbol AND timeframe = :tf AND timestamp = :ts
                    """)
                    existing = conn.execute(
                        check_sql,
                        {
                            "symbol": feat.symbol,
                            "tf": feat.timeframe,
                            "ts": feat.timestamp,
                        }
                    ).fetchone()

                    params = {
                        "symbol": feat.symbol,
                        "tf": feat.timeframe,
                        "ts": feat.timestamp,
                        "atr": feat.atr,
                        "range": feat.range,
                        "body": feat.body,
                        "price_change": feat.price_change,
                        "movement_efficiency": feat.movement_efficiency,
                        "effort": feat.effort,
                        "result": feat.result,
                        "effort_result_ratio": feat.effort_result_ratio,
                        "volatility": feat.volatility,
                        "volatility_zscore": feat.volatility_zscore,
                        "activity_zscore": feat.activity_zscore,
                        "price_response_zscore": feat.price_response_zscore,
                        "is_anomaly_candidate": feat.is_anomaly_candidate,
                        "is_strong_anomaly": feat.is_strong_anomaly,
                        "movement_speed": feat.movement_speed,
                        "range_per_second": feat.range_per_second,
                        "price_change_per_second": feat.price_change_per_second,
                        "feature_status": feat.feature_status.value,
                    }

                    if existing is None:
                        # INSERT
                        insert_sql = text("""
                            INSERT INTO market_features (
                                symbol, timeframe, timestamp,
                                atr, range, body, price_change, movement_efficiency,
                                effort, result, effort_result_ratio,
                                volatility, volatility_zscore, activity_zscore, price_response_zscore,
                                is_anomaly_candidate, is_strong_anomaly,
                                movement_speed, range_per_second, price_change_per_second,
                                feature_status
                            ) VALUES (
                                :symbol, :tf, :ts,
                                :atr, :range, :body, :price_change, :movement_efficiency,
                                :effort, :result, :effort_result_ratio,
                                :volatility, :volatility_zscore, :activity_zscore, :price_response_zscore,
                                :is_anomaly_candidate, :is_strong_anomaly,
                                :movement_speed, :range_per_second, :price_change_per_second,
                                :feature_status
                            );
                        """)
                        conn.execute(insert_sql, params)
                        result.inserted += 1
                    else:
                        # Compare to determine if identical
                        ex_atr, ex_range, ex_body, ex_pc, ex_me, ex_eff, ex_res, ex_err, ex_vol, ex_vz, ex_az, ex_prz, ex_anom, ex_sanom, ex_ms, ex_rps, ex_pcps, ex_st = existing
                        
                        def eq(a, b):
                            if a is None and b is None:
                                return True
                            if a is None or b is None:
                                return False
                            return Decimal(str(a)) == Decimal(str(b))

                        is_same = (
                            eq(ex_atr, feat.atr)
                            and eq(ex_range, feat.range)
                            and eq(ex_body, feat.body)
                            and eq(ex_pc, feat.price_change)
                            and eq(ex_me, feat.movement_efficiency)
                            and eq(ex_eff, feat.effort)
                            and eq(ex_res, feat.result)
                            and eq(ex_err, feat.effort_result_ratio)
                            and eq(ex_vol, feat.volatility)
                            and eq(ex_vz, feat.volatility_zscore)
                            and eq(ex_az, feat.activity_zscore)
                            and eq(ex_prz, feat.price_response_zscore)
                            and bool(ex_anom) == feat.is_anomaly_candidate
                            and bool(ex_sanom) == feat.is_strong_anomaly
                            and eq(ex_ms, feat.movement_speed)
                            and eq(ex_rps, feat.range_per_second)
                            and eq(ex_pcps, feat.price_change_per_second)
                            and ex_st == feat.feature_status.value
                        )

                        if is_same:
                            result.unchanged += 1
                        else:
                            # UPDATE
                            update_sql = text("""
                                UPDATE market_features
                                SET atr = :atr,
                                    range = :range,
                                    body = :body,
                                    price_change = :price_change,
                                    movement_efficiency = :movement_efficiency,
                                    effort = :effort,
                                    result = :result,
                                    effort_result_ratio = :effort_result_ratio,
                                    volatility = :volatility,
                                    volatility_zscore = :volatility_zscore,
                                    activity_zscore = :activity_zscore,
                                    price_response_zscore = :price_response_zscore,
                                    is_anomaly_candidate = :is_anomaly_candidate,
                                    is_strong_anomaly = :is_strong_anomaly,
                                    movement_speed = :movement_speed,
                                    range_per_second = :range_per_second,
                                    price_change_per_second = :price_change_per_second,
                                    feature_status = :feature_status
                                WHERE symbol = :symbol AND timeframe = :tf AND timestamp = :ts;
                            """)
                            conn.execute(update_sql, params)
                            result.updated += 1

        return result
