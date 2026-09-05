"""SQLAlchemy ORM models for Trader Machine V1 raw market data foundation."""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import BigInteger, Numeric, String, DateTime, Boolean, func, CheckConstraint, UniqueConstraint, Text
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


