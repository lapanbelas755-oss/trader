"""
Configuration specification for Backtest Engine V1.
Deterministic, canonical hashing, explicit parameter definitions.
"""

from decimal import Decimal
import hashlib
import json
from typing import Any, Dict
from pydantic import BaseModel, ConfigDict, Field


class BacktestConfig(BaseModel):
    """
    Explicit configuration parameters for backtesting setup occurrences.
    Strictly avoids hidden defaults.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    target_r: Decimal = Field(default=Decimal("2.0"), description="Baseline target R multiple")
    timeout_bars: int = Field(default=3, description="Maximum closed M5 bars trade may remain active before timeout")
    sl_buffer_pips: Decimal = Field(default=Decimal("0.00010"), description="Buffer added beyond structural extreme")
    commission_per_trade: Decimal = Field(default=Decimal("0.0"), description="Commission per round-turn trade")
    slippage_pips: Decimal = Field(default=Decimal("0.0"), description="Simulated execution slippage in price units")
    spread_fallback_pips: Decimal = Field(default=Decimal("0.00010"), description="Fallback spread when Bid/Ask is missing")
    collision_policy: str = Field(default="MAX_ONE_ACTIVE_TRADE_PER_SYMBOL", description="Collision policy for overlapping trades")
    max_active_trades: int = Field(default=1, description="Maximum active trades per symbol")

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Returns sorted, serializable representation for cryptographic hashing."""
        return {
            "collision_policy": str(self.collision_policy),
            "commission_per_trade": str(self.commission_per_trade),
            "max_active_trades": int(self.max_active_trades),
            "slippage_pips": str(self.slippage_pips),
            "sl_buffer_pips": str(self.sl_buffer_pips),
            "spread_fallback_pips": str(self.spread_fallback_pips),
            "target_r": str(self.target_r),
            "timeout_bars": int(self.timeout_bars),
        }

    def get_config_hash(self) -> str:
        """Computes deterministic SHA-256 hash of the configuration."""
        canonical_json = json.dumps(self.to_canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
