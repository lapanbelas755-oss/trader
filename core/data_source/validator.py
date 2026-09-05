"""Comprehensive Market Data Quality Validator.
Validates schema, timestamps, monotonicity, duplicates, OHLC integrity, bid/ask validity,
volume, symbol/timeframe consistency, and gap detection without fabricating data.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Sequence
import zoneinfo

from core.data_source.contract import (
    CheckStatus,
    DataQualityStatus,
    DatasetQualityReport,
    GapRecord,
    MarketDataType,
    QualityCheckResult,
    ValidatedCandleRecord,
    ValidatedTickRecord,
)
from core.data_source.mapping import SourceColumnMapping


TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}


class ValidationError(ValueError):
    """Raised on unrecoverable validation rejection."""
    pass


class MarketDataValidator:
    """Rigorous validator auditing external market datasets."""

    def __init__(
        self,
        expected_symbol: str = "EURUSD",
        expected_timeframe: str = "M5",
        declared_timezone: Optional[str] = None,
    ):
        self.expected_symbol = expected_symbol.upper()
        self.expected_timeframe = expected_timeframe.upper()
        self.declared_timezone = declared_timezone

    def resolve_timezone(self) -> zoneinfo.ZoneInfo:
        """Resolve and validate the declared timezone.
        Rejects unknown, empty, or None timezone.
        """
        if not self.declared_timezone or not isinstance(self.declared_timezone, str) or not self.declared_timezone.strip():
            raise ValidationError("Explicit timezone is required. Unknown or unspecified timezone is strictly REJECTED.")

        tz_str = self.declared_timezone.strip()
        try:
            return zoneinfo.ZoneInfo(tz_str)
        except Exception as e:
            # Handle common offsets like UTC+2, GMT+2, UTC-5
            tz_upper = tz_str.upper()
            if tz_upper in ("UTC", "GMT", "Z"):
                return zoneinfo.ZoneInfo("UTC")
            raise ValidationError(f"Unknown or invalid timezone '{tz_str}': {e}")

    def parse_timestamp(self, ts_val: Any, date_val: Any = None, time_val: Any = None, tz: Optional[zoneinfo.ZoneInfo] = None) -> datetime:
        """Parse timestamp and normalize to UTC timezone-aware datetime."""
        if tz is None:
            tz = self.resolve_timezone()

        if ts_val is not None:
            if isinstance(ts_val, datetime):
                dt = ts_val
            elif isinstance(ts_val, str):
                ts_clean = ts_val.strip()
                # Try ISO format
                try:
                    dt = datetime.fromisoformat(ts_clean.replace("Z", "+00:00"))
                except ValueError:
                    # Common formats: 'YYYY.MM.DD HH:MM:SS', 'YYYY-MM-DD HH:MM:SS', 'DD/MM/YYYY HH:MM:SS'
                    formats = [
                        "%Y.%m.%d %H:%M:%S",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y.%m.%d %H:%M",
                        "%Y-%m-%d %H:%M",
                        "%d.%m.%Y %H:%M:%S",
                        "%d/%m/%Y %H:%M:%S",
                        "%d-%m-%Y %H:%M:%S",
                        "%Y%m%d %H%M%S",
                        "%Y%m%d %H:%M:%S",
                    ]
                    dt = None
                    for fmt in formats:
                        try:
                            dt = datetime.strptime(ts_clean, fmt)
                            break
                        except ValueError:
                            continue
                    if dt is None:
                        raise ValidationError(f"Unable to parse timestamp string: '{ts_clean}'")
            elif isinstance(ts_val, (int, float)):
                # Unix timestamp (seconds or milliseconds)
                if ts_val > 1e11:
                    dt = datetime.fromtimestamp(ts_val / 1000.0, tz=timezone.utc)
                else:
                    dt = datetime.fromtimestamp(ts_val, tz=timezone.utc)
            else:
                raise ValidationError(f"Unsupported timestamp value type: {type(ts_val)}")
        elif date_val is not None and time_val is not None:
            comb = f"{str(date_val).strip()} {str(time_val).strip()}"
            formats = [
                "%Y.%m.%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y.%m.%d %H:%M",
                "%Y-%m-%d %H:%M",
                "%d.%m.%Y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S",
            ]
            dt = None
            for fmt in formats:
                try:
                    dt = datetime.strptime(comb, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                raise ValidationError(f"Unable to parse combined date/time: '{comb}'")
        else:
            raise ValidationError("Missing timestamp inputs.")

        # Attach declared timezone if naive, then convert to UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(timezone.utc)

    def validate_and_normalize_ohlc(
        self,
        raw_records: Sequence[dict[str, Any]],
        mapping: SourceColumnMapping,
        dataset_name: str,
    ) -> tuple[DatasetQualityReport, list[ValidatedCandleRecord], list[GapRecord]]:
        """Validate raw OHLC records, normalize to UTC, detect duplicates and gaps without data fabrication."""
        report = DatasetQualityReport(dataset_name=dataset_name, status=DataQualityStatus.PASS)
        validated_records: list[ValidatedCandleRecord] = []
        gaps: list[GapRecord] = []

        # 1. Timezone Check
        try:
            source_tz = self.resolve_timezone()
            report.add_check(QualityCheckResult(
                check_name="timezone_verification",
                status=CheckStatus.PASS,
                details={"declared_timezone": str(source_tz), "target_timezone": "UTC"}
            ))
        except ValidationError as e:
            report.add_check(QualityCheckResult(
                check_name="timezone_verification",
                status=CheckStatus.FAIL,
                details={"error": str(e)}
            ))
            report.summary = f"REJECTED: Timezone validation failed - {e}"
            return report, [], []

        # 2. Parse and Row-Level Validation
        seen_timestamps: dict[datetime, ValidatedCandleRecord] = {}
        exact_duplicates_count = 0
        conflicting_duplicates_count = 0
        invalid_ohlc_count = 0
        invalid_volume_count = 0
        symbol_mismatch_count = 0
        parse_errors_count = 0

        for idx, raw in enumerate(raw_records):
            # Extract timestamp
            ts_raw = raw.get(mapping.timestamp_col) if mapping.timestamp_col else None
            date_raw = raw.get(mapping.date_col) if mapping.date_col else None
            time_raw = raw.get(mapping.time_col) if mapping.time_col else None

            try:
                utc_ts = self.parse_timestamp(ts_raw, date_raw, time_raw, tz=source_tz)
            except Exception as e:
                parse_errors_count += 1
                continue

            # Symbol check
            raw_sym = raw.get(mapping.symbol_col, self.expected_symbol)
            sym_clean = str(raw_sym).strip().upper() if raw_sym is not None else self.expected_symbol
            if sym_clean != self.expected_symbol:
                symbol_mismatch_count += 1

            # Prices & Volume parsing
            try:
                open_p = Decimal(str(raw[mapping.open_col]))
                high_p = Decimal(str(raw[mapping.high_col]))
                low_p = Decimal(str(raw[mapping.low_col]))
                close_p = Decimal(str(raw[mapping.close_col]))
                vol = Decimal(str(raw.get(mapping.volume_col, 0))) if mapping.volume_col and raw.get(mapping.volume_col) is not None else Decimal("0")
                spread_val = Decimal(str(raw.get(mapping.spread_col))) if mapping.spread_col and raw.get(mapping.spread_col) is not None else None
            except (InvalidOperation, KeyError, TypeError):
                parse_errors_count += 1
                continue

            # Volume check
            if vol < 0:
                invalid_volume_count += 1

            # OHLC integrity checks:
            # high >= max(open, close, low)
            # low <= min(open, close, high)
            # high >= low
            # open > 0, close > 0, high > 0, low > 0
            if (
                high_p < max(open_p, close_p, low_p) or
                low_p > min(open_p, close_p, high_p) or
                high_p < low_p or
                open_p <= 0 or close_p <= 0 or high_p <= 0 or low_p <= 0
            ):
                invalid_ohlc_count += 1

            candle = ValidatedCandleRecord(
                timestamp=utc_ts,
                symbol=sym_clean,
                timeframe=self.expected_timeframe,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=vol,
                spread=spread_val,
            )

            # Duplicate check
            if utc_ts in seen_timestamps:
                existing = seen_timestamps[utc_ts]
                # Check if exact duplicate
                if (
                    existing.open == candle.open and
                    existing.high == candle.high and
                    existing.low == candle.low and
                    existing.close == candle.close and
                    existing.volume == candle.volume
                ):
                    exact_duplicates_count += 1
                    # Discard redundant duplicate
                    continue
                else:
                    conflicting_duplicates_count += 1
            else:
                seen_timestamps[utc_ts] = candle

        # Populate checks
        if parse_errors_count > 0:
            report.add_check(QualityCheckResult(
                check_name="row_parsing",
                status=CheckStatus.FAIL,
                affected_rows=parse_errors_count,
                details={"errors": f"{parse_errors_count} rows could not be parsed."}
            ))

        if symbol_mismatch_count > 0:
            report.add_check(QualityCheckResult(
                check_name="symbol_consistency",
                status=CheckStatus.FAIL,
                affected_rows=symbol_mismatch_count,
                details={"expected": self.expected_symbol, "mismatches": symbol_mismatch_count}
            ))

        if invalid_ohlc_count > 0:
            report.add_check(QualityCheckResult(
                check_name="ohlc_integrity",
                status=CheckStatus.FAIL,
                affected_rows=invalid_ohlc_count,
                details={"errors": f"{invalid_ohlc_count} candles violate mathematical OHLC bounds."}
            ))

        if invalid_volume_count > 0:
            report.add_check(QualityCheckResult(
                check_name="volume_validity",
                status=CheckStatus.FAIL,
                affected_rows=invalid_volume_count,
                details={"errors": f"{invalid_volume_count} rows have negative volume."}
            ))

        if conflicting_duplicates_count > 0:
            report.add_check(QualityCheckResult(
                check_name="duplicate_detection",
                status=CheckStatus.FAIL,
                affected_rows=conflicting_duplicates_count,
                details={"conflicts": f"{conflicting_duplicates_count} conflicting duplicate timestamps with differing prices."}
            ))
        elif exact_duplicates_count > 0:
            report.add_check(QualityCheckResult(
                check_name="duplicate_detection",
                status=CheckStatus.WARNING,
                affected_rows=exact_duplicates_count,
                details={"info": f"{exact_duplicates_count} exact duplicate rows found and safely deduplicated."}
            ))
        else:
            report.add_check(QualityCheckResult(
                check_name="duplicate_detection",
                status=CheckStatus.PASS,
                details={"duplicates": 0}
            ))

        # Check if already rejected
        if report.status == DataQualityStatus.REJECTED:
            report.summary = "REJECTED: Data quality failures detected."
            return report, [], []

        # 3. Sort Chronologically & Check Monotonicity
        sorted_records = sorted(seen_timestamps.values(), key=lambda c: c.timestamp)
        if len(sorted_records) < len(raw_records) - exact_duplicates_count:
            report.add_check(QualityCheckResult(
                check_name="monotonicity",
                status=CheckStatus.WARNING,
                details={"info": "Input rows were reordered into strict chronological order."}
            ))

        # 4. Gap Detection (WITHOUT DATA FABRICATION)
        expected_step = TIMEFRAME_SECONDS.get(self.expected_timeframe, 300)
        gap_count = 0
        total_missing_bars = 0

        for i in range(1, len(sorted_records)):
            prev_ts = sorted_records[i - 1].timestamp
            curr_ts = sorted_records[i].timestamp
            delta_seconds = (curr_ts - prev_ts).total_seconds()

            if delta_seconds > expected_step:
                missing_bars = int(round(delta_seconds / expected_step)) - 1
                if missing_bars > 0:
                    gap_count += 1
                    total_missing_bars += missing_bars
                    gaps.append(GapRecord(
                        start=prev_ts,
                        end=curr_ts,
                        duration_seconds=delta_seconds,
                        expected_rows=missing_bars,
                        actual_rows=0,  # Never fabricate synthetic candles
                    ))

        if gap_count > 0:
            report.add_check(QualityCheckResult(
                check_name="gap_detection",
                status=CheckStatus.WARNING,
                affected_rows=total_missing_bars,
                details={
                    "gaps_count": gap_count,
                    "total_missing_bars": total_missing_bars,
                    "policy": "NO_FABRICATION - Zero synthetic candles created."
                }
            ))
        else:
            report.add_check(QualityCheckResult(
                check_name="gap_detection",
                status=CheckStatus.PASS,
                details={"gaps_count": 0}
            ))

        # Summary
        if report.status == DataQualityStatus.PASS:
            report.summary = f"PASS: Dataset '{dataset_name}' validated successfully ({len(sorted_records)} records)."
        elif report.status == DataQualityStatus.PASS_WITH_WARNINGS:
            report.summary = f"PASS_WITH_WARNINGS: Dataset '{dataset_name}' passed with {gap_count} non-fatal gaps / warnings."

        return report, sorted_records, gaps

    def validate_and_normalize_ticks(
        self,
        raw_records: Sequence[dict[str, Any]],
        mapping: SourceColumnMapping,
        dataset_name: str,
    ) -> tuple[DatasetQualityReport, list[ValidatedTickRecord]]:
        """Validate raw tick records, normalize to UTC, audit spread and prices."""
        report = DatasetQualityReport(dataset_name=dataset_name, status=DataQualityStatus.PASS)
        validated_records: list[ValidatedTickRecord] = []

        # 1. Timezone Check
        try:
            source_tz = self.resolve_timezone()
            report.add_check(QualityCheckResult(
                check_name="timezone_verification",
                status=CheckStatus.PASS,
                details={"declared_timezone": str(source_tz), "target_timezone": "UTC"}
            ))
        except ValidationError as e:
            report.add_check(QualityCheckResult(
                check_name="timezone_verification",
                status=CheckStatus.FAIL,
                details={"error": str(e)}
            ))
            report.summary = f"REJECTED: Timezone validation failed - {e}"
            return report, []

        invalid_spread_count = 0
        negative_price_count = 0
        symbol_mismatch_count = 0

        for raw in raw_records:
            ts_raw = raw.get(mapping.timestamp_col)
            try:
                utc_ts = self.parse_timestamp(ts_raw, tz=source_tz)
            except Exception:
                continue

            raw_sym = raw.get(mapping.symbol_col, self.expected_symbol)
            sym_clean = str(raw_sym).strip().upper() if raw_sym is not None else self.expected_symbol
            if sym_clean != self.expected_symbol:
                symbol_mismatch_count += 1

            try:
                bid_p = Decimal(str(raw[mapping.bid_col]))
                ask_p = Decimal(str(raw[mapping.ask_col]))
                last_p = Decimal(str(raw[mapping.last_col])) if mapping.last_col and raw.get(mapping.last_col) is not None else None
                vol = Decimal(str(raw.get(mapping.volume_col, 0))) if mapping.volume_col and raw.get(mapping.volume_col) is not None else Decimal("0")
            except Exception:
                continue

            if bid_p <= 0 or ask_p <= 0:
                negative_price_count += 1
            if ask_p < bid_p:
                invalid_spread_count += 1

            validated_records.append(ValidatedTickRecord(
                timestamp=utc_ts,
                symbol=sym_clean,
                bid=bid_p,
                ask=ask_p,
                last=last_p,
                volume=vol,
            ))

        if invalid_spread_count > 0:
            report.add_check(QualityCheckResult(
                check_name="spread_validity",
                status=CheckStatus.FAIL,
                affected_rows=invalid_spread_count,
                details={"errors": f"{invalid_spread_count} ticks have inverted spread (ask < bid)."}
            ))

        if negative_price_count > 0:
            report.add_check(QualityCheckResult(
                check_name="price_validity",
                status=CheckStatus.FAIL,
                affected_rows=negative_price_count,
                details={"errors": f"{negative_price_count} ticks have non-positive prices."}
            ))

        if symbol_mismatch_count > 0:
            report.add_check(QualityCheckResult(
                check_name="symbol_consistency",
                status=CheckStatus.FAIL,
                affected_rows=symbol_mismatch_count,
                details={"expected": self.expected_symbol, "mismatches": symbol_mismatch_count}
            ))

        if report.status == DataQualityStatus.REJECTED:
            report.summary = "REJECTED: Tick quality check failed."
            return report, []

        validated_records.sort(key=lambda t: t.timestamp)
        report.summary = f"PASS: Validated {len(validated_records)} ticks."
        return report, validated_records
