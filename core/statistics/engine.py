"""
End-to-end Statistical Edge Engine V1 for Trader Machine.
Coordinates data quality audits, Wilson confidence intervals, deterministic bootstrapping,
Monte Carlo sequence permutations, multi-dimensional segmentation, and PostgreSQL persistence.
"""

from datetime import datetime, timezone
from decimal import Decimal
import math
import statistics
from typing import Any, Dict, List, Optional, Sequence
import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.backtest.contract import BacktestTradeRecord, TradeResult
from core.setups.common import ensure_utc, get_val
from core.statistics.bootstrap import DeterministicBootstrapEngine
from core.statistics.classifier import EdgeClassifier
from core.statistics.config import StatisticalConfig
from core.statistics.contract import (
    BootstrapMetricResult,
    EdgeClassification,
    MonteCarloMetricResult,
    OOSDegradationReport,
    SegmentMetricRecord,
    StatisticalMetricRecord,
    StatisticalRunRecord,
)
from core.statistics.degradation import DegradationEvaluator
from core.statistics.intervals import WilsonScoreIntervalCalculator
from core.statistics.monte_carlo import MonteCarloPermutationEngine
from core.statistics.report import StatisticalReportGenerator
from core.statistics.segmentation import SegmentationEngine
from database.models import (
    BootstrapResult as BootstrapResultModel,
    EdgeMetric as EdgeMetricModel,
    EdgeSegment as EdgeSegmentModel,
    StatisticalRun as StatisticalRunModel,
)


class StatisticalRunResult:
    """Encapsulates all statistical outputs produced by StatisticalEdgeEngine."""

    def __init__(
        self,
        run_id: str,
        run_record: StatisticalRunRecord,
        setup_metrics: Dict[str, StatisticalMetricRecord],
        split_metrics: Dict[str, Dict[str, StatisticalMetricRecord]],
        bootstraps: Dict[str, Optional[BootstrapMetricResult]],
        monte_carlo: Dict[str, Optional[MonteCarloMetricResult]],
        degradations: Dict[str, Optional[OOSDegradationReport]],
        segments: List[SegmentMetricRecord],
        total_segments_examined: int,
        data_quality_ok: bool,
        overall_verdict: EdgeClassification,
        report_text: str,
    ):
        self.run_id = run_id
        self.run_record = run_record
        self.setup_metrics = setup_metrics
        self.split_metrics = split_metrics
        self.bootstraps = bootstraps
        self.monte_carlo = monte_carlo
        self.degradations = degradations
        self.segments = segments
        self.total_segments_examined = total_segments_examined
        self.data_quality_ok = data_quality_ok
        self.overall_verdict = overall_verdict
        self.report_text = report_text


class StatisticalEdgeEngine:
    """
    Evaluates backtest trade outputs for evidence of statistical edge.
    Strictly preserves causality and reproducibility.
    """

    def __init__(
        self,
        symbol: Any = "EURUSD",
        config: Optional[StatisticalConfig] = None,
    ):
        if isinstance(symbol, StatisticalConfig):
            self.config = symbol
            self.symbol = "EURUSD"
        else:
            self.symbol = str(symbol).strip().upper()
            self.config = config or StatisticalConfig()

        self.classifier = EdgeClassifier(config=self.config)
        self.degradation_evaluator = DegradationEvaluator(config=self.config)
        self.segmentation_engine = SegmentationEngine(config=self.config)

    def verify_data_quality(self, trades: Sequence[BacktestTradeRecord]) -> bool:
        """
        Data quality gate. Rejects dataset if corrupted, zero-risk, or impossible prices exist.
        """
        for t in trades:
            if t.entry_price <= Decimal("0.0"):
                return False
            if t.stop_loss <= Decimal("0.0") and t.result not in (TradeResult.SKIPPED_ACTIVE_TRADE, TradeResult.INVALID):
                return False
            # Zero risk distance check for executed trades
            if t.result in (TradeResult.TP, TradeResult.SL, TradeResult.TIMEOUT):
                if t.entry_price == t.stop_loss:
                    return False
            if t.entry_time.year < 1970 or (t.exit_time and t.exit_time < t.entry_time):
                return False
        return True

    def calculate_descriptive_metrics(
        self,
        trades: Sequence[BacktestTradeRecord],
        setup_code: str,
        split_type: str = "ALL",
    ) -> StatisticalMetricRecord:
        """Computes descriptive and inferential statistics for a subset of trades."""
        sample_size = len(trades)
        wins = sum(1 for t in trades if t.result == TradeResult.TP)
        losses = sum(1 for t in trades if t.result == TradeResult.SL)
        timeouts = sum(1 for t in trades if t.result == TradeResult.TIMEOUT)
        ambiguous = sum(1 for t in trades if t.result == TradeResult.AMBIGUOUS)

        total_decisions = wins + losses
        win_rate = (
            (Decimal(str(wins)) / Decimal(str(total_decisions))).quantize(Decimal("0.0001"))
            if total_decisions > 0
            else None
        )

        win_rate_ci = WilsonScoreIntervalCalculator.calculate(
            wins=wins,
            total_decisions=total_decisions,
            confidence_level=self.config.confidence_level,
        )

        r_list = [t.r_multiple for t in trades if t.r_multiple is not None]
        win_rs = [r for r in r_list if r > 0]
        loss_rs = [r for r in r_list if r < 0]

        avg_win_r = (sum(win_rs) / Decimal(str(len(win_rs)))).quantize(Decimal("0.0001")) if win_rs else None
        avg_loss_r = (sum(loss_rs) / Decimal(str(len(loss_rs)))).quantize(Decimal("0.0001")) if loss_rs else None
        exp_r = (sum(r_list) / Decimal(str(len(r_list)))).quantize(Decimal("0.0001")) if r_list else None

        gross_pos = sum(win_rs) if win_rs else Decimal("0.0")
        gross_neg = abs(sum(loss_rs)) if loss_rs else Decimal("0.0")
        if gross_neg > Decimal("0"):
            pf = (gross_pos / gross_neg).quantize(Decimal("0.0001"))
        elif gross_pos > Decimal("0"):
            pf = None  # INF
        else:
            pf = None

        total_r = sum(r_list) if r_list else Decimal("0.0000")

        # Peak drawdown & consecutive losses
        peak = Decimal("0.0")
        cum_r = Decimal("0.0")
        max_dd = Decimal("0.0")
        max_cons_losses = 0
        curr_cons_losses = 0

        sorted_trades = sorted(trades, key=lambda tr: (tr.exit_time or tr.entry_time))
        for tr in sorted_trades:
            r = tr.r_multiple
            if r is not None:
                cum_r += r
                if cum_r > peak:
                    peak = cum_r
                dd = peak - cum_r
                if dd > max_dd:
                    max_dd = dd

            if tr.result == TradeResult.SL or (r is not None and r < 0):
                curr_cons_losses += 1
                if curr_cons_losses > max_cons_losses:
                    max_cons_losses = curr_cons_losses
            else:
                curr_cons_losses = 0

        # Mean, Median, Std of R
        if r_list:
            float_rs = [float(r) for r in r_list]
            mean_val = Decimal(str(round(statistics.mean(float_rs), 4)))
            median_val = Decimal(str(round(statistics.median(float_rs), 4)))
            std_val = (
                Decimal(str(round(statistics.stdev(float_rs), 4)))
                if len(float_rs) > 1
                else Decimal("0.0000")
            )
        else:
            mean_val = None
            median_val = None
            std_val = None

        reliability = self.classifier.classify_sample_size(sample_size)

        return StatisticalMetricRecord(
            setup_code=setup_code,
            split_type=split_type,
            sample_size=sample_size,
            wins=wins,
            losses=losses,
            timeouts=timeouts,
            ambiguous=ambiguous,
            win_rate=win_rate,
            win_rate_ci=win_rate_ci,
            average_win_r=avg_win_r,
            average_loss_r=avg_loss_r,
            expectancy_r=exp_r,
            profit_factor=pf,
            total_r=total_r.quantize(Decimal("0.0001")),
            max_drawdown_r=max_dd.quantize(Decimal("0.0001")),
            max_consecutive_losses=max_cons_losses,
            mean_r=mean_val,
            median_r=median_val,
            std_r=std_val,
            sample_reliability=reliability,
            classification=EdgeClassification.INSUFFICIENT_DATA,
        )

    def analyze_edge(
        self,
        trades: Sequence[BacktestTradeRecord],
        dataset_hash: str = "dataset_default_hash",
        backtest_config_hash: str = "bt_default_hash",
        backtest_run_id: Optional[int] = None,
        run_id: Optional[str] = None,
        occurrences_map: Optional[Dict[str, Any]] = None,
    ) -> StatisticalRunResult:
        """
        Executes statistical edge validation across trades.
        """
        active_run_id = run_id or f"stat_{uuid.uuid4().hex[:12]}"
        config_hash = self.config.get_config_hash()

        # 1. Data Quality Gate
        data_quality_ok = self.verify_data_quality(trades)

        setup_codes = ("S01", "S02", "S03", "S04", "S05")
        setup_metrics: Dict[str, StatisticalMetricRecord] = {}
        split_metrics: Dict[str, Dict[str, StatisticalMetricRecord]] = {}
        bootstraps: Dict[str, Optional[BootstrapMetricResult]] = {}
        monte_carlo: Dict[str, Optional[MonteCarloMetricResult]] = {}
        degradations: Dict[str, Optional[OOSDegradationReport]] = {}

        # 2. Evaluate each setup archetype
        for code in setup_codes:
            sub_trades = [t for t in trades if t.setup_code == code]
            overall_rec = self.calculate_descriptive_metrics(sub_trades, code, split_type="ALL")

            # Split evaluation
            is_trades = [t for t in sub_trades if t.split_type == "IN_SAMPLE"]
            val_trades = [t for t in sub_trades if t.split_type == "VALIDATION"]
            oos_trades = [t for t in sub_trades if t.split_type == "OUT_OF_SAMPLE"]

            is_rec = self.calculate_descriptive_metrics(is_trades, code, split_type="IN_SAMPLE")
            val_rec = self.calculate_descriptive_metrics(val_trades, code, split_type="VALIDATION")
            oos_rec = self.calculate_descriptive_metrics(oos_trades, code, split_type="OUT_OF_SAMPLE")

            split_metrics[code] = {
                "IN_SAMPLE": is_rec,
                "VALIDATION": val_rec,
                "OUT_OF_SAMPLE": oos_rec,
            }

            r_multiples = [t.r_multiple for t in sub_trades if t.r_multiple is not None]

            # Seed derivation
            seed = self.config.derive_seed(dataset_hash, backtest_config_hash, code)

            # Deterministic Bootstrap
            bs_engine = DeterministicBootstrapEngine(seed=seed, iterations=self.config.bootstrap_iterations)
            bs_exp = bs_engine.bootstrap_expectancy(r_multiples)
            bootstraps[code] = bs_exp
            overall_rec.expectancy_ci = bs_exp

            # Deterministic Monte Carlo
            mc_engine = MonteCarloPermutationEngine(seed=seed, iterations=self.config.monte_carlo_iterations)
            mc_res = mc_engine.run_permutation_analysis(r_multiples)
            monte_carlo[code] = mc_res

            # Degradation analysis
            deg_report = self.degradation_evaluator.evaluate_degradation(is_rec, oos_rec)
            degradations[code] = deg_report

            # Classification
            classification = self.classifier.classify_edge(
                overall_metrics=overall_rec,
                bootstrap_exp=bs_exp,
                degradation_report=deg_report,
                val_metrics=val_rec,
                data_quality_ok=data_quality_ok,
            )
            overall_rec.classification = classification
            setup_metrics[code] = overall_rec

        # 3. Multi-dimensional Segmentation
        segments, total_examined = self.segmentation_engine.segment_trades(trades, occurrences_map)

        # 4. Overall system verdict
        all_classifications = [m.classification for m in setup_metrics.values()]
        if not data_quality_ok:
            overall_verdict = EdgeClassification.INVALID_DATA
        elif any(c == EdgeClassification.ROBUST_EDGE for c in all_classifications):
            overall_verdict = EdgeClassification.ROBUST_EDGE
        elif any(c == EdgeClassification.POTENTIAL_EDGE for c in all_classifications):
            overall_verdict = EdgeClassification.POTENTIAL_EDGE
        elif any(c == EdgeClassification.PRELIMINARY_EDGE for c in all_classifications):
            overall_verdict = EdgeClassification.PRELIMINARY_EDGE
        elif any(c == EdgeClassification.NEGATIVE_EDGE for c in all_classifications):
            overall_verdict = EdgeClassification.NEGATIVE_EDGE
        elif any(c == EdgeClassification.NO_CLEAR_EDGE for c in all_classifications):
            overall_verdict = EdgeClassification.NO_CLEAR_EDGE
        else:
            overall_verdict = EdgeClassification.INSUFFICIENT_DATA

        # 5. Generate Report Text
        report_text = StatisticalReportGenerator.generate_report_text(
            symbol=self.symbol,
            config=self.config,
            setup_metrics=setup_metrics,
            setup_bootstraps=bootstraps,
            setup_degradations=degradations,
            setup_monte_carlo=monte_carlo,
            segments=segments,
            total_segments_examined=total_examined,
            data_quality_passed=data_quality_ok,
            overall_verdict=overall_verdict,
        )

        run_record = StatisticalRunRecord(
            run_id=active_run_id,
            backtest_run_id=backtest_run_id or 0,
            dataset_split="ALL",
            engine_version="1.0.0",
            config_hash=config_hash,
            completed_at=datetime.now(timezone.utc),
            status="SUCCESS" if data_quality_ok else "FAILED",
            overall_classification=overall_verdict,
        )

        return StatisticalRunResult(
            run_id=active_run_id,
            run_record=run_record,
            setup_metrics=setup_metrics,
            split_metrics=split_metrics,
            bootstraps=bootstraps,
            monte_carlo=monte_carlo,
            degradations=degradations,
            segments=segments,
            total_segments_examined=total_examined,
            data_quality_ok=data_quality_ok,
            overall_verdict=overall_verdict,
            report_text=report_text,
        )

    def persist_results(
        self,
        session: Session,
        result: StatisticalRunResult,
        backtest_run_db_id: int,
    ) -> int:
        """
        Persists statistical runs, edge metrics, segments, and bootstrap results idempotently.
        """
        stat_stmt = insert(StatisticalRunModel).values(
            run_id=result.run_id,
            backtest_run_id=backtest_run_db_id,
            dataset_split=result.run_record.dataset_split,
            engine_version=result.run_record.engine_version,
            config_hash=result.run_record.config_hash,
            started_at=result.run_record.started_at,
            completed_at=result.run_record.completed_at,
            status=result.run_record.status,
            overall_classification=result.overall_verdict.value,
        ).on_conflict_do_nothing(index_elements=["run_id"]).returning(StatisticalRunModel.id)

        res = session.execute(stat_stmt)
        inserted_id = res.scalar_one_or_none()

        if inserted_id is None:
            existing = session.query(StatisticalRunModel).filter_by(run_id=result.run_id).first()
            if not existing:
                session.rollback()
                raise RuntimeError(f"Could not persist or locate StatisticalRun {result.run_id}")
            stat_db_id = existing.id
        else:
            stat_db_id = inserted_id

        # Insert Edge Metrics
        persisted_records = 0
        for code, m in result.setup_metrics.items():
            ci_low = m.win_rate_ci.lower_bound if m.win_rate_ci else None
            ci_upp = m.win_rate_ci.upper_bound if m.win_rate_ci else None

            em_stmt = insert(EdgeMetricModel).values(
                statistical_run_id=stat_db_id,
                setup_code=code,
                split_type="ALL",
                sample_size=m.sample_size,
                wins=m.wins,
                losses=m.losses,
                timeouts=m.timeouts,
                ambiguous=m.ambiguous,
                win_rate=m.win_rate,
                win_rate_ci_lower=ci_low,
                win_rate_ci_upper=ci_upp,
                average_win_r=m.average_win_r,
                average_loss_r=m.average_loss_r,
                expectancy_r=m.expectancy_r,
                profit_factor=m.profit_factor,
                total_r=m.total_r,
                max_drawdown_r=m.max_drawdown_r,
                max_consecutive_losses=m.max_consecutive_losses,
                mean_r=m.mean_r,
                median_r=m.median_r,
                std_r=m.std_r,
                classification=m.classification.value,
            )
            session.execute(em_stmt)
            persisted_records += 1

        # Insert Edge Segments
        for seg in result.segments:
            seg_stmt = insert(EdgeSegmentModel).values(
                statistical_run_id=stat_db_id,
                setup_code=seg.setup_code,
                segment_type=seg.segment_type.value,
                segment_value=seg.segment_value,
                sample_size=seg.sample_size,
                win_rate=seg.win_rate,
                expectancy_r=seg.expectancy_r,
                profit_factor=seg.profit_factor,
                total_r=seg.total_r,
                max_drawdown_r=seg.max_drawdown_r,
            )
            session.execute(seg_stmt)
            persisted_records += 1

        # Insert Bootstrap Results
        for code, bs in result.bootstraps.items():
            if bs:
                bs_stmt = insert(BootstrapResultModel).values(
                    statistical_run_id=stat_db_id,
                    setup_code=code,
                    metric=bs.metric,
                    iterations=bs.iterations,
                    lower_bound=bs.lower_bound,
                    median=bs.median,
                    upper_bound=bs.upper_bound,
                    positive_fraction=bs.positive_fraction,
                )
                session.execute(bs_stmt)
                persisted_records += 1

        session.commit()
        return persisted_records
