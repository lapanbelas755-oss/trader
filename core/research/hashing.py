"""
Deterministic, canonical hashing utilities for datasets, candle series, and setup occurrences.
Ensures identical inputs and configurations always produce bit-for-bit identical hashes.
"""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence
from core.setups.common import get_val, ensure_utc


def hash_canonical_json(obj: Any) -> str:
    """Computes SHA-256 hash of a JSON-serializable structure with sorted keys."""
    def _normalize(val: Any) -> Any:
        if isinstance(val, (datetime,)):
            utc_dt = ensure_utc(val)
            return utc_dt.isoformat()
        if isinstance(val, Decimal):
            return str(val)
        if isinstance(val, float):
            return round(val, 6)
        if isinstance(val, dict):
            return {str(k): _normalize(v) for k, v in sorted(val.items())}
        if isinstance(val, (list, tuple)):
            return [_normalize(v) for v in val]
        return val

    normalized = _normalize(obj)
    serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def hash_candles(candles: Sequence[Any]) -> str:
    """
    Computes deterministic SHA-256 hash of a chronological candle sequence.
    Sorts strictly by timestamp and standardizes financial fields.
    """
    if not candles:
        return hashlib.sha256(b"EMPTY_CANDLE_SET").hexdigest()

    sorted_candles = sorted(candles, key=lambda c: ensure_utc(get_val(c, "timestamp")))
    canonical_items = []

    for c in sorted_candles:
        ts = ensure_utc(get_val(c, "timestamp"))
        o = Decimal(str(get_val(c, "open"))).quantize(Decimal("0.00001"))
        h = Decimal(str(get_val(c, "high"))).quantize(Decimal("0.00001"))
        l = Decimal(str(get_val(c, "low"))).quantize(Decimal("0.00001"))
        close_p = Decimal(str(get_val(c, "close"))).quantize(Decimal("0.00001"))
        vol = int(get_val(c, "tick_volume", 0))

        canonical_items.append({
            "ts": ts.isoformat(),
            "o": str(o),
            "h": str(h),
            "l": str(l),
            "c": str(close_p),
            "v": vol,
        })

    return hash_canonical_json(canonical_items)


def hash_occurrences(occurrences: Sequence[Any]) -> str:
    """
    Computes deterministic SHA-256 hash of research setup occurrences.
    Excludes random/internal database IDs so identical setup findings yield identical hashes.
    """
    if not occurrences:
        return hashlib.sha256(b"EMPTY_OCCURRENCES").hexdigest()

    canonical_items = []
    for occ in occurrences:
        ts = ensure_utc(get_val(occ, "timestamp"))
        code = str(get_val(occ, "setup_code"))
        status = str(get_val(occ, "status"))
        direction = str(get_val(occ, "direction"))
        split = str(get_val(occ, "split_type"))
        ev_snapshot = get_val(occ, "evidence_snapshot") or {}

        canonical_items.append({
            "ts": ts.isoformat(),
            "code": code,
            "status": status,
            "direction": direction,
            "split": split,
            "evidence": ev_snapshot,
        })

    # Sort deterministically by (ts, code, status, direction)
    canonical_items.sort(key=lambda x: (x["ts"], x["code"], x["status"], x["direction"]))
    return hash_canonical_json(canonical_items)
