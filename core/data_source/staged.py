"""Staged Historical Dataset Acquisition & Provider Partitioning Manager V1.
Enforces strict provider separation, dataset classifications, incremental acquisition stages,
partition paths, per-file and dataset-level SHA-256 manifests, and derived provenance lineage.
"""
from datetime import datetime, timezone
from enum import Enum
import hashlib
from pathlib import Path
from typing import Any, Optional, Sequence, Union
from pydantic import BaseModel, ConfigDict, Field

from core.data_source.contract import MarketDataType


class DataProvider(str, Enum):
    """Supported real historical market data sources with explicit semantics."""
    DUKASCOPY = "DUKASCOPY"
    TRUEFX = "TRUEFX"
    HISTDATA = "HISTDATA"
    USER_SUPPLIED = "USER_SUPPLIED"
    UNKNOWN = "UNKNOWN"


PROVIDER_SEMANTICS: dict[DataProvider, str] = {
    DataProvider.DUKASCOPY: (
        "Dukascopy: Historical broker quote feed containing Bid/Ask prices and observed tick frequency. "
        "Represents Dukascopy ECN marketplace liquidity; not global FX aggregate volume."
    ),
    DataProvider.TRUEFX: (
        "TrueFX: Indicative institutional top-of-book tick quotes sourced from major market makers. "
        "Filtered dealable interbank snapshot; provider-specific liquidity."
    ),
    DataProvider.HISTDATA: (
        "HistData: Provider-specific retail broker tick/M1 historical archive. "
        "Useful for reference and preliminary validation; subject to broker-specific filtering."
    ),
    DataProvider.USER_SUPPLIED: (
        "User-supplied external historical dataset. Origin provider unverified."
    ),
    DataProvider.UNKNOWN: (
        "Unknown/unverified external data provider. Origin unknown."
    ),
}


class DatasetClass(str, Enum):
    """Dataset functional classification within the research architecture."""
    PRIMARY_RESEARCH = "PRIMARY_RESEARCH"
    CROSS_VALIDATION = "CROSS_VALIDATION"
    REFERENCE_ONLY = "REFERENCE_ONLY"


class AcquisitionStage(str, Enum):
    """Controlled incremental data acquisition milestones."""
    STAGE_1 = "STAGE_1"  # 3 months
    STAGE_2 = "STAGE_2"  # 6 months
    STAGE_3 = "STAGE_3"  # 1 year
    STAGE_4 = "STAGE_4"  # 3 years
    STAGE_5 = "STAGE_5"  # 5+ years


STAGE_MIN_DAYS: dict[AcquisitionStage, int] = {
    AcquisitionStage.STAGE_1: 80,     # ~3 months (~90 days minus weekends/holidays)
    AcquisitionStage.STAGE_2: 170,    # ~6 months
    AcquisitionStage.STAGE_3: 350,    # ~1 year
    AcquisitionStage.STAGE_4: 1050,   # ~3 years
    AcquisitionStage.STAGE_5: 1800,   # ~5+ years
}


class ProviderSeparationError(ValueError):
    """Raised when records or files from differing data providers are mixed together."""
    pass


class AcquisitionManifest(BaseModel):
    """Formal audit manifest specifying a staged historical dataset."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataset_id: str
    provider: DataProvider
    dataset_class: DatasetClass
    symbol: str
    data_type: MarketDataType
    timeframe: str
    start_timestamp: Optional[datetime] = None
    end_timestamp: Optional[datetime] = None
    timezone: str = "UTC"
    file_count: int
    total_bytes: int
    row_count: int
    content_hash: str
    file_hashes: dict[str, str] = Field(default_factory=dict)
    source_description: str
    volume_semantics: str
    price_semantics: str
    bid_available: bool
    ask_available: bool
    spread_available: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parent_source_dataset_id: Optional[str] = None  # Provenance lineage for derived data


class DatasetPartitioner:
    """Computes and validates canonical directory structures for real market archives."""

    @staticmethod
    def build_partition_path(
        base_dir: Union[str, Path],
        provider: DataProvider,
        symbol: str,
        data_type: Union[MarketDataType, str],
        year: int,
        month: int,
        day: Optional[int] = None,
    ) -> Path:
        """Construct canonical partition path:
        base_dir/{provider}/{symbol}/{data_type}/{year}/{month:02d}/[day:02d]
        """
        type_str = data_type.value.lower() if isinstance(data_type, MarketDataType) else str(data_type).lower()
        path = Path(base_dir) / provider.value.lower() / symbol.upper() / type_str / f"{year:04d}" / f"{month:02d}"
        if day is not None:
            path = path / f"{day:02d}"
        return path


class FileHasher:
    """Computes SHA-256 for individual files in a streaming, memory-safe manner."""

    @staticmethod
    def hash_file(file_path: Union[str, Path], chunk_size: int = 65536) -> str:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Cannot hash missing file: {p}")
        hasher = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()


class StagedAcquisitionManager:
    """Coordinates staged dataset definitions, provider isolation, and manifest creation."""

    @staticmethod
    def validate_provider_separation(providers: Sequence[Union[DataProvider, str]]) -> DataProvider:
        """Enforce strict provider isolation. Rejects mixing differing providers."""
        if not providers:
            raise ValueError("No providers specified.")
        unique_providers = {
            p if isinstance(p, DataProvider) else DataProvider(str(p).upper())
            for p in providers
        }
        if len(unique_providers) > 1:
            names = sorted([p.value for p in unique_providers])
            raise ProviderSeparationError(
                f"PROVIDER SEPARATION VIOLATION: Cannot merge multiple market feeds into a single dataset: {names}. "
                f"Different providers represent distinct feeds and liquidity pools and must remain strictly segregated."
            )
        return next(iter(unique_providers))

    @staticmethod
    def evaluate_stage(start_ts: datetime, end_ts: datetime) -> AcquisitionStage:
        """Determine which acquisition stage is fulfilled by the given time span."""
        duration_days = (end_ts - start_ts).total_seconds() / 86400.0
        if duration_days >= STAGE_MIN_DAYS[AcquisitionStage.STAGE_5]:
            return AcquisitionStage.STAGE_5
        elif duration_days >= STAGE_MIN_DAYS[AcquisitionStage.STAGE_4]:
            return AcquisitionStage.STAGE_4
        elif duration_days >= STAGE_MIN_DAYS[AcquisitionStage.STAGE_3]:
            return AcquisitionStage.STAGE_3
        elif duration_days >= STAGE_MIN_DAYS[AcquisitionStage.STAGE_2]:
            return AcquisitionStage.STAGE_2
        else:
            return AcquisitionStage.STAGE_1

    @classmethod
    def create_manifest(
        cls,
        dataset_id: str,
        provider: DataProvider,
        dataset_class: DatasetClass,
        symbol: str,
        data_type: MarketDataType,
        timeframe: str,
        files: Sequence[Union[str, Path]],
        content_hash: str,
        row_count: int,
        start_ts: Optional[datetime],
        end_ts: Optional[datetime],
        timezone_str: str = "UTC",
        parent_source_dataset_id: Optional[str] = None,
        bid_available: bool = True,
        ask_available: bool = True,
        spread_available: bool = True,
    ) -> AcquisitionManifest:
        """Generate a complete acquisition manifest for an acquired file collection."""
        if timezone_str.upper() not in ("UTC", "GMT", "Z"):
            raise ValueError(f"Unknown or non-UTC timezone '{timezone_str}'. Staged manifests require explicit UTC alignment.")

        file_hashes: dict[str, str] = {}
        total_bytes = 0
        for f in files:
            p = Path(f)
            file_hashes[p.name] = FileHasher.hash_file(p)
            total_bytes += p.stat().st_size

        return AcquisitionManifest(
            dataset_id=dataset_id,
            provider=provider,
            dataset_class=dataset_class,
            symbol=symbol.upper(),
            data_type=data_type,
            timeframe=timeframe.upper(),
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            timezone="UTC",
            file_count=len(files),
            total_bytes=total_bytes,
            row_count=row_count,
            content_hash=content_hash,
            file_hashes=file_hashes,
            source_description=PROVIDER_SEMANTICS[provider],
            volume_semantics="Tick count activity observed at provider feed. Not traded volume.",
            price_semantics="Broker quote prices. May exhibit broker-specific spreads and tick timing.",
            bid_available=bid_available,
            ask_available=ask_available,
            spread_available=spread_available,
            parent_source_dataset_id=parent_source_dataset_id,
        )
