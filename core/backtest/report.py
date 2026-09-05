"""
Report generator for Backtest Engine V1.
Formats human-readable summary reports and JSON-serializable performance representations.
"""

from decimal import Decimal
from typing import Any, Dict, List
from core.backtest.config import BacktestConfig
from core.backtest.contract import BacktestTradeRecord, SplitMetrics, TradeMetrics


class BacktestReportGenerator:
    """
    Generates deterministic backtest reports without claiming profitability.
    """

    @staticmethod
    def generate_report_text(
        symbol: str,
        config: BacktestConfig,
        overall_metrics: TradeMetrics,
        setup_metrics: Dict[str, TradeMetrics],
        split_metrics: SplitMetrics,
    ) -> str:
        """Constructs human-readable audit report."""
        lines = [
            "==================================================",
            f"TRADER MACHINE — BACKTEST ENGINE V1 REPORT",
            "==================================================",
            f"Symbol: {symbol}",
            f"Target R: {config.target_r}R (BASELINE ONLY — NOT OPTIMIZED)",
            f"Timeout Bars: {config.timeout_bars} M5 bars",
            f"SL Buffer: {config.sl_buffer_pips} pips",
            f"Commission: {config.commission_per_trade} (COMMISSION = {config.commission_per_trade})",
            f"Slippage: {config.slippage_pips} (SLIPPAGE = {config.slippage_pips})",
            f"Collision Policy: {config.collision_policy}",
            "--------------------------------------------------",
            "OVERALL PERFORMANCE SUMMARY:",
            f"  Sample Size: {overall_metrics.sample_size}",
            f"  Wins: {overall_metrics.wins}",
            f"  Losses: {overall_metrics.losses}",
            f"  Timeouts: {overall_metrics.timeouts}",
            f"  Ambiguous (Intrabar): {overall_metrics.ambiguous}",
            f"  Skipped (Active Trade): {overall_metrics.skipped}",
            f"  Invalid / Error: {overall_metrics.invalid}",
            f"  Win Rate: {f'{overall_metrics.win_rate * 100:.2f}%' if overall_metrics.win_rate is not None else 'N/A'}",
            f"  Avg Win R: {overall_metrics.average_win_r if overall_metrics.average_win_r is not None else 'N/A'}",
            f"  Avg Loss R: {overall_metrics.average_loss_r if overall_metrics.average_loss_r is not None else 'N/A'}",
            f"  Expectancy R: {overall_metrics.expectancy_r if overall_metrics.expectancy_r is not None else 'N/A'}",
            f"  Profit Factor: {overall_metrics.profit_factor if overall_metrics.profit_factor is not None else ('INF' if overall_metrics.wins > 0 and overall_metrics.losses == 0 else 'N/A')}",
            f"  Total Realized R: {overall_metrics.total_r}R",
            f"  Max Drawdown R: {overall_metrics.max_drawdown_r}R",
            f"  Max Consecutive Losses: {overall_metrics.max_consecutive_losses}",
            "--------------------------------------------------",
            "BREAKDOWN BY SETUP ARCHETYPE:",
        ]

        for code in ("S01", "S02", "S03", "S04", "S05"):
            sm = setup_metrics.get(code, TradeMetrics())
            pf_str = str(sm.profit_factor) if sm.profit_factor is not None else ("INF" if sm.wins > 0 and sm.losses == 0 else "N/A")
            wr_str = f"{sm.win_rate * 100:.2f}%" if sm.win_rate is not None else "N/A"
            lines.extend([
                f"  [{code}]",
                f"    Sample: {sm.sample_size} | Wins: {sm.wins} | Losses: {sm.losses} | Timeouts: {sm.timeouts} | Ambiguous: {sm.ambiguous}",
                f"    Win Rate: {wr_str} | Expectancy: {sm.expectancy_r or 'N/A'}R | Total R: {sm.total_r}R | PF: {pf_str}",
            ])

        lines.extend([
            "--------------------------------------------------",
            "BREAKDOWN BY CHRONOLOGICAL SPLIT:",
            "  [IN_SAMPLE]:",
            f"    Sample: {split_metrics.in_sample.sample_size} | Wins: {split_metrics.in_sample.wins} | Losses: {split_metrics.in_sample.losses} | Total R: {split_metrics.in_sample.total_r}R",
            "  [VALIDATION]:",
            f"    Sample: {split_metrics.validation.sample_size} | Wins: {split_metrics.validation.wins} | Losses: {split_metrics.validation.losses} | Total R: {split_metrics.validation.total_r}R",
            "  [OUT_OF_SAMPLE]:",
            f"    Sample: {split_metrics.out_of_sample.sample_size} | Wins: {split_metrics.out_of_sample.wins} | Losses: {split_metrics.out_of_sample.losses} | Total R: {split_metrics.out_of_sample.total_r}R",
            "==================================================",
            "NOTE: This report measures deterministic baseline trade outcomes.",
            "It does NOT claim statistical significance, positive expectancy,",
            "or future profitability. Baseline only.",
            "==================================================",
        ])

        return "\n".join(lines)
