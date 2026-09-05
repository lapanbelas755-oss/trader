"""Generic Data Source Adapters for Trader Machine V1.
Supports CSV, JSON, and in-memory streams without assuming broker-specific formats.
"""
from abc import ABC, abstractmethod
import csv
import json
from pathlib import Path
from typing import Any, Iterator, Union

class DataSourceAdapter(ABC):
    """Abstract interface for raw market data input sources."""

    @abstractmethod
    def read_records(self, source: Union[str, Path, Any]) -> Iterator[dict[str, Any]]:
        """Yield raw unvalidated dictionary records from the source."""
        pass


class CSVAdapter(DataSourceAdapter):
    """Generic CSV adapter with optional column mapping."""

    def __init__(self, column_mapping: dict[str, str] | None = None, delimiter: str = ","):
        """
        Args:
            column_mapping: Dictionary mapping source column names to standard keys
                            e.g. {'Time': 'timestamp', 'Bid': 'bid', 'Ask': 'ask'}
            delimiter: CSV field separator.
        """
        self.column_mapping = column_mapping or {}
        self.delimiter = delimiter

    def read_records(self, source: Union[str, Path]) -> Iterator[dict[str, Any]]:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"CSV source not found: {path}")

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            for row in reader:
                mapped_row: dict[str, Any] = {}
                for k, v in row.items():
                    if k is None:
                        continue
                    clean_k = k.strip()
                    # Apply column mapping if defined, else keep lowercase key
                    target_key = self.column_mapping.get(clean_k, clean_k.lower())
                    mapped_row[target_key] = v.strip() if isinstance(v, str) else v
                yield mapped_row


class JSONAdapter(DataSourceAdapter):
    """Generic JSON and JSON Lines adapter."""

    def read_records(self, source: Union[str, Path]) -> Iterator[dict[str, Any]]:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"JSON source not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return

            # Check if JSON Lines (starts with { on each line) or standard JSON Array (starts with [)
            if content.startswith("["):
                records = json.loads(content)
                for item in records:
                    if isinstance(item, dict):
                        yield item
            else:
                # Process as JSON lines
                f.seek(0)
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        item = json.loads(line_str)
                        if isinstance(item, dict):
                            yield item


class InMemoryAdapter(DataSourceAdapter):
    """Adapter for in-memory lists of dictionary records (used for streaming or tests)."""

    def __init__(self, records: list[dict[str, Any]]):
        self.records = records

    def read_records(self, source: Any = None) -> Iterator[dict[str, Any]]:
        for record in self.records:
            yield dict(record)
