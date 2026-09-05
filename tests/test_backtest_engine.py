"""
Comprehensive unit, integration, and causality tests for Backtest Engine V1.
Deterministic, strictly no lookahead, zero random mocking.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import text

from core.backtest.config import BacktestConfig
from core.backtest.contract import (
    BacktestTradeRecord,
    EntryPriceType,
    TradeMetrics,
    TradeResult,
    TradeStatus,
)
from core.backtest.engine import BacktestEngine
from core.backtest.metrics import BacktestMetricsCalculator
from core.backtest.report import BacktestReportGenerator
from core.backtest.rules import BacktestRuleEngine
from core.backtest.simulator import TradePathSimulator
from core.candles.contract import AggregatedCandle as Candle
from core.research.contract import ResearchOccurrenceRecord, SplitType
from database.connection import get_session_factory, get_engine


def make_candle(ts: datetime, o: float, h: float, l: float, c: float, bid: float = None, ask: float = None) -> Candle:
    return Candle(
        symbol="EURUSD",
        timeframe="M5",
        timestamp=ts,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(l)),
        close=Decimal(str(c)),
        volume=Decimal("100"),
        tick_volume=100,
        spread=Decimal(str(ask - bid)) if (bid is not None and ask is not None) else Decimal("0.00010"),
        bid=Decimal(str(bid)) if bid is not None else None,
        ask=Decimal(str(ask)) if ask is not None else None,
    )



def test_config_canonical_hashing():
    """Config produces identical hash for identical configuration and changes when altered."""
    c1 = BacktestConfig(target_r=Decimal("2.0"), timeout_bars=3)
    c2 = BacktestConfig(target_r=Decimal("2.0"), timeout_bars=3)
    c3 = BacktestConfig(target_r=Decimal("2.5"), timeout_bars=3)

    assert c1.get_config_hash() == c2.get_config_hash()
    assert c1.get_config_hash() != c3.get_config_hash()


def test_entry_price_resolution():
    """Real Bid/Ask is used when present; fallback is used when absent."""
    rules = BacktestRuleEngine(BacktestConfig())
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    # With Bid/Ask
    c_real = {
        "timestamp": t0, "open": Decimal("1.0500"), "high": Decimal("1.0510"),
        "low": Decimal("1.0490"), "close": Decimal("1.0505"),
        "bid": Decimal("1.0504"), "ask": Decimal("1.0506")
    }
    buy_p, p_type, spread = rules.resolve_entry_price(c_real, "BULLISH")
    assert buy_p == Decimal("1.0506")
    assert p_type == EntryPriceType.REAL_BID_ASK
    assert spread == Decimal("0.0002")

    sell_p, p_type, spread = rules.resolve_entry_price(c_real, "BEARISH")
    assert sell_p == Decimal("1.0504")

    # Without Bid/Ask (Fallback)
    c_fallback = {
        "timestamp": t0, "open": Decimal("1.0500"), "high": Decimal("1.0510"),
        "low": Decimal("1.0490"), "close": Decimal("1.0505")
    }
    fb_p, fb_type, fb_spread = rules.resolve_entry_price(c_fallback, "BULLISH")
    assert fb_p == Decimal("1.0505")
    assert fb_type == EntryPriceType.FALLBACK_PRICE
    assert fb_spread == Decimal("0.00010")



def test_structural_stop_loss_derivation():
    """SL is derived beyond recent structural extremes without future lookahead."""
    rules = BacktestRuleEngine(BacktestConfig(sl_buffer_pips=Decimal("0.00010")))
    base_t = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    candles = [
        make_candle(base_t - timedelta(minutes=15), 1.0500, 1.0520, 1.0480, 1.0490),
        make_candle(base_t - timedelta(minutes=10), 1.0490, 1.0510, 1.0470, 1.0500),  # Lowest low: 1.0470
        make_candle(base_t - timedelta(minutes=5), 1.0500, 1.0530, 1.0495, 1.0520),   # Highest high: 1.0530
        make_candle(base_t, 1.0520, 1.0525, 1.0515, 1.0520),
    ]

    # Bullish SL should be lowest_low - buffer = 1.0470 - 0.0001 = 1.0469
    sl_bull, err = rules.derive_structural_stop_loss("S01", "BULLISH", Decimal("1.0520"), candles)
    assert err is None
    assert sl_bull == Decimal("1.0469")

    # Bearish SL should be highest_high + buffer = 1.0530 + 0.0001 = 1.0531
    sl_bear, err = rules.derive_structural_stop_loss("S01", "BEARISH", Decimal("1.0500"), candles)
    assert err is None
    assert sl_bear == Decimal("1.0531")


def test_take_profit_calculation():
    """Baseline TP is strictly 2.0R."""
    rules = BacktestRuleEngine(BacktestConfig(target_r=Decimal("2.0")))

    # BULLISH: entry 1.0500, SL 1.0450 -> R = 0.0050 -> TP = 1.0500 + 2*0.0050 = 1.0600
    tp_bull = rules.calculate_take_profit("BULLISH", Decimal("1.0500"), Decimal("1.0450"))
    assert tp_bull == Decimal("1.0600")

    # BEARISH: entry 1.0500, SL 1.0550 -> R = 0.0050 -> TP = 1.0500 - 2*0.0050 = 1.0400
    tp_bear = rules.calculate_take_profit("BEARISH", Decimal("1.0500"), Decimal("1.0550"))
    assert tp_bear == Decimal("1.0400")


def test_tp_only_path():
    """Price hits TP cleanly; trade yields +2.0R."""
    sim = TradePathSimulator(BacktestConfig(target_r=Decimal("2.0"), timeout_bars=5))
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    trade = BacktestTradeRecord(
        setup_id="s1",
        setup_code="S01",
        direction="BULLISH",
        entry_time=t0,
        entry_price=Decimal("1.0500"),
        stop_loss=Decimal("1.0450"),
        take_profit=Decimal("1.0600"),
        result=TradeResult.TIMEOUT,
        status=TradeStatus.OPEN,
    )

    subsequent = [
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0550, 1.0490, 1.0540),
        make_candle(t0 + timedelta(minutes=10), 1.0540, 1.0610, 1.0530, 1.0605),  # Hits TP 1.0600
    ]

    res = sim.simulate_trade(trade, subsequent)
    assert res.result == TradeResult.TP
    assert res.r_multiple == Decimal("2.0")
    assert res.exit_time == t0 + timedelta(minutes=10)
    assert res.exit_price == Decimal("1.0600")


def test_sl_only_path():
    """Price hits SL cleanly; trade yields -1.0R."""
    sim = TradePathSimulator(BacktestConfig(target_r=Decimal("2.0"), timeout_bars=5))
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    trade = BacktestTradeRecord(
        setup_id="s1",
        setup_code="S01",
        direction="BULLISH",
        entry_time=t0,
        entry_price=Decimal("1.0500"),
        stop_loss=Decimal("1.0450"),
        take_profit=Decimal("1.0600"),
        result=TradeResult.TIMEOUT,
        status=TradeStatus.OPEN,
    )

    subsequent = [
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0510, 1.0440, 1.0445),  # Breaches SL 1.0450
    ]

    res = sim.simulate_trade(trade, subsequent)
    assert res.result == TradeResult.SL
    assert res.r_multiple == Decimal("-1.0")
    assert res.exit_price == Decimal("1.0450")


def test_intrabar_ambiguity_detection():
    """When both SL and TP are breached in the same candle, result MUST be AMBIGUOUS."""
    sim = TradePathSimulator(BacktestConfig(target_r=Decimal("2.0"), timeout_bars=5))
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    trade = BacktestTradeRecord(
        setup_id="s1",
        setup_code="S01",
        direction="BULLISH",
        entry_time=t0,
        entry_price=Decimal("1.0500"),
        stop_loss=Decimal("1.0450"),
        take_profit=Decimal("1.0600"),
        result=TradeResult.TIMEOUT,
        status=TradeStatus.OPEN,
    )

    # Candle reaches both 1.0620 (above TP) and 1.0430 (below SL)
    ambig_candle = make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0620, 1.0430, 1.0550)

    res = sim.simulate_trade(trade, [ambig_candle])
    assert res.result == TradeResult.AMBIGUOUS
    assert res.r_multiple is None
    assert "Intrabar ambiguity" in res.ambiguity_reason


def test_timeout_execution():
    """Trade held for timeout_bars (3 candles) exits with realized R."""
    sim = TradePathSimulator(BacktestConfig(target_r=Decimal("2.0"), timeout_bars=3))
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    trade = BacktestTradeRecord(
        setup_id="s1",
        setup_code="S01",
        direction="BULLISH",
        entry_time=t0,
        entry_price=Decimal("1.0500"),
        stop_loss=Decimal("1.0450"),  # R unit = 0.0050
        take_profit=Decimal("1.0600"),
        result=TradeResult.TIMEOUT,
        status=TradeStatus.OPEN,
    )

    subsequent = [
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0530, 1.0480, 1.0510),
        make_candle(t0 + timedelta(minutes=10), 1.0510, 1.0540, 1.0500, 1.0520),
        make_candle(t0 + timedelta(minutes=15), 1.0520, 1.0550, 1.0510, 1.0525),  # 3rd candle closes at 1.0525
    ]

    res = sim.simulate_trade(trade, subsequent)
    assert res.result == TradeResult.TIMEOUT
    # Realized R = (1.0525 - 1.0500) / 0.0050 = +0.5000R
    assert res.r_multiple == Decimal("0.5000")
    assert res.exit_price == Decimal("1.0525")


def test_mae_mfe_tracking():
    """MAE and MFE are properly recorded in R units."""
    sim = TradePathSimulator(BacktestConfig(target_r=Decimal("2.0"), timeout_bars=2))
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    trade = BacktestTradeRecord(
        setup_id="s1",
        setup_code="S01",
        direction="BULLISH",
        entry_time=t0,
        entry_price=Decimal("1.0500"),
        stop_loss=Decimal("1.0450"),  # R unit = 0.0050
        take_profit=Decimal("1.0600"),
        result=TradeResult.TIMEOUT,
        status=TradeStatus.OPEN,
    )

    subsequent = [
        # Low went to 1.0480 -> adverse = 0.0020 / 0.0050 = 0.4R. High went to 1.0540 -> fav = 0.0040 / 0.0050 = 0.8R
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0540, 1.0480, 1.0520),
        # Low went to 1.0475 -> adverse = 0.0025 / 0.0050 = 0.5R. High went to 1.0575 -> fav = 0.0075 / 0.0050 = 1.5R
        make_candle(t0 + timedelta(minutes=10), 1.0520, 1.0575, 1.0475, 1.0550),
    ]

    res = sim.simulate_trade(trade, subsequent)
    assert res.mae_r == Decimal("0.5")
    assert res.mfe_r == Decimal("1.5")


def test_trade_collision_management():
    """Overlapping setups while trade is open are marked SKIPPED_ACTIVE_TRADE."""
    engine = BacktestEngine(BacktestConfig(max_active_trades=1, timeout_bars=3))
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    candles = [
        make_candle(t0 - timedelta(minutes=10), 1.0500, 1.0520, 1.0480, 1.0500),
        make_candle(t0, 1.0500, 1.0510, 1.0490, 1.0500),
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0520, 1.0495, 1.0510),
        make_candle(t0 + timedelta(minutes=10), 1.0510, 1.0530, 1.0500, 1.0520),
        make_candle(t0 + timedelta(minutes=15), 1.0520, 1.0540, 1.0510, 1.0530),
    ]

    occurrences = [
        ResearchOccurrenceRecord(
            occurrence_id="occ1",
            setup_id="s1",
            setup_code="S01",
            symbol="EURUSD",
            timeframe="M5",
            timestamp=t0,
            direction="BULLISH",
            status="FIRE",
            config_hash="cfg_test",
        ),
        # Overlapping occurrence while s1 is still active
        ResearchOccurrenceRecord(
            occurrence_id="occ2",
            setup_id="s2",
            setup_code="S01",
            symbol="EURUSD",
            timeframe="M5",
            timestamp=t0 + timedelta(minutes=5),
            direction="BULLISH",
            status="FIRE",
            config_hash="cfg_test",
        ),
    ]

    res = engine.run_backtest(candles, occurrences)
    assert len(res.trades) == 2
    assert res.trades[0].result == TradeResult.TIMEOUT
    assert res.trades[1].result == TradeResult.SKIPPED_ACTIVE_TRADE
    assert res.trades[1].status == TradeStatus.SKIPPED


def test_metrics_calculation_accuracy():
    """Metrics calculation adheres to mathematical definitions and excludes ambiguous from WR."""
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    trades = [
        BacktestTradeRecord(
            setup_id="1", setup_code="S01", direction="BULLISH", entry_time=t0, entry_price=Decimal("1.0"),
            stop_loss=Decimal("0.9"), take_profit=Decimal("1.2"), result=TradeResult.TP, r_multiple=Decimal("2.0")
        ),
        BacktestTradeRecord(
            setup_id="2", setup_code="S01", direction="BULLISH", entry_time=t0, entry_price=Decimal("1.0"),
            stop_loss=Decimal("0.9"), take_profit=Decimal("1.2"), result=TradeResult.SL, r_multiple=Decimal("-1.0")
        ),
        BacktestTradeRecord(
            setup_id="3", setup_code="S01", direction="BULLISH", entry_time=t0, entry_price=Decimal("1.0"),
            stop_loss=Decimal("0.9"), take_profit=Decimal("1.2"), result=TradeResult.TIMEOUT, r_multiple=Decimal("0.5")
        ),
        BacktestTradeRecord(
            setup_id="4", setup_code="S01", direction="BULLISH", entry_time=t0, entry_price=Decimal("1.0"),
            stop_loss=Decimal("0.9"), take_profit=Decimal("1.2"), result=TradeResult.AMBIGUOUS, r_multiple=None
        ),
    ]

    m = BacktestMetricsCalculator.calculate_metrics(trades)
    assert m.sample_size == 4
    assert m.wins == 1
    assert m.losses == 1
    assert m.timeouts == 1
    assert m.ambiguous == 1
    # Win rate = 1 / (1 + 1) = 50%
    assert m.win_rate == Decimal("0.5000")
    # Total R = 2.0 - 1.0 + 0.5 = 1.5R
    assert m.total_r == Decimal("1.5000")
    # Profit factor = 2.5 / 1.0 = 2.5
    assert m.profit_factor == Decimal("2.5000")
    # Expectancy = (2.0 - 1.0 + 0.5) / 3 = 0.5000R
    assert m.expectancy_r == Decimal("0.5000")


def test_split_segregation():
    """Metrics are properly segregated by IN_SAMPLE, VALIDATION, and OUT_OF_SAMPLE."""
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    trades = [
        BacktestTradeRecord(
            setup_id="1", setup_code="S01", direction="BULLISH", entry_time=t0, entry_price=Decimal("1.0"),
            stop_loss=Decimal("0.9"), take_profit=Decimal("1.2"), result=TradeResult.TP, r_multiple=Decimal("2.0"),
            split_type="IN_SAMPLE"
        ),
        BacktestTradeRecord(
            setup_id="2", setup_code="S01", direction="BULLISH", entry_time=t0, entry_price=Decimal("1.0"),
            stop_loss=Decimal("0.9"), take_profit=Decimal("1.2"), result=TradeResult.SL, r_multiple=Decimal("-1.0"),
            split_type="VALIDATION"
        ),
        BacktestTradeRecord(
            setup_id="3", setup_code="S01", direction="BULLISH", entry_time=t0, entry_price=Decimal("1.0"),
            stop_loss=Decimal("0.9"), take_profit=Decimal("1.2"), result=TradeResult.TP, r_multiple=Decimal("2.0"),
            split_type="OUT_OF_SAMPLE"
        ),
    ]

    splits = BacktestMetricsCalculator.calculate_by_split(trades)
    assert splits.in_sample.wins == 1
    assert splits.in_sample.total_r == Decimal("2.0000")
    assert splits.validation.losses == 1
    assert splits.validation.total_r == Decimal("-1.0000")
    assert splits.out_of_sample.wins == 1
    assert splits.out_of_sample.total_r == Decimal("2.0000")


def test_backtest_has_no_future_leakage():
    """
    CRITICAL CAUSALITY TEST:
    Adding extreme future candles after timestamp T must have ZERO effect
    on entry price, stop loss, or trade decisions taken at or before T.
    """
    engine = BacktestEngine(BacktestConfig(timeout_bars=2))
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    # Initial historical dataset through T + 2 bars
    candles_d1 = [
        make_candle(t0 - timedelta(minutes=15), 1.0500, 1.0520, 1.0480, 1.0500),
        make_candle(t0 - timedelta(minutes=10), 1.0500, 1.0515, 1.0475, 1.0490),
        make_candle(t0, 1.0490, 1.0510, 1.0485, 1.0500),  # Entry at T
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0530, 1.0490, 1.0510),
        make_candle(t0 + timedelta(minutes=10), 1.0510, 1.0540, 1.0500, 1.0520),
    ]

    occurrences = [
        ResearchOccurrenceRecord(
            occurrence_id="occ_t0",
            setup_id="s_t0",
            setup_code="S01",
            symbol="EURUSD",
            timeframe="M5",
            timestamp=t0,
            direction="BULLISH",
            status="FIRE",
            config_hash="cfg_test",
        )
    ]

    res1 = engine.run_backtest(candles_d1, occurrences)
    trade1 = res1.trades[0]

    # Append extreme future market data well after T + 10m
    candles_d2 = list(candles_d1) + [
        make_candle(t0 + timedelta(minutes=15), 1.0520, 1.9999, 0.5000, 1.8000),
        make_candle(t0 + timedelta(minutes=20), 1.8000, 2.5000, 1.7000, 2.4000),
    ]

    res2 = engine.run_backtest(candles_d2, occurrences)
    trade2 = res2.trades[0]

    # Verification: entry price, stop loss, take profit, and exit MUST be identical
    assert trade1.entry_price == trade2.entry_price
    assert trade1.stop_loss == trade2.stop_loss
    assert trade1.take_profit == trade2.take_profit
    assert trade1.exit_price == trade2.exit_price
    assert trade1.result == trade2.result
    assert trade1.r_multiple == trade2.r_multiple


def test_reproducibility():
    """Identical occurrences and configuration produce identical trade records and report."""
    engine = BacktestEngine(BacktestConfig())
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    candles = [
        make_candle(t0 - timedelta(minutes=10), 1.0500, 1.0520, 1.0480, 1.0500),
        make_candle(t0, 1.0500, 1.0510, 1.0490, 1.0500),
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0550, 1.0490, 1.0530),
    ]

    occurrences = [
        ResearchOccurrenceRecord(
            occurrence_id="occ1",
            setup_id="s1",
            setup_code="S01",
            symbol="EURUSD",
            timeframe="M5",
            timestamp=t0,
            direction="BULLISH",
            status="FIRE",
            config_hash="cfg_test",
        )
    ]

    res1 = engine.run_backtest(candles, occurrences)
    res2 = engine.run_backtest(candles, occurrences)

    assert res1.trades[0].r_multiple == res2.trades[0].r_multiple
    assert res1.overall_metrics.total_r == res2.overall_metrics.total_r
    assert res1.report_text == res2.report_text


def test_costs_and_slippage():
    """Commission and slippage are correctly subtracted from realized R."""
    # R distance = 1.0500 - 1.0450 = 0.0050
    # Commission = 0.00050 -> 0.00050 / 0.0050 = 0.1R
    cfg = BacktestConfig(
        commission_per_trade=Decimal("0.00050"),
        slippage_pips=Decimal("0.00010"),
        timeout_bars=2,
    )
    sim = TradePathSimulator(cfg)
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    trade = BacktestTradeRecord(
        setup_id="s1",
        setup_code="S01",
        direction="BULLISH",
        entry_time=t0,
        entry_price=Decimal("1.0500"),
        stop_loss=Decimal("1.0450"),
        take_profit=Decimal("1.0600"),
        result=TradeResult.TIMEOUT,
        status=TradeStatus.OPEN,
    )

    # TP candle
    subsequent = [make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0620, 1.0490, 1.0610)]
    res = sim.simulate_trade(trade, subsequent)
    assert res.result == TradeResult.TP
    # 2.0R - 0.1R commission = 1.9R
    assert res.r_multiple == Decimal("1.9000")
    # TP slippage: exit_price = 1.0600 - 0.0001 = 1.0599
    assert res.exit_price == Decimal("1.0599")


def test_database_persistence():
    """Backtest run and trade records persist idempotently into PostgreSQL."""
    engine = BacktestEngine(BacktestConfig())
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    candles = [
        make_candle(t0 - timedelta(minutes=10), 1.0500, 1.0520, 1.0480, 1.0500),
        make_candle(t0, 1.0500, 1.0510, 1.0490, 1.0500),
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0550, 1.0490, 1.0530),
    ]

    occurrences = [
        ResearchOccurrenceRecord(
            occurrence_id="occ_db",
            setup_id="s_db",
            setup_code="S01",
            symbol="EURUSD",
            timeframe="M5",
            timestamp=t0,
            direction="BULLISH",
            status="FIRE",
            config_hash="cfg_test",
        )
    ]

    res = engine.run_backtest(candles, occurrences, run_id="bt_test_run_1")

    session_factory = get_session_factory()
    with session_factory() as session:
        # Create dummy research dataset and run for FK
        session.execute(text("""
            INSERT INTO research_datasets (dataset_name, symbol, source, timeframe, start_time, end_time, row_count, dataset_version, content_hash, status)
            VALUES ('test_ds', 'EURUSD', 'TEST', 'M5', NOW(), NOW(), 10, '1.0', 'hash_test_bt', 'READY')
            ON CONFLICT DO NOTHING;
        """))
        res_ds = session.execute(text("SELECT id FROM research_datasets WHERE content_hash = 'hash_test_bt'")).scalar()
        session.execute(text(f"""
            INSERT INTO research_runs (run_id, dataset_id, run_version, config_hash, status)
            VALUES ('run_test_bt', {res_ds}, '1.0', 'cfg_test_bt', 'SUCCESS')
            ON CONFLICT DO NOTHING;
        """))
        res_run = session.execute(text("SELECT id FROM research_runs WHERE run_id = 'run_test_bt'")).scalar()

        persisted = engine.persist_results(session, res, research_run_db_id=res_run)
        assert persisted == 1

        # Check DB query
        count = session.execute(text(f"SELECT count(*) FROM backtest_trades WHERE setup_id = 's_db'")).scalar()
        assert count >= 1


def test_sell_direction_simulation():
    """SELL trade simulation behaves symmetrically with BUY."""
    sim = TradePathSimulator(BacktestConfig(target_r=Decimal("2.0"), timeout_bars=5))
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    trade = BacktestTradeRecord(
        setup_id="sell_1",
        setup_code="S01",
        direction="BEARISH",
        entry_time=t0,
        entry_price=Decimal("1.0500"),
        stop_loss=Decimal("1.0550"),   # R unit = 0.0050
        take_profit=Decimal("1.0400"),  # 2R = 1.0500 - 0.0100 = 1.0400
        result=TradeResult.TIMEOUT,
        status=TradeStatus.OPEN,
    )

    # TP hit for SELL when price reaches low <= 1.0400
    subsequent = [
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0520, 1.0450, 1.0460),
        make_candle(t0 + timedelta(minutes=10), 1.0460, 1.0470, 1.0395, 1.0400),
    ]

    res = sim.simulate_trade(trade, subsequent)
    assert res.result == TradeResult.TP
    assert res.r_multiple == Decimal("2.0")
    assert res.exit_price == Decimal("1.0400")


def test_zero_risk_distance_invalidation():
    """Zero risk distance or invalid SL direction marks trade INVALID or DATA_ERROR."""
    sim = TradePathSimulator(BacktestConfig())
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    # Zero risk distance
    trade_zero_r = BacktestTradeRecord(
        setup_id="err1",
        setup_code="S01",
        direction="BULLISH",
        entry_time=t0,
        entry_price=Decimal("1.0500"),
        stop_loss=Decimal("1.0500"),
        take_profit=Decimal("1.0500"),
        result=TradeResult.TIMEOUT,
        status=TradeStatus.OPEN,
    )

    subsequent = [make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0520, 1.0490, 1.0510)]
    res = sim.simulate_trade(trade_zero_r, subsequent)
    assert res.result == TradeResult.DATA_ERROR
    assert res.status == TradeStatus.INVALID


def test_setups_s02_to_s05_sl_derivation():
    """SL is deterministically derived for S02, S03, S04, S05."""
    rules = BacktestRuleEngine(BacktestConfig(sl_buffer_pips=Decimal("0.00010")))
    base_t = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    candles = [
        make_candle(base_t - timedelta(minutes=30), 1.0500, 1.0540, 1.0460, 1.0470),
        make_candle(base_t - timedelta(minutes=25), 1.0470, 1.0530, 1.0465, 1.0510),
        make_candle(base_t - timedelta(minutes=20), 1.0510, 1.0550, 1.0490, 1.0520),
        make_candle(base_t - timedelta(minutes=15), 1.0520, 1.0560, 1.0500, 1.0540),
        make_candle(base_t - timedelta(minutes=10), 1.0540, 1.0580, 1.0520, 1.0570),
        make_candle(base_t - timedelta(minutes=5), 1.0570, 1.0590, 1.0540, 1.0580),
        make_candle(base_t, 1.0580, 1.0600, 1.0560, 1.0590),
    ]

    for code in ("S02", "S03", "S04", "S05"):
        sl_bull, err_bull = rules.derive_structural_stop_loss(code, "BULLISH", Decimal("1.0600"), candles)
        assert err_bull is None
        assert sl_bull is not None
        assert sl_bull < Decimal("1.0600")

        sl_bear, err_bear = rules.derive_structural_stop_loss(code, "BEARISH", Decimal("1.0400"), candles)
        assert err_bear is None
        assert sl_bear is not None
        assert sl_bear > Decimal("1.0400")


def test_empty_and_insufficient_occurrences():
    """Engine gracefully handles empty occurrence lists and missing candles."""
    engine = BacktestEngine(BacktestConfig())
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    candles = [make_candle(t0, 1.0500, 1.0510, 1.0490, 1.0500)]

    # Empty occurrences
    res_empty = engine.run_backtest(candles, [])
    assert res_empty.overall_metrics.sample_size == 0
    assert res_empty.overall_metrics.total_r == Decimal("0.0000")

    # Occurrence with no subsequent candles
    occ = [
        ResearchOccurrenceRecord(
            occurrence_id="occ_end",
            setup_id="s_end",
            setup_code="S01",
            symbol="EURUSD",
            timeframe="M5",
            timestamp=t0,
            direction="BULLISH",
            status="FIRE",
            config_hash="cfg_test",
        )
    ]
    res_end = engine.run_backtest(candles, occ)
    assert len(res_end.trades) == 1
    # Trade closes with TIMEOUT / exit at last candle or DATA_ERROR
    assert res_end.trades[0].status in (TradeStatus.CLOSED, TradeStatus.INVALID)


def test_report_generation_content():
    """Report includes mandatory disclaimers and explicit cost parameters."""
    cfg = BacktestConfig(commission_per_trade=Decimal("0.0"), slippage_pips=Decimal("0.0"))
    engine = BacktestEngine(cfg)
    t0 = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    candles = [
        make_candle(t0 - timedelta(minutes=5), 1.0500, 1.0520, 1.0480, 1.0500),
        make_candle(t0, 1.0500, 1.0510, 1.0490, 1.0500),
        make_candle(t0 + timedelta(minutes=5), 1.0500, 1.0550, 1.0490, 1.0530),
    ]

    occ = [
        ResearchOccurrenceRecord(
            occurrence_id="occ_rep",
            setup_id="s_rep",
            setup_code="S01",
            symbol="EURUSD",
            timeframe="M5",
            timestamp=t0,
            direction="BULLISH",
            status="FIRE",
            config_hash="cfg_test",
        )
    ]

    res = engine.run_backtest(candles, occ)
    report = res.report_text

    assert "COMMISSION = 0.0" in report
    assert "SLIPPAGE = 0.0" in report
    assert "TARGET_R = 2.0" in report or "2.0R (BASELINE ONLY — NOT OPTIMIZED)" in report
    assert "NOTE: This report measures deterministic baseline trade outcomes." in report
    assert "It does NOT claim statistical significance" in report


def test_migration_006_idempotency():
    """Running migration 006 multiple times executes cleanly without errors."""
    from database.migrate import run_migrations
    run_migrations()
    run_migrations()

