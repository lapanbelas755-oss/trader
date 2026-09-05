"""
Multi-dimensional segmentation engine for Statistical Edge Engine V1.
Partitions backtest outcomes across market conditions and logs total comparisons.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple
from core.backtest.contract import BacktestTradeRecord, TradeResult
from core.setups.common import ensure_utc, get_val
from core.statistics.config import StatisticalConfig
from core.statistics.contract import SegmentMetricRecord, SegmentType


class SegmentationEngine:
    """
    Slices trades into descriptive sub-segments to evaluate contextual stability.
    Maintains count of total segments examined for multiple-testing disclosure.
    """

    def __init__(self, config: Optional[StatisticalConfig] = None):
        self.config = config or StatisticalConfig()

    def determine_session(self, entry_time: datetime) -> str:
        """Categorizes UTC timestamp into Forex market session."""
        hour = entry_time.hour
        if 0 <= hour < 8:
            return "ASIA"
        elif 8 <= hour < 13:
            return "LONDON"
        elif 13 <= hour < 21:
            return "NEW_YORK"
        else:
            return "ASIA"

    def determine_spread_bucket(self, spread: Decimal) -> str:
        """Classifies spread into deterministic buckets."""
        if spread <= self.config.spread_low_pips:
            return "LOW"
        elif spread <= self.config.spread_normal_pips:
            return "NORMAL"
        elif spread <= self.config.spread_high_pips:
            return "HIGH"
        else:
            return "EXTREME"

    def determine_day_of_week(self, entry_time: datetime) -> str:
        """Returns standard day of week name."""
        days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
        return days[entry_time.weekday()]

    def segment_trades(
        self,
        trades: Sequence[BacktestTradeRecord],
        occurrences_map: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[SegmentMetricRecord], int]:
        """
        Generates segment records across all supported dimensions.
        Returns (segment_metrics_list, total_segments_examined).
        """
        occ_map = occurrences_map or {}
        segments_dict: Dict[Tuple[str, SegmentType, str], List[BacktestTradeRecord]] = {}

        for t in trades:
            code = t.setup_code
            entry_t = ensure_utc(t.entry_time)

            # 1. Direction
            dir_val = t.direction.upper()
            segments_dict.setdefault((code, SegmentType.DIRECTION, dir_val), []).append(t)

            # 2. Session
            session_val = self.determine_session(entry_t)
            segments_dict.setdefault((code, SegmentType.SESSION, session_val), []).append(t)

            # 3. Day of Week
            day_val = self.determine_day_of_week(entry_t)
            segments_dict.setdefault((code, SegmentType.DAY_OF_WEEK, day_val), []).append(t)

            # 4. Spread Bucket
            spread_val = self.determine_spread_bucket(t.spread)
            segments_dict.setdefault((code, SegmentType.SPREAD_BUCKET, spread_val), []).append(t)

            # 5. Regime & Liquidity Type from Occurrence metadata
            occ = occ_map.get(t.setup_id)
            if occ:
                regime_val = str(get_val(occ, "regime", "UNKNOWN")).upper()
                segments_dict.setdefault((code, SegmentType.REGIME, regime_val), []).append(t)

                liq_val = get_val(occ, "liquidity_type")
                if liq_val:
                    segments_dict.setdefault((code, SegmentType.LIQUIDITY_TYPE, str(liq_val).upper()), []).append(t)

        metric_records: List[SegmentMetricRecord] = []

        for (code, seg_type, seg_val), sub_trades in segments_dict.items():
            sample_size = len(sub_trades)
            wins = sum(1 for tr in sub_trades if tr.result == TradeResult.TP)
            losses = sum(1 for tr in sub_trades if tr.result == TradeResult.SL)

            win_rate = (
                (Decimal(str(wins)) / Decimal(str(wins + losses))).quantize(Decimal("0.0001"))
                if (wins + losses) > 0
                else None
            )

            r_list = [tr.r_multiple for tr in sub_trades if tr.r_multiple is not None]
            expectancy_r = (
                (sum(r_list) / Decimal(str(len(r_list)))).quantize(Decimal("0.0001"))
                if r_list
                else None
            )

            gross_pos = sum(r for r in r_list if r > 0)
            gross_neg = abs(sum(r for r in r_list if r < 0))
            if gross_neg > Decimal("0"):
                pf = (gross_pos / gross_neg).quantize(Decimal("0.0001"))
            elif gross_pos > Decimal("0"):
                pf = None
            else:
                pf = None

            total_r = sum(r_list) if r_list else Decimal("0.0000")

            peak = Decimal("0.0")
            cum_r = Decimal("0.0")
            max_dd = Decimal("0.0")
            for r in r_list:
                cum_r += r
                if cum_r > peak:
                    peak = cum_r
                dd = peak - cum_r
                if dd > max_dd:
                    max_dd = dd

            rec = SegmentMetricRecord(
                setup_code=code,
                segment_type=seg_type,
                segment_value=seg_val,
                sample_size=sample_size,
                win_rate=win_rate,
                expectancy_r=expectancy_r,
                profit_factor=pf,
                total_r=total_r.quantize(Decimal("0.0001")),
                max_drawdown_r=max_dd.quantize(Decimal("0.0001")),
            )
            metric_records.append(rec)

        total_examined = len(metric_records)
        return metric_records, total_examined
