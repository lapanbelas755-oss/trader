"""SQLAlchemy ORM models for Trader Machine V1 raw market data foundation."""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import BigInteger, Numeric, String, DateTime, Boolean, func, CheckConstraint, UniqueConstraint, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class MarketTick(Base):
    """Raw tick market data without modification or derived indicators."""
    __tablename__ = "market_ticks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    bid: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    ask: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    last: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    volume: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=Decimal("0"))
    tick_direction: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="MT5_EXNESS")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<MarketTick(symbol={self.symbol!r}, ts={self.timestamp.isoformat()!r}, bid={self.bid}, ask={self.ask})>"


class MarketCandle(Base):
    """Raw or aggregated market candles across standard timeframes (M1, M5, M15, H1)."""
    __tablename__ = "market_candles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    tick_volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    real_volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    spread: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("timeframe IN ('M1', 'M5', 'M15', 'H1')", name="chk_valid_timeframe"),
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_market_candles_symbol_tf_ts"),
    )

    def __repr__(self) -> str:
        return f"<MarketCandle(symbol={self.symbol!r}, tf={self.timeframe!r}, ts={self.timestamp.isoformat()!r}, close={self.close})>"


class MarketFeature(Base):
    """Derived market measurements, volatility baselines, and anomalies."""
    __tablename__ = "market_features"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Geometry & ATR
    atr: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    range: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    body: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    price_change: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    movement_efficiency: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)

    # Effort vs Result
    effort: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    result: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    effort_result_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 4), nullable=True)

    # Volatility & Baselines
    volatility: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    volatility_zscore: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    activity_zscore: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    price_response_zscore: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)

    # Anomaly Flags
    is_anomaly_candidate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_strong_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Market Speed
    movement_speed: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 8), nullable=True)
    range_per_second: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 8), nullable=True)
    price_change_per_second: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 8), nullable=True)

    # Lifecycle & Status
    feature_status: Mapped[str] = mapped_column(String(32), default="WARMUP", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("timeframe IN ('M1', 'M5', 'M15', 'H1')", name="chk_feature_timeframe"),
        CheckConstraint("feature_status IN ('VALID', 'WARMUP', 'INSUFFICIENT_DATA', 'INVALID')", name="chk_feature_status"),
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_market_features_symbol_tf_ts"),
    )

    def __repr__(self) -> str:
        return f"<MarketFeature(symbol={self.symbol!r}, tf={self.timeframe!r}, ts={self.timestamp.isoformat()!r}, status={self.feature_status!r})>"


class MarketStructure(Base):
    """Market structure events: Swings, BOS, and CHoCH."""
    __tablename__ = "market_structure"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    structure_type: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    swing_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reference_swing_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    displacement: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    strength: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("timeframe IN ('M5', 'M15', 'H1')", name="chk_structure_timeframe"),
        CheckConstraint("direction IN ('BULLISH', 'BEARISH', 'MIXED', 'TRANSITION', 'UNDEFINED')", name="chk_structure_direction"),
        UniqueConstraint("symbol", "timeframe", "timestamp", "structure_type", name="uq_market_structure_event"),
    )

    def __repr__(self) -> str:
        return f"<MarketStructure(symbol={self.symbol!r}, tf={self.timeframe!r}, type={self.structure_type!r}, price={self.price})>"


class LiquidityLevel(Base):
    """Liquidity levels and lifecycle tracking."""
    __tablename__ = "liquidity_levels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    level_type: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    tolerance: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0.000100"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="UNTOUCHED", nullable=False)
    session: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    source_swing_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    start_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    strength: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    sweep_depth: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    swept_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('UNTOUCHED', 'APPROACHED', 'TOUCHED', 'SWEPT', 'REJECTED', 'ACCEPTED', 'INVALIDATED')", name="chk_liq_status"),
        UniqueConstraint("symbol", "timeframe", "level_type", "price", "start_timestamp", name="uq_liquidity_level"),
    )

    def __repr__(self) -> str:
        return f"<LiquidityLevel(symbol={self.symbol!r}, type={self.level_type!r}, price={self.price}, status={self.status!r})>"


class Setup(Base):
    """Deterministic setup candidates generated by Setup Detector Engine V1."""
    __tablename__ = "setups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    setup_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    setup_code: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, default="M5")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    regime: Mapped[str] = mapped_column(String(32), default="UNKNOWN", nullable=False)
    liquidity_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    structure_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    anomaly_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('OBSERVE', 'WATCH', 'ARMED', 'FIRE', 'EXPIRED', 'REJECTED')", name="chk_setup_status"),
        CheckConstraint("setup_code IN ('S01', 'S02', 'S03', 'S04', 'S05')", name="chk_setup_code"),
        CheckConstraint("direction IN ('BULLISH', 'BEARISH', 'UNDEFINED')", name="chk_setup_direction"),
        UniqueConstraint("symbol", "timeframe", "setup_code", "timestamp", "status", "direction", name="uq_setup_event"),
    )

    def __repr__(self) -> str:
        return f"<Setup(id={self.setup_id!r}, code={self.setup_code!r}, sym={self.symbol!r}, status={self.status!r}, dir={self.direction!r})>"


class SetupEvidence(Base):
    """Auditable evidence entries supporting setup decisions."""
    __tablename__ = "setup_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    setup_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_key: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_value: Mapped[str] = mapped_column(String(128), nullable=False)
    numeric_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("setup_id", "evidence_key", name="uq_setup_evidence"),
    )

    def __repr__(self) -> str:
        return f"<SetupEvidence(setup_id={self.setup_id!r}, key={self.evidence_key!r}, val={self.evidence_value!r})>"


class ResearchDataset(Base):
    """Metadata and content hash tracking for reproducible historical research datasets."""
    __tablename__ = "research_datasets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_name: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="BUILDING", nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('BUILDING', 'VALIDATED', 'READY', 'REJECTED')", name="chk_dataset_status"),
        UniqueConstraint("dataset_name", "dataset_version", "content_hash", name="uq_research_dataset"),
    )

    def __repr__(self) -> str:
        return f"<ResearchDataset(name={self.dataset_name!r}, v={self.dataset_version!r}, hash={self.content_hash[:8]!r}, status={self.status!r})>"


class ResearchRun(Base):
    """Execution run record linking dataset, configuration hash, and outputs."""
    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    dataset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("research_datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    run_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING", nullable=False, index=True)
    input_row_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_row_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'FAILED')", name="chk_run_status"),
        UniqueConstraint("run_id", name="uq_research_run"),
    )

    def __repr__(self) -> str:
        return f"<ResearchRun(run_id={self.run_id!r}, dataset_id={self.dataset_id}, status={self.status!r})>"


class ResearchSetupOccurrence(Base):
    """Recorded setup occurrences observed in historical research datasets."""
    __tablename__ = "research_setup_occurrences"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    research_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    setup_id: Mapped[str] = mapped_column(String(64), nullable=False)
    setup_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    regime: Mapped[str] = mapped_column(String(32), default="UNKNOWN", nullable=False)
    liquidity_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    structure_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    split_type: Mapped[str] = mapped_column(String(16), default="IN_SAMPLE", nullable=False, index=True)
    evidence_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("split_type IN ('IN_SAMPLE', 'VALIDATION', 'OUT_OF_SAMPLE')", name="chk_occ_split"),
        CheckConstraint("status IN ('OBSERVE', 'WATCH', 'ARMED', 'FIRE', 'EXPIRED', 'REJECTED')", name="chk_occ_status"),
        CheckConstraint("setup_code IN ('S01', 'S02', 'S03', 'S04', 'S05')", name="chk_occ_code"),
        CheckConstraint("direction IN ('BULLISH', 'BEARISH', 'UNDEFINED')", name="chk_occ_direction"),
        UniqueConstraint("research_run_id", "setup_code", "timestamp", "status", "direction", name="uq_research_occurrence"),
    )

    def __repr__(self) -> str:
        return f"<ResearchSetupOccurrence(run_id={self.research_run_id}, code={self.setup_code!r}, ts={self.timestamp.isoformat()!r}, split={self.split_type!r})>"


class BacktestRun(Base):
    """Execution run record for backtest evaluation."""
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    research_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    backtest_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING", nullable=False, index=True)
    trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timeouts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ambiguous: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_r: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'FAILED')", name="chk_backtest_run_status"),
        UniqueConstraint("run_id", name="uq_backtest_run"),
    )

    def __repr__(self) -> str:
        return f"<BacktestRun(run_id={self.run_id!r}, research_run_id={self.research_run_id}, status={self.status!r})>"


class BacktestTrade(Base):
    """Simulated trade record produced by Backtest Engine V1."""
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    setup_id: Mapped[str] = mapped_column(String(64), nullable=False)
    setup_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(12, 5), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(12, 5), nullable=False)
    take_profit: Mapped[Decimal] = mapped_column(Numeric(12, 5), nullable=False)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 5), nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    r_multiple: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    mae_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    mfe_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    commission: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    slippage: Mapped[Decimal] = mapped_column(Numeric(12, 5), default=Decimal("0.00000"), nullable=False)
    spread: Mapped[Decimal] = mapped_column(Numeric(12, 5), default=Decimal("0.00000"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="CLOSED", nullable=False)
    split_type: Mapped[str] = mapped_column(String(16), default="IN_SAMPLE", nullable=False, index=True)
    ambiguity_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("result IN ('TP', 'SL', 'TIMEOUT', 'INVALID', 'DATA_ERROR', 'AMBIGUOUS', 'SKIPPED_ACTIVE_TRADE')", name="chk_trade_result"),
        CheckConstraint("status IN ('OPEN', 'CLOSED', 'SKIPPED', 'INVALID')", name="chk_trade_status"),
        CheckConstraint("direction IN ('BULLISH', 'BEARISH', 'UNDEFINED')", name="chk_trade_direction"),
        CheckConstraint("split_type IN ('IN_SAMPLE', 'VALIDATION', 'OUT_OF_SAMPLE')", name="chk_trade_split"),
        CheckConstraint("setup_code IN ('S01', 'S02', 'S03', 'S04', 'S05')", name="chk_trade_setup_code"),
    )

    def __repr__(self) -> str:
        return f"<BacktestTrade(run_id={self.backtest_run_id}, setup={self.setup_code!r}, entry={self.entry_time.isoformat()!r}, res={self.result!r}, R={self.r_multiple})>"


class StatisticalRun(Base):
    """Run metadata for statistical edge analysis."""
    __tablename__ = "statistical_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    backtest_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_split: Mapped[str] = mapped_column(String(32), default="ALL", nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING", nullable=False)
    overall_classification: Mapped[str] = mapped_column(String(32), default="INSUFFICIENT_DATA", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'FAILED')", name="chk_stat_run_status"),
        UniqueConstraint("run_id", name="uq_statistical_run"),
    )

    def __repr__(self) -> str:
        return f"<StatisticalRun(run_id={self.run_id!r}, status={self.status!r}, edge={self.overall_classification!r})>"


class EdgeMetric(Base):
    """Descriptive and inferential statistical metrics per setup and split."""
    __tablename__ = "edge_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    statistical_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("statistical_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    setup_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    split_type: Mapped[str] = mapped_column(String(16), default="ALL", nullable=False, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timeouts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ambiguous: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    win_rate_ci_lower: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    win_rate_ci_upper: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    average_win_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    average_loss_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    expectancy_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    profit_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    total_r: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    max_drawdown_r: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    max_consecutive_losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mean_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    median_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    std_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    classification: Mapped[str] = mapped_column(String(32), default="INSUFFICIENT_DATA", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("setup_code IN ('S01', 'S02', 'S03', 'S04', 'S05', 'OVERALL')", name="chk_edge_setup_code"),
        CheckConstraint("split_type IN ('ALL', 'IN_SAMPLE', 'VALIDATION', 'OUT_OF_SAMPLE')", name="chk_edge_split"),
    )

    def __repr__(self) -> str:
        return f"<EdgeMetric(setup={self.setup_code!r}, split={self.split_type!r}, N={self.sample_size}, E={self.expectancy_r})>"


class EdgeSegment(Base):
    """Segmented performance breakdown across market conditions."""
    __tablename__ = "edge_segments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    statistical_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("statistical_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    setup_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    segment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    segment_value: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    expectancy_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    profit_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    total_r: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    max_drawdown_r: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0.0000"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("segment_type IN ('REGIME', 'SESSION', 'DIRECTION', 'LIQUIDITY_TYPE', 'SPREAD_BUCKET', 'DAY_OF_WEEK', 'MTF_ALIGNMENT', 'VOLATILITY_STATE')", name="chk_segment_type"),
    )

    def __repr__(self) -> str:
        return f"<EdgeSegment(type={self.segment_type!r}, val={self.segment_value!r}, N={self.sample_size}, E={self.expectancy_r})>"


class BootstrapResult(Base):
    """Bootstrap distribution results for statistical validation."""
    __tablename__ = "bootstrap_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    statistical_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("statistical_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    setup_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    iterations: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    lower_bound: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    median: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    upper_bound: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    positive_fraction: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<BootstrapResult(setup={self.setup_code!r}, metric={self.metric!r}, lower={self.lower_bound}, upper={self.upper_bound}, pos_frac={self.positive_fraction})>"




