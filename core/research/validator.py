"""
Historical data quality and integrity validator for Historical Research Engine V1.
Strictly audits OHLC bounds, spreads, volumes, duplicate timestamps, and intervals.
Does NOT silently repair bad data. Missing candles must never be fabricated.
"""

from datetime import timedelta, timezone
from decimal import Decimal
from typing import Any, List, Sequence
from core.research.contract import DataValidationReport, ValidationStatus
from core.setups.common import get_val, ensure_utc


class HistoricalDataValidator:
    """
    Performs comprehensive data quality audit on raw or aggregated historical candles.
    """

    TIMEFRAME_DELTAS = {
        "M1": timedelta(minutes=1),
        "M5": timedelta(minutes=5),
        "M15": timedelta(minutes=15),
        "H1": timedelta(hours=1),
    }

    def __init__(self, timeframe: str = "M5"):
        self.timeframe = timeframe.strip().upper()
        self.expected_delta = self.TIMEFRAME_DELTAS.get(self.timeframe, timedelta(minutes=5))

    def validate_dataset(self, candles: Sequence[Any]) -> DataValidationReport:
        """
        Audits candles for strict validity:
        - OHLC consistency: low <= open, close <= high; high >= low
        - Positive prices
        - Non-negative spreads & volumes
        - Timezone consistency (must be UTC)
        - Chronological ordering
        - Duplicate detection
        - Missing interval reporting (without fabrication)
        """
        if not candles:
            return DataValidationReport(
                status=ValidationStatus.REJECTED,
                total_candles=0,
                valid_candles=0,
                errors=["Dataset is empty."],
            )

        errors: List[str] = []
        warnings: List[str] = []
        valid_count = 0
        duplicate_count = 0
        missing_intervals = 0

        seen_timestamps = set()
        prev_ts = None

        for idx, c in enumerate(candles):
            raw_ts = get_val(c, "timestamp")
            if raw_ts is None:
                errors.append(f"Candle at index {idx} has missing timestamp.")
                continue

            ts = ensure_utc(raw_ts)

            # Duplicate timestamp check
            if ts in seen_timestamps:
                duplicate_count += 1
                errors.append(f"Duplicate timestamp detected at index {idx}: {ts.isoformat()}")
            seen_timestamps.add(ts)

            # Chronological ordering check
            if prev_ts is not None and ts < prev_ts:
                errors.append(
                    f"Out of order timestamp at index {idx}: {ts.isoformat()} occurs after {prev_ts.isoformat()}"
                )

            # Missing interval check (gap > expected delta)
            if prev_ts is not None and ts > prev_ts:
                delta = ts - prev_ts
                if delta > self.expected_delta:
                    # Weekend gap check: gap between Friday 21:00 UTC and Sunday 21:00 UTC is normal market close
                    is_weekend = (prev_ts.weekday() == 4 and ts.weekday() == 6) or delta >= timedelta(days=2)
                    if not is_weekend:
                        missing_intervals += 1
                        warnings.append(
                            f"Missing interval between {prev_ts.isoformat()} and {ts.isoformat()} (gap: {delta})"
                        )

            prev_ts = ts

            # Price integrity checks
            try:
                o = Decimal(str(get_val(c, "open")))
                h = Decimal(str(get_val(c, "high")))
                l = Decimal(str(get_val(c, "low")))
                close_p = Decimal(str(get_val(c, "close")))
            except Exception as e:
                errors.append(f"Invalid decimal price format at index {idx}: {e}")
                continue

            if o <= Decimal("0") or h <= Decimal("0") or l <= Decimal("0") or close_p <= Decimal("0"):
                errors.append(f"Non-positive price at index {idx}: O={o}, H={h}, L={l}, C={close_p}")
                continue

            # OHLC consistency
            if not (l <= o <= h and l <= close_p <= h and h >= l):
                errors.append(
                    f"OHLC violation at index {idx} ({ts.isoformat()}): Low {l} must be <= Open {o}/Close {close_p} <= High {h}"
                )
                continue

            # Spread check
            spread = get_val(c, "spread")
            if spread is not None:
                try:
                    s_dec = Decimal(str(spread))
                    if s_dec < Decimal("0"):
                        errors.append(f"Negative spread at index {idx}: {s_dec}")
                        continue
                except Exception:
                    errors.append(f"Invalid spread format at index {idx}: {spread}")
                    continue

            # Volume check
            vol = get_val(c, "tick_volume")
            if vol is not None:
                if int(vol) < 0:
                    errors.append(f"Negative volume at index {idx}: {vol}")
                    continue

            valid_count += 1

        # Determine overall status
        if errors:
            status = ValidationStatus.REJECTED
        elif warnings:
            status = ValidationStatus.PASS_WITH_WARNINGS
        else:
            status = ValidationStatus.PASS

        return DataValidationReport(
            status=status,
            total_candles=len(candles),
            valid_candles=valid_count,
            duplicate_count=duplicate_count,
            missing_intervals=missing_intervals,
            warnings=warnings,
            errors=errors,
        )
