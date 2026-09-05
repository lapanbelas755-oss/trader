"""
Common utilities, attribute accessors, and execution condition helpers for Setup Detector Engine V1.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence
from core.setups.contract import SetupDirection


def get_val(obj: Any, key: str, default: Any = None) -> Any:
    """Safely extract field value from dict, Pydantic model, or class instance."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def evaluate_execution_conditions(
    candle: Any,
    max_acceptable_spread: Decimal = Decimal("3.0"),
) -> tuple[bool, str]:
    """
    Evaluates whether execution conditions at the current bar are acceptable.
    Does NOT implement Risk Firewall rules; checks spread and market availability only.
    """
    spread = get_val(candle, "spread")
    if spread is not None:
        spread_dec = Decimal(str(spread))
        if spread_dec > max_acceptable_spread:
            return False, f"SPREAD_ABOVE_THRESHOLD_{spread_dec}"
    return True, "ACCEPTABLE"


def check_htf_alignment(
    setup_direction: SetupDirection,
    htf_direction: Optional[str],
) -> tuple[bool, str]:
    """
    Checks whether Higher Timeframe (H1/M15) strongly opposes the setup.
    If setup is BULLISH and HTF is BEARISH -> strongly opposed (False).
    If setup is BEARISH and HTF is BULLISH -> strongly opposed (False).
    Otherwise (ALIGNED, MIXED, TRANSITION, UNDEFINED, UNKNOWN) -> not strongly opposed (True).
    """
    if not htf_direction:
        return True, "HTF_NEUTRAL"

    htf_dir = str(htf_direction).strip().upper()
    if setup_direction == SetupDirection.BULLISH:
        if htf_dir in ("BEARISH", "ALIGNED_BEARISH"):
            return False, "HTF_OPPOSES_BULLISH"
        return True, f"HTF_{htf_dir}"
    elif setup_direction == SetupDirection.BEARISH:
        if htf_dir in ("BULLISH", "ALIGNED_BULLISH"):
            return False, "HTF_OPPOSES_BEARISH"
        return True, f"HTF_{htf_dir}"

    return True, "HTF_UNDEFINED"
