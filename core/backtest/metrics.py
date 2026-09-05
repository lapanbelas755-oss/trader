"""
Deterministic performance metrics calculator for Backtest Engine V1.
Strictly based on realized R-multiples and objective trade outcomes.
"""

from decimal import Decimal
from typing import Dict, List, Optional, Sequence
from core.backtest.contract import BacktestTradeRecord, SplitMetrics, TradeMetrics, TradeResult


class BacktestMetricsCalculator:
    """
    Computes deterministic statistical metrics across simulated trades.
    Segregates overall, setup archetype (S01-S05), and chronological splits.
    """

    @staticmethod
    def calculate_metrics(trades: Sequence[BacktestTradeRecord]) -> TradeMetrics:
        """Calculates TradeMetrics for a given sequence of trades."""
        sample_size = len(trades)
        wins = sum(1 for t in trades if t.result == TradeResult.TP)
        losses = sum(1 for t in trades if t.result == TradeResult.SL)
        timeouts = sum(1 for t in trades if t.result == TradeResult.TIMEOUT)
        ambiguous = sum(1 for t in trades if t.result == TradeResult.AMBIGUOUS)
        skipped = sum(1 for t in trades if t.result == TradeResult.SKIPPED_ACTIVE_TRADE)
        invalid = sum(1 for t in trades if t.result in (TradeResult.INVALID, TradeResult.DATA_ERROR))

        # Win Rate: wins / (wins + losses)
        win_loss_total = wins + losses
        win_rate = (
            (Decimal(str(wins)) / Decimal(str(win_loss_total))).quantize(Decimal("0.0001"))
            if win_loss_total > 0
            else None
        )

        realized_r_list: List[Decimal] = [
            t.r_multiple for t in trades if t.r_multiple is not None
        ]

        win_r_list = [r for r in realized_r_list if r > Decimal("0")]
        loss_r_list = [r for r in realized_r_list if r < Decimal("0")]

        average_win_r = (
            (sum(win_r_list) / Decimal(str(len(win_r_list)))).quantize(Decimal("0.0001"))
            if win_r_list
            else None
        )

        average_loss_r = (
            (sum(loss_r_list) / Decimal(str(len(loss_r_list)))).quantize(Decimal("0.0001"))
            if loss_r_list
            else None
        )

        expectancy_r = (
            (sum(realized_r_list) / Decimal(str(len(realized_r_list)))).quantize(Decimal("0.0001"))
            if realized_r_list
            else None
        )

        gross_pos = sum(win_r_list) if win_r_list else Decimal("0.0")
        gross_neg = abs(sum(loss_r_list)) if loss_r_list else Decimal("0.0")

        if gross_neg > Decimal("0"):
            profit_factor = (gross_pos / gross_neg).quantize(Decimal("0.0001"))
        elif gross_pos > Decimal("0"):
            profit_factor = None  # Represents INF
        else:
            profit_factor = None  # Undefined

        total_r = sum(realized_r_list) if realized_r_list else Decimal("0.0000")

        # Calculate Max Drawdown in R and Max Consecutive Losses
        peak = Decimal("0.0")
        cum_r = Decimal("0.0")
        max_dd = Decimal("0.0")
        max_cons_losses = 0
        curr_cons_losses = 0

        # Sort trades by exit time or entry time for equity curve
        sorted_trades = sorted(
            [t for t in trades if t.r_multiple is not None],
            key=lambda x: (x.exit_time or x.entry_time)
        )

        for t in sorted_trades:
            r = t.r_multiple or Decimal("0.0")
            cum_r += r
            if cum_r > peak:
                peak = cum_r
            dd = peak - cum_r
            if dd > max_dd:
                max_dd = dd

            if r < Decimal("0") or t.result == TradeResult.SL:
                curr_cons_losses += 1
                if curr_cons_losses > max_cons_losses:
                    max_cons_losses = curr_cons_losses
            else:
                curr_cons_losses = 0

        return TradeMetrics(
            sample_size=sample_size,
            wins=wins,
            losses=losses,
            timeouts=timeouts,
            ambiguous=ambiguous,
            skipped=skipped,
            invalid=invalid,
            win_rate=win_rate,
            average_win_r=average_win_r,
            average_loss_r=average_loss_r,
            expectancy_r=expectancy_r,
            profit_factor=profit_factor,
            total_r=total_r.quantize(Decimal("0.0001")),
            max_drawdown_r=max_dd.quantize(Decimal("0.0001")),
            max_consecutive_losses=max_cons_losses,
        )

    @classmethod
    def calculate_by_split(cls, trades: Sequence[BacktestTradeRecord]) -> SplitMetrics:
        """Segregates trades into IN_SAMPLE, VALIDATION, and OUT_OF_SAMPLE metrics."""
        in_sample = [t for t in trades if t.split_type == "IN_SAMPLE"]
        validation = [t for t in trades if t.split_type == "VALIDATION"]
        out_of_sample = [t for t in trades if t.split_type == "OUT_OF_SAMPLE"]

        return SplitMetrics(
            in_sample=cls.calculate_metrics(in_sample),
            validation=cls.calculate_metrics(validation),
            out_of_sample=cls.calculate_metrics(out_of_sample),
        )

    @classmethod
    def calculate_by_setup(cls, trades: Sequence[BacktestTradeRecord]) -> Dict[str, TradeMetrics]:
        """Calculates metrics broken down by setup archetype S01-S05."""
        by_setup: Dict[str, TradeMetrics] = {}
        for code in ("S01", "S02", "S03", "S04", "S05"):
            sub_trades = [t for t in trades if t.setup_code == code]
            by_setup[code] = cls.calculate_metrics(sub_trades)
        return by_setup
