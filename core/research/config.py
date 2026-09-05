"""
Explicit configuration and deterministic config hashing for Historical Research Engine V1.
Zero hidden defaults. All research runs are permanently bound to their config hash.
"""

import hashlib
import json
from decimal import Decimal
from typing import Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class ResearchConfig(BaseModel):
    """
    Explicit, auditable configuration for research dataset generation.
    Every parameter is captured in the deterministic config_hash.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Market Structure
    swing_left_bars: int = 2
    swing_right_bars: int = 2
    bos_displacement_atr_mult: Decimal = Decimal("0.10")
    structure_displacement_atr_mult: Decimal = Decimal("0.10")

    # Features & ATR
    atr_period: int = 14
    baseline_window: int = 100
    fallback_atr: Decimal = Decimal("0.00100")

    # Liquidity & Tolerances
    equal_high_low_tolerance: Decimal = Decimal("0.00010")
    sweep_min_atr_mult: Decimal = Decimal("0.05")
    sweep_max_atr_mult: Decimal = Decimal("0.50")
    sweep_return_window: int = 3
    rejection_displacement_atr_mult: Decimal = Decimal("0.30")
    acceptance_candle_count: int = 2
    acceptance_follow_through_atr_mult: Decimal = Decimal("0.30")

    # Compression & Expansion (S05)
    compression_bars: int = 10
    compression_atr_percentile: Decimal = Decimal("20.0")
    compression_range_percentile: Decimal = Decimal("25.0")
    expansion_range_multiplier: Decimal = Decimal("1.5")
    expansion_volatility_zscore: Decimal = Decimal("1.5")

    # Sessions
    session_configuration: Dict[str, Dict[str, str]] = Field(
        default_factory=lambda: {
            "ASIA": {"start": "00:00", "end": "08:00"},
            "LONDON": {"start": "08:00", "end": "16:00"},
            "NEW_YORK": {"start": "13:00", "end": "21:00"},
        }
    )

    # Splits (strictly chronological)
    in_sample_ratio: float = 0.60
    validation_ratio: float = 0.20
    out_of_sample_ratio: float = 0.20

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Produce a canonical dictionary with deterministic formatting."""
        data = self.model_dump()
        # Convert Decimal values to fixed-precision string representation
        def _canonicalize(val: Any) -> Any:
            if isinstance(val, Decimal):
                return str(val)
            if isinstance(val, float):
                return round(val, 6)
            if isinstance(val, dict):
                return {k: _canonicalize(v) for k, v in sorted(val.items())}
            if isinstance(val, list):
                return [_canonicalize(v) for v in val]
            return val

        return {k: _canonicalize(v) for k, v in sorted(data.items())}

    def get_config_hash(self) -> str:
        """Compute SHA-256 hash of the canonical JSON representation."""
        canonical = self.to_canonical_dict()
        serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
