"""Real Market Data Acquisition and Dataset Validation V1 package."""
from core.data_source.contract import (
    GLOBAL_LIQUIDITY_DISCLAIMER,
    TICK_VOLUME_DISCLAIMER,
    CheckStatus,
    DataFormat,
    DataQualityStatus,
    DatasetProvenance,
    DatasetQualityReport,
    GapRecord,
    MarketDataType,
    QualityCheckResult,
    SourceType,
    ValidatedCandleRecord,
    ValidatedTickRecord,
)
from core.data_source.engine import MarketDataAcquisitionEngine
from core.data_source.hashing import CanonicalHasher
from core.data_source.mapping import (
    DUKASCOPY_CSV_MAPPING,
    GENERIC_OHLC_MAPPING,
    GENERIC_TICK_MAPPING,
    MT5_EXPORT_OHLC_MAPPING,
    MappingError,
    SourceColumnMapping,
)
from core.data_source.provenance import ProvenanceManager
from core.data_source.registry import DatasetRegistry
from core.data_source.validator import MarketDataValidator, ValidationError
from core.data_source.importer import MarketDataImporter
from core.data_source.storage import StorageSafetyChecker, StorageSafetyReport, InsufficientStorageError
from core.data_source.staged import (
    DataProvider,
    DatasetClass,
    AcquisitionStage,
    AcquisitionManifest,
    DatasetPartitioner,
    FileHasher,
    StagedAcquisitionManager,
    ProviderSeparationError,
    PROVIDER_SEMANTICS,
)
from core.data_source.cross_val import (
    CrossValidationComparator,
    CrossValidationReport,
    FeedCharacteristics,
    SpreadStatistics,
    CROSS_VALIDATION_DISCLAIMER,
)

__all__ = [
    "DataFormat",
    "SourceType",
    "DataQualityStatus",
    "CheckStatus",
    "MarketDataType",
    "TICK_VOLUME_DISCLAIMER",
    "GLOBAL_LIQUIDITY_DISCLAIMER",
    "QualityCheckResult",
    "DatasetQualityReport",
    "GapRecord",
    "ValidatedCandleRecord",
    "ValidatedTickRecord",
    "DatasetProvenance",
    "CanonicalHasher",
    "SourceColumnMapping",
    "MappingError",
    "GENERIC_OHLC_MAPPING",
    "MT5_EXPORT_OHLC_MAPPING",
    "DUKASCOPY_CSV_MAPPING",
    "GENERIC_TICK_MAPPING",
    "MarketDataValidator",
    "ValidationError",
    "ProvenanceManager",
    "DatasetRegistry",
    "MarketDataAcquisitionEngine",
    "MarketDataImporter",
    "StorageSafetyChecker",
    "StorageSafetyReport",
    "InsufficientStorageError",
    "DataProvider",
    "DatasetClass",
    "AcquisitionStage",
    "AcquisitionManifest",
    "DatasetPartitioner",
    "FileHasher",
    "StagedAcquisitionManager",
    "ProviderSeparationError",
    "PROVIDER_SEMANTICS",
    "CrossValidationComparator",
    "CrossValidationReport",
    "FeedCharacteristics",
    "SpreadStatistics",
    "CROSS_VALIDATION_DISCLAIMER",
]
