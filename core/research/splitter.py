"""
Chronological dataset splitter for Historical Research Engine V1.
Enforces strictly sequential, non-overlapping train / validation / out-of-sample splits.
Zero random shuffling. Zero temporal leakage.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from core.research.contract import SplitType
from core.setups.common import get_val, ensure_utc


class ChronologicalSplitter:
    """
    Partitions time series candles into chronological subsets:
    IN_SAMPLE -> VALIDATION -> OUT_OF_SAMPLE.
    """

    def __init__(
        self,
        in_sample_ratio: float = 0.60,
        validation_ratio: float = 0.20,
        out_of_sample_ratio: float = 0.20,
    ):
        total = in_sample_ratio + validation_ratio + out_of_sample_ratio
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Split ratios must sum to 1.0 (got {total})")
        self.in_sample_ratio = in_sample_ratio
        self.validation_ratio = validation_ratio
        self.out_of_sample_ratio = out_of_sample_ratio

    def split_candles(
        self,
        candles: Sequence[Any],
    ) -> Tuple[List[Any], List[Any], List[Any]]:
        """
        Splits candles sequentially into (in_sample, validation, out_of_sample).
        Enforces chronological sorting beforehand.
        """
        if not candles:
            return [], [], []

        sorted_candles = sorted(candles, key=lambda c: ensure_utc(get_val(c, "timestamp")))
        n = len(sorted_candles)

        idx_val = int(n * self.in_sample_ratio)
        idx_oos = int(n * (self.in_sample_ratio + self.validation_ratio))

        in_sample = sorted_candles[:idx_val]
        validation = sorted_candles[idx_val:idx_oos]
        out_of_sample = sorted_candles[idx_oos:]

        # Validate non-overlapping chronological boundaries
        if in_sample and validation:
            max_in = ensure_utc(get_val(in_sample[-1], "timestamp"))
            min_val = ensure_utc(get_val(validation[0], "timestamp"))
            assert max_in < min_val, f"Boundary violation: IN_SAMPLE end ({max_in}) >= VALIDATION start ({min_val})"

        if validation and out_of_sample:
            max_val = ensure_utc(get_val(validation[-1], "timestamp"))
            min_oos = ensure_utc(get_val(out_of_sample[0], "timestamp"))
            assert max_val < min_oos, f"Boundary violation: VALIDATION end ({max_val}) >= OOS start ({min_oos})"

        return in_sample, validation, out_of_sample

    def get_split_boundaries(
        self,
        candles: Sequence[Any],
    ) -> Dict[str, Tuple[Optional[datetime], Optional[datetime]]]:
        """Returns the exact (start_time, end_time) tuple for each split."""
        ins, val, oos = self.split_candles(candles)

        def _bounds(subset: List[Any]) -> Tuple[Optional[datetime], Optional[datetime]]:
            if not subset:
                return None, None
            return (
                ensure_utc(get_val(subset[0], "timestamp")),
                ensure_utc(get_val(subset[-1], "timestamp")),
            )

        return {
            SplitType.IN_SAMPLE.value: _bounds(ins),
            SplitType.VALIDATION.value: _bounds(val),
            SplitType.OUT_OF_SAMPLE.value: _bounds(oos),
        }

    def determine_split_type(
        self,
        timestamp: datetime,
        boundaries: Dict[str, Tuple[Optional[datetime], Optional[datetime]]],
    ) -> SplitType:
        """Determines which split a specific timestamp falls into."""
        ts = ensure_utc(timestamp)

        ins_start, ins_end = boundaries.get(SplitType.IN_SAMPLE.value, (None, None))
        val_start, val_end = boundaries.get(SplitType.VALIDATION.value, (None, None))
        oos_start, oos_end = boundaries.get(SplitType.OUT_OF_SAMPLE.value, (None, None))

        if ins_start and ins_end and ins_start <= ts <= ins_end:
            return SplitType.IN_SAMPLE
        if val_start and val_end and val_start <= ts <= val_end:
            return SplitType.VALIDATION
        if oos_start and oos_end and oos_start <= ts <= oos_end:
            return SplitType.OUT_OF_SAMPLE

        # Fallback based on relative positioning
        if ins_end and ts <= ins_end:
            return SplitType.IN_SAMPLE
        if val_end and ts <= val_end:
            return SplitType.VALIDATION
        return SplitType.OUT_OF_SAMPLE
