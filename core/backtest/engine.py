"""
End-to-end Backtest Engine V1 for Trader Machine.
Coordinates deterministic trade rule generation, sequential path simulation,
intrabar ambiguity handling, collision management, metrics calculation, and database persistence.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence
import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.backtest.collision import CollisionManager
from core.backtest.config import BacktestConfig
from core.backtest.contract import (
    BacktestRunRecord,
    BacktestTradeRecord,
    EntryPriceType,
    SplitMetrics,
    TradeMetrics,
    TradeResult,
    TradeStatus,
)
from core.backtest.metrics import BacktestMetricsCalculator
from core.backtest.report import BacktestReportGenerator
from core.backtest.rules import BacktestRuleEngine
from core.backtest.simulator import TradePathSimulator
from core.setups.common import ensure_utc, get_val
from database.models import BacktestRun as BacktestRunModel, BacktestTrade as BacktestTradeModel


class BacktestRunResult:
    """Encapsulates all outputs produced by a BacktestEngine execution."""

    def __init__(
        self,
        run_id: str,
        run_record: BacktestRunRecord,
        trades: List[BacktestTradeRecord],
        overall_metrics: TradeMetrics,
        setup_metrics: Dict[str, TradeMetrics],
        split_metrics: SplitMetrics,
        report_text: str,
    ):
        self.run_id = run_id
        self.run_record = run_record
        self.trades = trades
        self.overall_metrics = overall_metrics
        self.setup_metrics = setup_metrics
        self.split_metrics = split_metrics
        self.report_text = report_text


class BacktestEngine:
    """
    Simulates historical trade execution for deterministic setup occurrences.
    Strictly preserves causality: decision at T uses only data <= T.
    """

    def __init__(
        self,
        symbol: Any = "EURUSD",
        timeframe: str = "M5",
        config: Optional[BacktestConfig] = None,
    ):
        if isinstance(symbol, BacktestConfig):
            self.config = symbol
            self.symbol = "EURUSD"
        else:
            self.symbol = str(symbol).strip().upper()
            self.config = config or BacktestConfig()
        self.timeframe = timeframe.strip().upper()

        self.rule_engine = BacktestRuleEngine(config=self.config)
        self.simulator = TradePathSimulator(config=self.config)
        self.collision_manager = CollisionManager(config=self.config)

    def run_backtest(
        self,
        candles: Sequence[Any],
        occurrences: Sequence[Any],
        research_run_id: Optional[int] = None,
        run_id: Optional[str] = None,
        backtest_version: str = "1.0.0",
    ) -> BacktestRunResult:
        """
        Executes deterministic backtest on provided setup occurrences and candles.
        """
        active_run_id = run_id or f"bt_{uuid.uuid4().hex[:12]}"
        config_hash = self.config.get_config_hash()

        # 1. Sort candles chronologically
        sorted_candles = sorted(candles, key=lambda c: ensure_utc(get_val(c, "timestamp")))

        # 2. Filter FIRE occurrences only and sort chronologically
        fire_occurrences = [
            occ for occ in occurrences
            if str(get_val(occ, "status")).upper() == "FIRE"
        ]
        sorted_occurrences = sorted(fire_occurrences, key=lambda o: ensure_utc(get_val(o, "timestamp")))

        executed_trades: List[BacktestTradeRecord] = []

        # 3. Simulate each occurrence sequentially
        for occ in sorted_occurrences:
            occ_ts = ensure_utc(get_val(occ, "timestamp"))
            occ_setup_id = str(get_val(occ, "setup_id"))
            occ_code = str(get_val(occ, "setup_code"))
            occ_direction = str(get_val(occ, "direction"))
            split_raw = get_val(occ, "split_type", "IN_SAMPLE")
            occ_split = split_raw.value if hasattr(split_raw, "value") else str(split_raw)
            if occ_split.startswith("SplitType."):
                occ_split = occ_split.replace("SplitType.", "")

            # Candles available up to entry timestamp T
            candles_up_to_t = [c for c in sorted_candles if ensure_utc(get_val(c, "timestamp")) <= occ_ts]
            if not candles_up_to_t:
                continue

            entry_candle = candles_up_to_t[-1]

            # Collision check: is symbol already in an active trade?
            blocking_trade = self.collision_manager.is_symbol_occupied(
                symbol=self.symbol,
                entry_time=occ_ts,
                active_trades=executed_trades,
            )

            entry_price, price_type, spread = self.rule_engine.resolve_entry_price(
                candle=entry_candle,
                direction=occ_direction,
            )

            if blocking_trade is not None:
                # Flag as SKIPPED_ACTIVE_TRADE without discarding
                skipped_trade = BacktestTradeRecord(
                    setup_id=occ_setup_id,
                    setup_code=occ_code,
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    direction=occ_direction,
                    entry_time=occ_ts,
                    entry_price=entry_price,
                    stop_loss=Decimal("0.0"),
                    take_profit=Decimal("0.0"),
                    exit_time=occ_ts,
                    exit_price=entry_price,
                    result=TradeResult.SKIPPED_ACTIVE_TRADE,
                    status=TradeStatus.SKIPPED,
                    split_type=occ_split,
                    commission=Decimal("0.0"),
                    slippage=self.config.slippage_pips,
                    spread=spread,
                    ambiguity_reason=f"Collision: active trade {blocking_trade.setup_id} open until {blocking_trade.exit_time}",
                    entry_price_type=price_type,
                )
                executed_trades.append(skipped_trade)
                continue

            # Derive Stop Loss
            evidence_snapshot = get_val(occ, "evidence_snapshot")
            sl, sl_error = self.rule_engine.derive_structural_stop_loss(
                setup_code=occ_code,
                direction=occ_direction,
                entry_price=entry_price,
                candles_up_to_t=candles_up_to_t,
                evidence_snapshot=evidence_snapshot if isinstance(evidence_snapshot, dict) else None,
            )

            if sl is None:
                invalid_trade = BacktestTradeRecord(
                    setup_id=occ_setup_id,
                    setup_code=occ_code,
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    direction=occ_direction,
                    entry_time=occ_ts,
                    entry_price=entry_price,
                    stop_loss=Decimal("0.0"),
                    take_profit=Decimal("0.0"),
                    exit_time=occ_ts,
                    exit_price=entry_price,
                    result=TradeResult.INVALID,
                    status=TradeStatus.INVALID,
                    split_type=occ_split,
                    commission=Decimal("0.0"),
                    slippage=self.config.slippage_pips,
                    spread=spread,
                    ambiguity_reason=f"Invalid SL: {sl_error}",
                    entry_price_type=price_type,
                )
                executed_trades.append(invalid_trade)
                continue

            # Calculate Take Profit
            tp = self.rule_engine.calculate_take_profit(
                direction=occ_direction,
                entry_price=entry_price,
                stop_loss=sl,
            )

            # Create preliminary trade record
            trade = BacktestTradeRecord(
                setup_id=occ_setup_id,
                setup_code=occ_code,
                symbol=self.symbol,
                timeframe=self.timeframe,
                direction=occ_direction,
                entry_time=occ_ts,
                entry_price=entry_price,
                stop_loss=sl,
                take_profit=tp,
                result=TradeResult.TIMEOUT,  # Default, overwritten during simulation
                status=TradeStatus.OPEN,
                split_type=occ_split,
                commission=self.config.commission_per_trade,
                slippage=self.config.slippage_pips,
                spread=spread,
                entry_price_type=price_type,
            )

            # Extract subsequent candles > T
            subsequent_candles = [c for c in sorted_candles if ensure_utc(get_val(c, "timestamp")) > occ_ts]

            # Simulate price path
            simulated_trade = self.simulator.simulate_trade(
                trade=trade,
                subsequent_candles=subsequent_candles,
            )
            executed_trades.append(simulated_trade)

        # 4. Metrics & Report Generation
        overall_metrics = BacktestMetricsCalculator.calculate_metrics(executed_trades)
        setup_metrics = BacktestMetricsCalculator.calculate_by_setup(executed_trades)
        split_metrics = BacktestMetricsCalculator.calculate_by_split(executed_trades)

        report_text = BacktestReportGenerator.generate_report_text(
            symbol=self.symbol,
            config=self.config,
            overall_metrics=overall_metrics,
            setup_metrics=setup_metrics,
            split_metrics=split_metrics,
        )

        run_record = BacktestRunRecord(
            run_id=active_run_id,
            research_run_id=research_run_id or 0,
            backtest_version=backtest_version,
            config_hash=config_hash,
            completed_at=datetime.now(timezone.utc),
            status="SUCCESS",
            trade_count=overall_metrics.sample_size,
            wins=overall_metrics.wins,
            losses=overall_metrics.losses,
            timeouts=overall_metrics.timeouts,
            ambiguous=overall_metrics.ambiguous,
            skipped=overall_metrics.skipped,
            total_r=overall_metrics.total_r,
            metrics={
                "overall": overall_metrics.model_dump(mode="json"),
                "by_setup": {k: v.model_dump(mode="json") for k, v in setup_metrics.items()},
                "by_split": split_metrics.model_dump(mode="json"),
            },
        )

        return BacktestRunResult(
            run_id=active_run_id,
            run_record=run_record,
            trades=executed_trades,
            overall_metrics=overall_metrics,
            setup_metrics=setup_metrics,
            split_metrics=split_metrics,
            report_text=report_text,
        )

    def persist_results(
        self,
        session: Session,
        result: BacktestRunResult,
        research_run_db_id: int,
    ) -> int:
        """
        Persists backtest run record and simulated trades idempotently to PostgreSQL.
        """
        # Insert or retrieve backtest run
        stmt = insert(BacktestRunModel).values(
            run_id=result.run_id,
            research_run_id=research_run_db_id,
            backtest_version=result.run_record.backtest_version,
            config_hash=result.run_record.config_hash,
            started_at=result.run_record.started_at,
            completed_at=result.run_record.completed_at,
            status=result.run_record.status,
            trade_count=result.run_record.trade_count,
            wins=result.run_record.wins,
            losses=result.run_record.losses,
            timeouts=result.run_record.timeouts,
            ambiguous=result.run_record.ambiguous,
            skipped=result.run_record.skipped,
            total_r=result.run_record.total_r,
            metrics=result.run_record.metrics,
        ).on_conflict_do_nothing(index_elements=["run_id"]).returning(BacktestRunModel.id)

        res = session.execute(stmt)
        inserted_id = res.scalar_one_or_none()

        if inserted_id is None:
            existing = session.query(BacktestRunModel).filter_by(run_id=result.run_id).first()
            if not existing:
                session.rollback()
                raise RuntimeError(f"Could not persist or locate BacktestRun with run_id {result.run_id}")
            bt_db_id = existing.id
        else:
            bt_db_id = inserted_id

        # Insert trades
        persisted_trades = 0
        for t in result.trades:
            trade_stmt = insert(BacktestTradeModel).values(
                backtest_run_id=bt_db_id,
                setup_id=t.setup_id,
                setup_code=t.setup_code,
                symbol=t.symbol,
                timeframe=t.timeframe,
                direction=t.direction,
                entry_time=t.entry_time,
                entry_price=t.entry_price,
                stop_loss=t.stop_loss,
                take_profit=t.take_profit,
                exit_time=t.exit_time,
                exit_price=t.exit_price,
                result=t.result.value if hasattr(t.result, "value") else str(t.result),
                r_multiple=t.r_multiple,
                mae_r=t.mae_r,
                mfe_r=t.mfe_r,
                commission=t.commission,
                slippage=t.slippage,
                spread=t.spread,
                status=t.status.value if hasattr(t.status, "value") else str(t.status),
                split_type=t.split_type,
                ambiguity_reason=t.ambiguity_reason,
            )
            session.execute(trade_stmt)
            persisted_trades += 1

        session.commit()
        return persisted_trades
