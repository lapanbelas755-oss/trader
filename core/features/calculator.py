"""Deterministic mathematical feature calculation engine for Trader Machine V1."""
from datetime import datetime, timezone
from decimal import Decimal
import math
from typing import Any, Sequence
from core.features.contract import CalculatedFeatureRecord, FeatureStatus

class FeatureCalculator:
    """Calculates deterministic market measurements, ATR(14), rolling baselines, and anomaly indicators."""

    def __init__(self, baseline_window: int = 100, atr_period: int = 14):
        self.baseline_window = baseline_window
        self.atr_period = atr_period

    def _extract(self, obj: Any, attr: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(attr)
        return getattr(obj, attr, None)

    def calculate_features(self, candles: Sequence[Any]) -> list[CalculatedFeatureRecord]:
        """
        Calculates all derived features for an ordered sequence of candles.
        Candles must be strictly ordered by timestamp ASC.
        Zero look-ahead bias is strictly maintained.
        """
        candle_list = list(candles)
        if not candle_list:
            return []

        # Ensure sorted deterministically by timestamp
        def get_ts(c: Any) -> datetime:
            t = self._extract(c, "timestamp")
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

        candle_list.sort(key=get_ts)

        records: list[CalculatedFeatureRecord] = []
        true_ranges: list[Decimal] = []
        atrs: list[Decimal | None] = []
        results: list[Decimal | None] = []
        efforts: list[Decimal] = []
        ranges: list[Decimal] = []

        running_atr: Decimal | None = None

        for t, candle in enumerate(candle_list):
            symbol = str(self._extract(candle, "symbol")).strip().upper()
            timeframe = str(self._extract(candle, "timeframe")).strip()
            ts = get_ts(candle)

            open_p = Decimal(str(self._extract(candle, "open")))
            high_p = Decimal(str(self._extract(candle, "high")))
            low_p = Decimal(str(self._extract(candle, "low")))
            close_p = Decimal(str(self._extract(candle, "close")))
            tick_vol = Decimal(str(self._extract(candle, "tick_volume") or 0))

            # 1. Geometry
            bar_range = high_p - low_p
            body = abs(close_p - open_p)

            if t > 0:
                prev_close = Decimal(str(self._extract(candle_list[t - 1], "close")))
                price_change = close_p - prev_close
            else:
                price_change = close_p - open_p

            if bar_range > Decimal("0"):
                movement_efficiency = (body / bar_range).quantize(Decimal("0.0001"))
            else:
                movement_efficiency = Decimal("0.0000")

            # 2. True Range & ATR(14) Wilder's RMA
            if t > 0:
                prev_close = Decimal(str(self._extract(candle_list[t - 1], "close")))
                tr = max(
                    bar_range,
                    abs(high_p - prev_close),
                    abs(low_p - prev_close)
                )
            else:
                tr = bar_range

            true_ranges.append(tr)

            if t < self.atr_period - 1:
                # Insufficient bars for initial ATR
                atr = None
            elif t == self.atr_period - 1:
                # First ATR is simple arithmetic mean of first 14 TRs
                running_atr = (sum(true_ranges[:self.atr_period]) / Decimal(self.atr_period)).quantize(Decimal("0.000001"))
                atr = running_atr
            else:
                # Wilder's RMA: (prior_atr * 13 + current_tr) / 14
                running_atr = (
                    (running_atr * Decimal(self.atr_period - 1) + tr) / Decimal(self.atr_period)
                ).quantize(Decimal("0.000001"))
                atr = running_atr

            atrs.append(atr)
            efforts.append(tick_vol)
            ranges.append(bar_range)

            # 3. Effort vs Result (Law #4)
            effort = tick_vol
            if atr is not None and atr > Decimal("0"):
                result = (bar_range / atr).quantize(Decimal("0.000001"))
                if result > Decimal("0"):
                    effort_result_ratio = (effort / result).quantize(Decimal("0.0001"))
                else:
                    effort_result_ratio = None
            else:
                result = None
                effort_result_ratio = None

            results.append(result)

            # 4. Market Speed
            movement_speed = None
            range_per_second = None
            price_change_per_second = None

            if t > 0:
                prev_ts = get_ts(candle_list[t - 1])
                delta_sec = Decimal(str((ts - prev_ts).total_seconds()))
                if delta_sec > Decimal("0"):
                    movement_speed = (abs(price_change) / delta_sec).quantize(Decimal("0.00000001"))
                    range_per_second = (bar_range / delta_sec).quantize(Decimal("0.00000001"))
                    price_change_per_second = (price_change / delta_sec).quantize(Decimal("0.00000001"))

            # 5. Rolling Baseline (100 periods, strictly historical: t-100 ... t-1)
            volatility_zscore = None
            activity_zscore = None
            price_response_zscore = None
            is_anomaly_candidate = False
            is_strong_anomaly = False

            if t < self.atr_period - 1:
                status = FeatureStatus.INSUFFICIENT_DATA
            elif t < self.baseline_window:
                status = FeatureStatus.WARMUP
            else:
                status = FeatureStatus.VALID

                # Baseline slices strictly excluding current candle t
                baseline_slice = slice(t - self.baseline_window, t)

                # Activity Z-Score
                base_efforts = efforts[baseline_slice]
                mean_effort = sum(base_efforts) / Decimal(self.baseline_window)
                var_effort = sum((x - mean_effort) ** 2 for x in base_efforts) / Decimal(self.baseline_window)
                std_effort = Decimal(str(math.sqrt(float(var_effort))))
                if std_effort > Decimal("0"):
                    activity_zscore = ((effort - mean_effort) / std_effort).quantize(Decimal("0.0001"))
                else:
                    activity_zscore = Decimal("0.0000")

                # Volatility Z-Score (using bar_range)
                base_ranges = ranges[baseline_slice]
                mean_range = sum(base_ranges) / Decimal(self.baseline_window)
                var_range = sum((x - mean_range) ** 2 for x in base_ranges) / Decimal(self.baseline_window)
                std_range = Decimal(str(math.sqrt(float(var_range))))
                if std_range > Decimal("0"):
                    volatility_zscore = ((bar_range - mean_range) / std_range).quantize(Decimal("0.0001"))
                else:
                    volatility_zscore = Decimal("0.0000")

                # Price Response Z-Score (using result = range / atr)
                base_results = [r for r in results[baseline_slice] if r is not None]
                if len(base_results) >= self.baseline_window // 2 and result is not None:
                    mean_res = sum(base_results) / Decimal(len(base_results))
                    var_res = sum((x - mean_res) ** 2 for x in base_results) / Decimal(len(base_results))
                    std_res = Decimal(str(math.sqrt(float(var_res))))
                    if std_res > Decimal("0"):
                        price_response_zscore = ((result - mean_res) / std_res).quantize(Decimal("0.0001"))
                    else:
                        price_response_zscore = Decimal("0.0000")

                # 6. Anomaly Candidate Detection (Law #5 & Initial Research Parameters)
                if activity_zscore is not None and activity_zscore >= Decimal("2.0"):
                    is_anomaly_candidate = True

                if (
                    activity_zscore is not None
                    and activity_zscore >= Decimal("2.5")
                    and price_response_zscore is not None
                    and price_response_zscore <= Decimal("-1.5")
                ):
                    is_strong_anomaly = True

            record = CalculatedFeatureRecord(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=ts,
                atr=atr,
                range=bar_range.quantize(Decimal("0.000001")),
                body=body.quantize(Decimal("0.000001")),
                price_change=price_change.quantize(Decimal("0.000001")),
                movement_efficiency=movement_efficiency,
                effort=effort,
                result=result,
                effort_result_ratio=effort_result_ratio,
                volatility=atr if atr is not None else bar_range.quantize(Decimal("0.000001")),
                volatility_zscore=volatility_zscore,
                activity_zscore=activity_zscore,
                price_response_zscore=price_response_zscore,
                is_anomaly_candidate=is_anomaly_candidate,
                is_strong_anomaly=is_strong_anomaly,
                movement_speed=movement_speed,
                range_per_second=range_per_second,
                price_change_per_second=price_change_per_second,
                feature_status=status,
            )
            records.append(record)

        return records
