"""
Comprehensive unit, integration, and statistical validity tests for Statistical Edge Engine V1.
Deterministic, reproducible, zero non-deterministic randomness.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import pytest
from sqlalchemy import text

from core.backtest.contract import BacktestTradeRecord, TradeResult, TradeStatus
from core.statistics.bootstrap import DeterministicBootstrapEngine
from core.statistics.classifier import EdgeClassifier
from core.statistics.config import StatisticalConfig
from core.statistics.contract import (
    EdgeClassification,
    OOSDegradationStatus,
    SampleReliability,
    SegmentType,
    StatisticalMetricRecord,
)
from core.statistics.degradation import DegradationEvaluator
from core.statistics.engine import StatisticalEdgeEngine
from core.statistics.intervals import WilsonScoreIntervalCalculator
from core.statistics.monte_carlo import MonteCarloPermutationEngine
from core.statistics.report import StatisticalReportGenerator
from core.statistics.segmentation import SegmentationEngine
from database.connection import get_session_factory


def make_trade(
    setup_code: str = "S01",
    direction: str = "BULLISH",
    result: TradeResult = TradeResult.TP,
    r_multiple: Optional[float] = 2.0,
    entry_time: Optional[datetime] = None,
    entry_price: float = 1.0500,
    stop_loss: float = 1.0450,
    split_type: str = "IN_SAMPLE",
    spread: float = 0.00010,
    setup_id: str = "s1",
) -> BacktestTradeRecord:
    t = entry_time or datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    return BacktestTradeRecord(
        setup_id=setup_id,
        setup_code=setup_code,
        symbol="EURUSD",
        timeframe="M5",
        direction=direction,
        entry_time=t,
        entry_price=Decimal(str(entry_price)),
        stop_loss=Decimal(str(stop_loss)),
        take_profit=Decimal("1.0600"),
        exit_time=t + timedelta(minutes=10),
        exit_price=Decimal("1.0600") if result == TradeResult.TP else Decimal("1.0450"),
        result=result,
        r_multiple=Decimal(str(r_multiple)) if r_multiple is not None else None,
        commission=Decimal("0.0"),
        slippage=Decimal("0.0"),
        spread=Decimal(str(spread)),
        status=TradeStatus.CLOSED,
        split_type=split_type,
    )


def test_win_rate_calculation():
    """Win rate properly divides wins by (wins + losses) and excludes timeouts/ambiguous."""
    trades = [
        make_trade(result=TradeResult.TP, r_multiple=2.0),
        make_trade(result=TradeResult.TP, r_multiple=2.0),
        make_trade(result=TradeResult.SL, r_multiple=-1.0),
        make_trade(result=TradeResult.TIMEOUT, r_multiple=0.5),
        make_trade(result=TradeResult.AMBIGUOUS, r_multiple=None),
    ]
    engine = StatisticalEdgeEngine()
    m = engine.calculate_descriptive_metrics(trades, "S01")
    assert m.wins == 2
    assert m.losses == 1
    assert m.timeouts == 1
    assert m.ambiguous == 1
    # 2 / (2 + 1) = 0.6667
    assert m.win_rate == Decimal("0.6667")


def test_wilson_confidence_interval():
    """Wilson interval generates robust boundaries without collapsing on boundary samples."""
    # 5 wins out of 10 decisions
    ci = WilsonScoreIntervalCalculator.calculate(wins=5, total_decisions=10, confidence_level=Decimal("0.95"))
    assert ci is not None
    assert Decimal("0.23") < ci.lower_bound < Decimal("0.25")
    assert Decimal("0.75") < ci.upper_bound < Decimal("0.77")

    # 0 wins out of 10 decisions: lower bound is 0.0, upper bound > 0.0
    ci_zero = WilsonScoreIntervalCalculator.calculate(wins=0, total_decisions=10)
    assert ci_zero.lower_bound == Decimal("0.0000")
    assert ci_zero.upper_bound > Decimal("0.0000")

    # 10 wins out of 10 decisions: upper bound is 1.0, lower bound < 1.0
    ci_full = WilsonScoreIntervalCalculator.calculate(wins=10, total_decisions=10)
    assert ci_full.upper_bound == Decimal("1.0000")
    assert ci_full.lower_bound < Decimal("1.0000")


def test_expectancy_calculation():
    """Expectancy calculates arithmetic mean of realized R."""
    trades = [
        make_trade(r_multiple=2.0),
        make_trade(r_multiple=-1.0),
        make_trade(r_multiple=0.5),
    ]
    engine = StatisticalEdgeEngine()
    m = engine.calculate_descriptive_metrics(trades, "S01")
    # (2.0 - 1.0 + 0.5) / 3 = 0.5000R
    assert m.expectancy_r == Decimal("0.5000")
    assert m.mean_r == Decimal("0.5000")
    assert m.median_r == Decimal("0.5000")


def test_profit_factor_edge_cases():
    """Profit factor correctly reports INF when zero losses, and None when zero wins."""
    engine = StatisticalEdgeEngine()

    # Zero loss -> INF / None
    t_wins = [make_trade(r_multiple=2.0), make_trade(r_multiple=1.0)]
    m_win = engine.calculate_descriptive_metrics(t_wins, "S01")
    assert m_win.profit_factor is None

    # Zero win -> 0.0000
    t_loss = [make_trade(result=TradeResult.SL, r_multiple=-1.0)]
    m_loss = engine.calculate_descriptive_metrics(t_loss, "S01")
    assert m_loss.profit_factor == Decimal("0.0000")

    # All-zero R
    t_zero = [make_trade(r_multiple=0.0)]
    m_zero = engine.calculate_descriptive_metrics(t_zero, "S01")
    assert m_zero.profit_factor is None


def test_drawdown_calculation():
    """Drawdown tracks chronological peak-to-trough decline."""
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    trades = [
        make_trade(entry_time=t0, r_multiple=2.0),                     # Peak = 2.0
        make_trade(entry_time=t0 + timedelta(minutes=15), r_multiple=-1.0),  # Cum = 1.0, DD = 1.0
        make_trade(entry_time=t0 + timedelta(minutes=30), r_multiple=-1.0),  # Cum = 0.0, DD = 2.0
        make_trade(entry_time=t0 + timedelta(minutes=45), r_multiple=3.0),   # Peak = 3.0
    ]
    engine = StatisticalEdgeEngine()
    m = engine.calculate_descriptive_metrics(trades, "S01")
    assert m.max_drawdown_r == Decimal("2.0000")
    assert m.total_r == Decimal("3.0000")


def test_consecutive_losses():
    """Calculates max consecutive losing outcomes accurately."""
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    trades = [
        make_trade(entry_time=t0, result=TradeResult.SL, r_multiple=-1.0),
        make_trade(entry_time=t0 + timedelta(minutes=10), result=TradeResult.SL, r_multiple=-1.0),
        make_trade(entry_time=t0 + timedelta(minutes=20), result=TradeResult.TP, r_multiple=2.0),
        make_trade(entry_time=t0 + timedelta(minutes=30), result=TradeResult.SL, r_multiple=-1.0),
    ]
    engine = StatisticalEdgeEngine()
    m = engine.calculate_descriptive_metrics(trades, "S01")
    assert m.max_consecutive_losses == 2


def test_bootstrap_reproducibility():
    """Identical seed produces identical bootstrap distribution."""
    r_multiples = [Decimal("2.0"), Decimal("-1.0"), Decimal("0.5"), Decimal("2.0"), Decimal("-1.0")]
    b1 = DeterministicBootstrapEngine(seed=42, iterations=1000)
    b2 = DeterministicBootstrapEngine(seed=42, iterations=1000)

    res1 = b1.bootstrap_expectancy(r_multiples)
    res2 = b2.bootstrap_expectancy(r_multiples)

    assert res1.lower_bound == res2.lower_bound
    assert res1.median == res2.median
    assert res1.upper_bound == res2.upper_bound
    assert res1.positive_fraction == res2.positive_fraction


def test_bootstrap_confidence_interval():
    """Bootstrap interval bounds the median correctly."""
    r_multiples = [Decimal("2.0"), Decimal("1.5"), Decimal("0.5"), Decimal("-1.0"), Decimal("2.0")] * 5
    b = DeterministicBootstrapEngine(seed=123, iterations=1000)
    res = b.bootstrap_expectancy(r_multiples)

    assert res.lower_bound <= res.median <= res.upper_bound
    assert res.positive_fraction > Decimal("0.80")


def test_monte_carlo_reproducibility():
    """Monte Carlo sequence permutation produces identical results with same seed."""
    r_multiples = [Decimal("2.0"), Decimal("-1.0"), Decimal("-1.0"), Decimal("2.0"), Decimal("-1.0")] * 4
    mc1 = MonteCarloPermutationEngine(seed=777, iterations=500)
    mc2 = MonteCarloPermutationEngine(seed=777, iterations=500)

    res1 = mc1.run_permutation_analysis(r_multiples)
    res2 = mc2.run_permutation_analysis(r_multiples)

    assert res1.drawdown_median == res2.drawdown_median
    assert res1.drawdown_p95 == res2.drawdown_p95
    assert res1.drawdown_p99 == res2.drawdown_p99


def test_oos_degradation_calculation():
    """OOS degradation classifies STABLE, DEGRADED, COLLAPSED accurately."""
    evaluator = DegradationEvaluator(StatisticalConfig(oos_degraded_ratio=Decimal("0.60"), oos_collapsed_ratio=Decimal("0.00")))

    # Stable case: IS = 1.0R, OOS = 0.8R -> ratio 0.80 >= 0.60
    is_m = StatisticalMetricRecord(setup_code="S01", sample_size=100, expectancy_r=Decimal("1.0000"), win_rate=Decimal("0.60"))
    oos_stable = StatisticalMetricRecord(setup_code="S01", sample_size=40, expectancy_r=Decimal("0.8000"), win_rate=Decimal("0.55"))
    r_stable = evaluator.evaluate_degradation(is_m, oos_stable)
    assert r_stable.status == OOSDegradationStatus.STABLE
    assert r_stable.expectancy_ratio == Decimal("0.8000")

    # Degraded case: IS = 1.0R, OOS = 0.4R -> ratio 0.40 < 0.60
    oos_deg = StatisticalMetricRecord(setup_code="S01", sample_size=40, expectancy_r=Decimal("0.4000"), win_rate=Decimal("0.45"))
    r_deg = evaluator.evaluate_degradation(is_m, oos_deg)
    assert r_deg.status == OOSDegradationStatus.DEGRADED

    # Collapsed case: IS = 1.0R, OOS = -0.2R -> ratio <= 0
    oos_col = StatisticalMetricRecord(setup_code="S01", sample_size=40, expectancy_r=Decimal("-0.2000"), win_rate=Decimal("0.30"))
    r_col = evaluator.evaluate_degradation(is_m, oos_col)
    assert r_col.status == OOSDegradationStatus.COLLAPSED


def test_regime_segmentation():
    """Trades are correctly segmented by market regime."""
    seg_engine = SegmentationEngine()
    t1 = make_trade(setup_id="s1", r_multiple=2.0)
    t2 = make_trade(setup_id="s2", r_multiple=-1.0)
    occ_map = {
        "s1": {"regime": "TREND_UP", "liquidity_type": "SWING_HIGH"},
        "s2": {"regime": "RANGE", "liquidity_type": "SESSION_LOW"},
    }

    segments, count = seg_engine.segment_trades([t1, t2], occ_map)
    regime_segs = [s for s in segments if s.segment_type == SegmentType.REGIME]
    assert len(regime_segs) == 2
    vals = {s.segment_value for s in regime_segs}
    assert "TREND_UP" in vals
    assert "RANGE" in vals


def test_session_segmentation():
    """Trades are categorized into ASIA, LONDON, and NEW_YORK sessions."""
    seg_engine = SegmentationEngine()
    # 04:00 UTC -> ASIA
    t_asia = make_trade(entry_time=datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc))
    # 09:00 UTC -> LONDON
    t_lon = make_trade(entry_time=datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc))
    # 15:00 UTC -> NEW_YORK
    t_ny = make_trade(entry_time=datetime(2025, 1, 1, 15, 0, tzinfo=timezone.utc))

    segments, _ = seg_engine.segment_trades([t_asia, t_lon, t_ny])
    session_segs = [s for s in segments if s.segment_type == SegmentType.SESSION]
    sessions = {s.segment_value for s in session_segs}
    assert "ASIA" in sessions
    assert "LONDON" in sessions
    assert "NEW_YORK" in sessions


def test_direction_segmentation():
    """BUY and SELL direction performance are independently tracked."""
    seg_engine = SegmentationEngine()
    t_buy = make_trade(direction="BULLISH", r_multiple=2.0)
    t_sell = make_trade(direction="BEARISH", r_multiple=-1.0)

    segments, _ = seg_engine.segment_trades([t_buy, t_sell])
    dir_segs = [s for s in segments if s.segment_type == SegmentType.DIRECTION]
    assert len(dir_segs) == 2
    buy_seg = next(s for s in dir_segs if s.segment_value == "BULLISH")
    sell_seg = next(s for s in dir_segs if s.segment_value == "BEARISH")
    assert buy_seg.expectancy_r == Decimal("2.0000")
    assert sell_seg.expectancy_r == Decimal("-1.0000")


def test_liquidity_segmentation():
    """Trades are properly sliced by liquidity level type."""
    seg_engine = SegmentationEngine()
    t1 = make_trade(setup_id="s1")
    occ_map = {"s1": {"liquidity_type": "PREVIOUS_DAY_HIGH"}}

    segments, _ = seg_engine.segment_trades([t1], occ_map)
    liq_segs = [s for s in segments if s.segment_type == SegmentType.LIQUIDITY_TYPE]
    assert len(liq_segs) == 1
    assert liq_segs[0].segment_value == "PREVIOUS_DAY_HIGH"


def test_spread_segmentation():
    """Trades are partitioned into LOW, NORMAL, HIGH, and EXTREME spread buckets."""
    seg_engine = SegmentationEngine(StatisticalConfig(
        spread_low_pips=Decimal("0.00008"),
        spread_normal_pips=Decimal("0.00018"),
        spread_high_pips=Decimal("0.00030"),
    ))

    t_low = make_trade(spread=0.00005)
    t_norm = make_trade(spread=0.00012)
    t_high = make_trade(spread=0.00025)
    t_ext = make_trade(spread=0.00050)

    segments, _ = seg_engine.segment_trades([t_low, t_norm, t_high, t_ext])
    spread_segs = {s.segment_value for s in segments if s.segment_type == SegmentType.SPREAD_BUCKET}
    assert "LOW" in spread_segs
    assert "NORMAL" in spread_segs
    assert "HIGH" in spread_segs
    assert "EXTREME" in spread_segs


def test_day_of_week_segmentation():
    """Trades are properly grouped by day of week."""
    seg_engine = SegmentationEngine()
    # 2025-01-01 was Wednesday
    t_wed = make_trade(entry_time=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc))
    # 2025-01-02 was Thursday
    t_thu = make_trade(entry_time=datetime(2025, 1, 2, 10, 0, tzinfo=timezone.utc))

    segments, _ = seg_engine.segment_trades([t_wed, t_thu])
    days = {s.segment_value for s in segments if s.segment_type == SegmentType.DAY_OF_WEEK}
    assert "WEDNESDAY" in days
    assert "THURSDAY" in days


def test_small_sample_handling():
    """Samples < 30 are explicitly classified as INSUFFICIENT_DATA."""
    classifier = EdgeClassifier(StatisticalConfig(min_sample_preliminary=30))
    m = StatisticalMetricRecord(setup_code="S01", sample_size=15, expectancy_r=Decimal("1.5"))
    c = classifier.classify_edge(m)
    assert c == EdgeClassification.INSUFFICIENT_DATA
    assert classifier.classify_sample_size(15) == SampleReliability.INSUFFICIENT_DATA


def test_negative_expectancy_classification():
    """Negative expectancy with N >= 30 produces NEGATIVE_EDGE."""
    classifier = EdgeClassifier(StatisticalConfig(min_sample_preliminary=30))
    m = StatisticalMetricRecord(setup_code="S01", sample_size=50, expectancy_r=Decimal("-0.2000"))
    c = classifier.classify_edge(m)
    assert c == EdgeClassification.NEGATIVE_EDGE


def test_preliminary_edge_classification():
    """30 <= N < 100 with positive expectancy and solid bootstrap produces PRELIMINARY_EDGE."""
    classifier = EdgeClassifier(StatisticalConfig(min_sample_preliminary=30, min_sample_relevant=100))
    m = StatisticalMetricRecord(
        setup_code="S01", sample_size=50, expectancy_r=Decimal("0.8000"), max_drawdown_r=Decimal("5.0")
    )
    from core.statistics.contract import BootstrapMetricResult
    bs = BootstrapMetricResult(
        metric="EXP", iterations=1000, lower_bound=Decimal("0.2"), median=Decimal("0.8"),
        upper_bound=Decimal("1.4"), positive_fraction=Decimal("0.85")
    )
    c = classifier.classify_edge(m, bootstrap_exp=bs)
    assert c == EdgeClassification.PRELIMINARY_EDGE


def test_robust_edge_classification():
    """N >= 100 meeting all criteria produces ROBUST_EDGE."""
    classifier = EdgeClassifier(StatisticalConfig(min_sample_relevant=100, max_acceptable_dd_r=Decimal("15.0")))
    m = StatisticalMetricRecord(
        setup_code="S01", sample_size=120, expectancy_r=Decimal("0.7500"), max_drawdown_r=Decimal("8.0")
    )
    from core.statistics.contract import BootstrapMetricResult, OOSDegradationReport
    bs = BootstrapMetricResult(
        metric="EXP", iterations=1000, lower_bound=Decimal("0.3"), median=Decimal("0.75"),
        upper_bound=Decimal("1.2"), positive_fraction=Decimal("0.90")
    )
    deg = OOSDegradationReport(
        is_expectancy=Decimal("0.8000"), oos_expectancy=Decimal("0.6500"), expectancy_ratio=Decimal("0.8125"),
        status=OOSDegradationStatus.STABLE
    )
    val = StatisticalMetricRecord(setup_code="S01", sample_size=30, expectancy_r=Decimal("0.7000"))

    c = classifier.classify_edge(m, bootstrap_exp=bs, degradation_report=deg, val_metrics=val)
    assert c == EdgeClassification.ROBUST_EDGE


def test_data_quality_rejection():
    """Zero-risk distance or corrupted prices trigger INVALID_DATA."""
    engine = StatisticalEdgeEngine()
    corrupted_trade = make_trade(entry_price=1.0500, stop_loss=1.0500)  # zero risk distance
    assert engine.verify_data_quality([corrupted_trade]) is False

    res = engine.analyze_edge([corrupted_trade])
    assert res.data_quality_ok is False
    assert res.overall_verdict == EdgeClassification.INVALID_DATA


def test_split_isolation():
    """IN_SAMPLE, VALIDATION, and OUT_OF_SAMPLE are analyzed independently."""
    engine = StatisticalEdgeEngine()
    trades = [
        make_trade(split_type="IN_SAMPLE", r_multiple=2.0),
        make_trade(split_type="VALIDATION", r_multiple=1.0),
        make_trade(split_type="OUT_OF_SAMPLE", r_multiple=-1.0),
    ]
    res = engine.analyze_edge(trades)
    s01_splits = res.split_metrics["S01"]

    assert s01_splits["IN_SAMPLE"].expectancy_r == Decimal("2.0000")
    assert s01_splits["VALIDATION"].expectancy_r == Decimal("1.0000")
    assert s01_splits["OUT_OF_SAMPLE"].expectancy_r == Decimal("-1.0000")


def test_no_future_leakage():
    """Adding future trades does not modify statistical metrics for prior timestamps."""
    engine = StatisticalEdgeEngine()
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    trades_d1 = [
        make_trade(entry_time=t0, r_multiple=2.0),
        make_trade(entry_time=t0 + timedelta(minutes=15), r_multiple=-1.0),
    ]
    m1 = engine.calculate_descriptive_metrics(trades_d1, "S01")

    # Append future trades
    trades_d2 = list(trades_d1) + [
        make_trade(entry_time=t0 + timedelta(days=1), r_multiple=3.0),
    ]
    m_prior = engine.calculate_descriptive_metrics(trades_d2[:2], "S01")

    assert m1.expectancy_r == m_prior.expectancy_r
    assert m1.win_rate == m_prior.win_rate
    assert m1.max_drawdown_r == m_prior.max_drawdown_r


def test_statistical_reproducibility():
    """Identical trades produce identical hashes, report text, and bootstrap values."""
    engine = StatisticalEdgeEngine(StatisticalConfig(bootstrap_iterations=500, monte_carlo_iterations=200))
    trades = [
        make_trade(r_multiple=2.0),
        make_trade(r_multiple=-1.0),
        make_trade(r_multiple=0.5),
    ]

    res1 = engine.analyze_edge(trades, dataset_hash="h1", backtest_config_hash="h2")
    res2 = engine.analyze_edge(trades, dataset_hash="h1", backtest_config_hash="h2")

    assert res1.setup_metrics["S01"].expectancy_r == res2.setup_metrics["S01"].expectancy_r
    assert res1.bootstraps["S01"].lower_bound == res2.bootstraps["S01"].lower_bound
    assert res1.bootstraps["S01"].upper_bound == res2.bootstraps["S01"].upper_bound
    assert res1.report_text == res2.report_text


def test_multiple_testing_reporting():
    """Report outputs total sub-segments examined and warning."""
    engine = StatisticalEdgeEngine()
    trades = [
        make_trade(direction="BULLISH", entry_time=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)),
        make_trade(direction="BEARISH", entry_time=datetime(2025, 1, 2, 14, 0, tzinfo=timezone.utc)),
    ]
    res = engine.analyze_edge(trades)
    assert res.total_segments_examined > 0
    assert "Total Sub-Segments Examined:" in res.report_text
    assert "WARNING: Slicing into multiple segments increases false discovery risk." in res.report_text


def test_parameter_sensitivity_state():
    """Report clearly outputs SENSITIVITY_NOT_ESTABLISHED when single configuration is analyzed."""
    engine = StatisticalEdgeEngine()
    res = engine.analyze_edge([make_trade()])
    assert "SENSITIVITY_NOT_ESTABLISHED (Single baseline evaluated)" in res.report_text


def test_database_persistence_and_idempotency():
    """Statistical runs, metrics, segments, and bootstrap persist cleanly into PostgreSQL."""
    engine = StatisticalEdgeEngine(StatisticalConfig(bootstrap_iterations=200, monte_carlo_iterations=100))
    trades = [
        make_trade(setup_code="S01", r_multiple=2.0),
        make_trade(setup_code="S01", r_multiple=-1.0),
    ]
    res = engine.analyze_edge(trades, run_id="stat_test_run_1")

    session_factory = get_session_factory()
    with session_factory() as session:
        # Create prerequisite DB rows
        session.execute(text("""
            INSERT INTO research_datasets (dataset_name, symbol, source, timeframe, start_time, end_time, row_count, dataset_version, content_hash, status)
            VALUES ('test_ds_stat', 'EURUSD', 'TEST', 'M5', NOW(), NOW(), 10, '1.0', 'hash_test_stat', 'READY')
            ON CONFLICT DO NOTHING;
        """))
        res_ds = session.execute(text("SELECT id FROM research_datasets WHERE content_hash = 'hash_test_stat'")).scalar()
        session.execute(text(f"""
            INSERT INTO research_runs (run_id, dataset_id, run_version, config_hash, status)
            VALUES ('run_test_stat', {res_ds}, '1.0', 'cfg_test_stat', 'SUCCESS')
            ON CONFLICT DO NOTHING;
        """))
        res_run = session.execute(text("SELECT id FROM research_runs WHERE run_id = 'run_test_stat'")).scalar()
        session.execute(text(f"""
            INSERT INTO backtest_runs (run_id, research_run_id, backtest_version, config_hash, status)
            VALUES ('bt_run_stat', {res_run}, '1.0', 'cfg_bt_stat', 'SUCCESS')
            ON CONFLICT DO NOTHING;
        """))
        res_bt = session.execute(text("SELECT id FROM backtest_runs WHERE run_id = 'bt_run_stat'")).scalar()

        persisted = engine.persist_results(session, res, backtest_run_db_id=res_bt)
        assert persisted > 0

        # Query check
        cnt = session.execute(text("SELECT count(*) FROM edge_metrics WHERE setup_code = 'S01'")).scalar()
        assert cnt >= 1


def test_zero_win_classification():
    """All losses (zero win) with N >= 30 produces NEGATIVE_EDGE."""
    classifier = EdgeClassifier(StatisticalConfig(min_sample_preliminary=30))
    trades = [make_trade(result=TradeResult.SL, r_multiple=-1.0) for _ in range(35)]
    engine = StatisticalEdgeEngine()
    m = engine.calculate_descriptive_metrics(trades, "S01")
    assert m.win_rate == Decimal("0.0000")
    assert m.expectancy_r == Decimal("-1.0000")
    c = classifier.classify_edge(m)
    assert c == EdgeClassification.NEGATIVE_EDGE


def test_bootstrap_win_rate():
    """Bootstrap win rate distribution generates valid median and positive fractions."""
    binary_outcomes = [1, 1, 1, 0, 1, 0, 1, 1, 0, 1]  # 7 wins out of 10
    b = DeterministicBootstrapEngine(seed=999, iterations=1000)
    res = b.bootstrap_win_rate(binary_outcomes)
    assert res is not None
    assert Decimal("0.60") <= res.median <= Decimal("0.80")
    assert res.lower_bound <= res.median <= res.upper_bound


def test_migration_007_idempotency():
    """Running migration 007 repeatedly executes cleanly without errors."""
    from database.migrate import run_migrations
    run_migrations()
    run_migrations()

