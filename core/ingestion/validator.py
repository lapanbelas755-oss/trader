"""Validation layer using Pydantic for raw market tick records."""
from typing import Any
from pydantic import ValidationError
from core.ingestion.contract import ValidatedTickRecord, RejectedRecord

class ValidationResult:
    """Stores batches of valid and rejected records with explicit rejection reasons."""
    def __init__(self):
        self.valid_records: list[ValidatedTickRecord] = []
        self.rejected_records: list[RejectedRecord] = []

    @property
    def total_count(self) -> int:
        return len(self.valid_records) + len(self.rejected_records)

    @property
    def valid_count(self) -> int:
        return len(self.valid_records)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_records)


class TickValidator:
    """Validates normalized tick dictionaries against Pydantic schema and market laws."""

    def validate_record(self, record_index: int, data: dict[str, Any]) -> ValidatedTickRecord | RejectedRecord:
        # Check market law: ask >= bid (cross-check before/after instantiation)
        try:
            validated = ValidatedTickRecord(**data)
            # Market law check: ask must not be strictly less than bid (inverted spread)
            if validated.ask < validated.bid:
                return RejectedRecord(
                    record_index=record_index,
                    raw_data=data,
                    reason=f"Inverted spread: ask ({validated.ask}) < bid ({validated.bid})",
                    category="PRICE",
                )
            return validated
        except ValidationError as e:
            # Extract error summary from Pydantic
            errors = e.errors()
            first_err = errors[0] if errors else {}
            loc = ".".join(str(l) for l in first_err.get("loc", []))
            msg = first_err.get("msg", str(e))
            category = "PRICE" if "bid" in loc or "ask" in loc else (
                "TIMESTAMP" if "timestamp" in loc else (
                    "VOLUME" if "volume" in loc else "SCHEMA"
                )
            )
            return RejectedRecord(
                record_index=record_index,
                raw_data=data,
                reason=f"Validation failed at field '{loc}': {msg}",
                category=category,
            )
        except Exception as e:
            return RejectedRecord(
                record_index=record_index,
                raw_data=data,
                reason=f"Unexpected validation error: {str(e)}",
                category="SCHEMA",
            )

    def validate_batch(self, records: list[dict[str, Any]]) -> ValidationResult:
        """Validate a list of normalized dictionaries."""
        result = ValidationResult()
        for idx, record in enumerate(records):
            val_or_rej = self.validate_record(idx, record)
            if isinstance(val_or_rej, ValidatedTickRecord):
                result.valid_records.append(val_or_rej)
            else:
                result.rejected_records.append(val_or_rej)
        return result
