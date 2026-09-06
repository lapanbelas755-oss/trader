"""
Trader Machine — XAUUSD Setup Logging & Persistence Engine V1.
Records every detected market setup (both Actionable Signals and NO_TRADE events).

Adheres to Master Instruction (AGENTS.MD Law #14, #15) & User Specification (Section M):
PENTING:
Simpan juga setup yang akhirnya NO_TRADE.
Data NO_TRADE sangat berharga untuk statistical edge analysis & backtesting.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "setups"


@dataclass
class XAUUSDSetupRecord:
    """Standardized record of an evaluated XAU/USD market setup."""
    timestamp: str
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    level: float = 0.0
    level_type: str = "SWING"
    breakout_direction: str = "NONE"      # BULLISH | BEARISH | NONE
    breakout_category: str = "NONE"       # WICK_BREAKOUT | WEAK_BREAKOUT | VALID_BREAKOUT | STRONG_BREAKOUT | NONE
    atr: float = 0.0
    spread: float = 0.0
    momentum: str = "WEAK"
    volatility: str = "NORMAL"
    retest: str = "NONE"
    rr: str = "N/A"
    rr_ratio: float = 0.0
    score: int = 0
    score_breakdown: Dict[str, int] = field(default_factory=dict)
    signal: str = "NO_TRADE"              # BUY | SELL | NO_TRADE
    entry: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    expected_move: float = 0.0
    reasons: List[str] = field(default_factory=list)
    result: str = "NO_TRADE_OBSERVED"     # NO_TRADE_OBSERVED | PENDING | TP_HIT | SL_HIT


class XAUUSDSetupLogger:
    """
    Persistent logger for XAU/USD setups.
    Writes atomic JSONL records and maintains an in-memory cache for fast UI access.
    """

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or _DEFAULT_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "xauusd_setups.jsonl"
        self._memory_cache: List[XAUUSDSetupRecord] = []
        self._load_cache()

    def _load_cache(self, max_items: int = 500) -> None:
        """Loads most recent items into memory buffer."""
        if not self.log_file.exists():
            return
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            recent_lines = lines[-max_items:]
            for line in recent_lines:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    self._memory_cache.append(XAUUSDSetupRecord(**data))
        except Exception as ex:
            logger.warning("Could not read setup cache from %s: %s", self.log_file, ex)

    def log_setup(self, record: XAUUSDSetupRecord) -> None:
        """Appends record to disk and memory buffer."""
        self._memory_cache.append(record)
        if len(self._memory_cache) > 1000:
            self._memory_cache = self._memory_cache[-1000:]

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record)) + "\n")
        except Exception as ex:
            logger.error("Failed to write setup record to %s: %s", self.log_file, ex)

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns recent setups formatted as dictionaries."""
        records = self._memory_cache[-limit:]
        return [asdict(r) for r in reversed(records)]

    def get_no_trade_setups(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns recent NO_TRADE setups for analysis."""
        no_trades = [r for r in self._memory_cache if r.signal == "NO_TRADE"]
        return [asdict(r) for r in reversed(no_trades[-limit:])]

    def get_actionable_setups(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns recent BUY and SELL trade signals."""
        actionable = [r for r in self._memory_cache if r.signal in ("BUY", "SELL")]
        return [asdict(r) for r in reversed(actionable[-limit:])]

    def count_by_score_brackets(self) -> Dict[str, int]:
        """Returns distribution of setups across score ranges."""
        brackets = {
            "0-59 (NO TRADE)": 0,
            "60-74 (WATCH)": 0,
            "75-84 (VALID SETUP)": 0,
            "85-100 (HIGH QUALITY)": 0,
        }
        for r in self._memory_cache:
            if r.score >= 85:
                brackets["85-100 (HIGH QUALITY)"] += 1
            elif r.score >= 75:
                brackets["75-84 (VALID SETUP)"] += 1
            elif r.score >= 60:
                brackets["60-74 (WATCH)"] += 1
            else:
                brackets["0-59 (NO TRADE)"] += 1
        return brackets


# Global singleton instance for easy import across dashboard & engines
setup_logger = XAUUSDSetupLogger()
