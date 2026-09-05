"""
Configuration specification for Statistical Edge Engine V1.
Deterministic random seeding, explicit parameter thresholds, and canonical hashing.
"""

from decimal import Decimal
import hashlib
import json
from typing import Any, Dict
from pydantic import BaseModel, ConfigDict, Field


class StatisticalConfig(BaseModel):
    """
    Explicit parameters for statistical validation, intervals, and edge classification.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    bootstrap_iterations: int = Field(default=10000, description="Iterations for deterministic bootstrap resampling")
    monte_carlo_iterations: int = Field(default=1000, description="Iterations for trade permutation resampling")
    confidence_level: Decimal = Field(default=Decimal("0.95"), description="Two-sided confidence level")
    min_sample_preliminary: int = Field(default=30, description="Minimum sample size for preliminary evaluation")
    min_sample_relevant: int = Field(default=100, description="Minimum sample size for candidate relevance")
    oos_degraded_ratio: Decimal = Field(default=Decimal("0.60"), description="OOS/IS ratio below which edge is degraded")
    oos_collapsed_ratio: Decimal = Field(default=Decimal("0.00"), description="OOS/IS ratio at or below which edge collapsed")
    max_acceptable_dd_r: Decimal = Field(default=Decimal("15.0"), description="Max drawdown in R acceptable for robust edge")
    spread_low_pips: Decimal = Field(default=Decimal("0.00008"), description="Upper bound for LOW spread bucket")
    spread_normal_pips: Decimal = Field(default=Decimal("0.00018"), description="Upper bound for NORMAL spread bucket")
    spread_high_pips: Decimal = Field(default=Decimal("0.00035"), description="Upper bound for HIGH spread bucket")

    def derive_seed(self, dataset_hash: str, backtest_config_hash: str, setup_code: str) -> int:
        """Derives a deterministic integer seed from component hashes."""
        payload = f"{dataset_hash}_{backtest_config_hash}_{setup_code}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        # Use first 8 bytes as unsigned integer seed (0 to 2^32 - 1)
        return int(digest[:8], 16)

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Canonical dictionary representation for hashing."""
        return {
            "bootstrap_iterations": int(self.bootstrap_iterations),
            "confidence_level": str(self.confidence_level),
            "max_acceptable_dd_r": str(self.max_acceptable_dd_r),
            "min_sample_preliminary": int(self.min_sample_preliminary),
            "min_sample_relevant": int(self.min_sample_relevant),
            "monte_carlo_iterations": int(self.monte_carlo_iterations),
            "oos_collapsed_ratio": str(self.oos_collapsed_ratio),
            "oos_degraded_ratio": str(self.oos_degraded_ratio),
            "spread_high_pips": str(self.spread_high_pips),
            "spread_low_pips": str(self.spread_low_pips),
            "spread_normal_pips": str(self.spread_normal_pips),
        }

    def get_config_hash(self) -> str:
        """Computes deterministic SHA-256 hash of configuration."""
        canonical_json = json.dumps(self.to_canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
