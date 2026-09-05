"""
Report generator for Statistical Edge Engine V1.
Formats audit reports with multiple-testing warnings and strict truth-in-advertising disclaimers.
"""

from decimal import Decimal
from typing import Dict, List, Optional
from core.statistics.config import StatisticalConfig
from core.statistics.contract import (
    BootstrapMetricResult,
    EdgeClassification,
    MonteCarloMetricResult,
    OOSDegradationReport,
    SegmentMetricRecord,
    StatisticalMetricRecord,
)


class StatisticalReportGenerator:
    """
    Constructs comprehensive statistical edge audit reports.
    """

    @staticmethod
    def generate_report_text(
        symbol: str,
        config: StatisticalConfig,
        setup_metrics: Dict[str, StatisticalMetricRecord],
        setup_bootstraps: Dict[str, Optional[BootstrapMetricResult]],
        setup_degradations: Dict[str, Optional[OOSDegradationReport]],
        setup_monte_carlo: Dict[str, Optional[MonteCarloMetricResult]],
        segments: List[SegmentMetricRecord],
        total_segments_examined: int,
        data_quality_passed: bool,
        overall_verdict: EdgeClassification,
    ) -> str:
        """Builds standard text report."""
        lines = [
            "==================================================",
            "TRADER MACHINE — STATISTICAL EDGE REPORT",
            "==================================================",
            f"Symbol: {symbol}",
            f"Bootstrap Iterations: {config.bootstrap_iterations}",
            f"Monte Carlo Iterations: {config.monte_carlo_iterations}",
            f"Confidence Level: {config.confidence_level * 100:.1f}%",
            "Parameter Sensitivity State: SENSITIVITY_NOT_ESTABLISHED (Single baseline evaluated)",
            "--------------------------------------------------",
            "SETUP ARCHETYPE EVALUATION:",
        ]

        for code in ("S01", "S02", "S03", "S04", "S05"):
            m = setup_metrics.get(code)
            bs = setup_bootstraps.get(code)
            deg = setup_degradations.get(code)

            if m is None or m.sample_size == 0:
                lines.extend([
                    f"[{code}]",
                    "  Sample: 0 | Status: INSUFFICIENT_DATA",
                ])
                continue

            wr_str = f"{m.win_rate * 100:.2f}%" if m.win_rate is not None else "N/A"
            wr_ci = (
                f"[{m.win_rate_ci.lower_bound * 100:.2f}%, {m.win_rate_ci.upper_bound * 100:.2f}%]"
                if m.win_rate_ci
                else "N/A"
            )
            exp_str = f"{m.expectancy_r}R" if m.expectancy_r is not None else "N/A"
            pf_str = str(m.profit_factor) if m.profit_factor is not None else ("INF" if m.wins > 0 and m.losses == 0 else "N/A")

            bs_str = (
                f"[{bs.lower_bound}R, {bs.upper_bound}R] (Median: {bs.median}R, Pos: {bs.positive_fraction * 100:.1f}%)"
                if bs
                else "N/A"
            )
            oos_exp_str = f"{deg.oos_expectancy}R" if deg and deg.oos_expectancy is not None else "N/A"
            oos_deg_str = deg.status.value if deg else "N/A"

            lines.extend([
                f"[{code}]",
                f"  Sample: {m.sample_size} | Wins: {m.wins} | Losses: {m.losses} | Timeouts: {m.timeouts} | Ambiguous: {m.ambiguous}",
                f"  Win Rate: {wr_str} (Wilson 95% CI: {wr_ci})",
                f"  Expectancy: {exp_str} | Profit Factor: {pf_str} | Max Drawdown: {m.max_drawdown_r}R",
                f"  Bootstrap Expectancy CI: {bs_str}",
                f"  OOS Expectancy: {oos_exp_str} | OOS Status: {oos_deg_str}",
                f"  Classification: {m.classification.value}",
            ])

        lines.extend([
            "--------------------------------------------------",
            "EXPLORATORY SEGMENTATION ANALYSIS:",
            f"  Total Sub-Segments Examined: {total_segments_examined}",
            "  WARNING: Slicing into multiple segments increases false discovery risk.",
            "  Segmented findings must be treated as exploratory unless independently tested.",
        ])

        if segments:
            for s in segments[:12]:  # Show top representative segments
                wr_s = f"{s.win_rate * 100:.1f}%" if s.win_rate is not None else "N/A"
                lines.append(
                    f"  [{s.setup_code}][{s.segment_type.value} = {s.segment_value}]: "
                    f"N={s.sample_size}, WR={wr_s}, E={s.expectancy_r}R, DD={s.max_drawdown_r}R"
                )
            if len(segments) > 12:
                lines.append(f"  ... ({len(segments) - 12} additional segments logged to database)")

        lines.extend([
            "--------------------------------------------------",
            "MONTE CARLO SEQUENCE-RISK ANALYSIS:",
        ])
        for code in ("S01", "S02", "S03", "S04", "S05"):
            mc = setup_monte_carlo.get(code)
            if mc:
                lines.append(
                    f"  [{code}]: Median DD = {mc.drawdown_median}R | 95th Percentile DD = {mc.drawdown_p95}R | "
                    f"99th Percentile DD = {mc.drawdown_p99}R | Prob Neg Terminal = {mc.prob_negative_terminal * 100:.1f}%"
                )

        lines.extend([
            "--------------------------------------------------",
            "DATA QUALITY AUDIT:",
            f"  Integrity Check: {'PASS' if data_quality_passed else 'FAIL / CORRUPTED'}",
            "--------------------------------------------------",
            f"FINAL SYSTEM VERDICT: {overall_verdict.value}",
            "==================================================",
        ])

        return "\n".join(lines)
