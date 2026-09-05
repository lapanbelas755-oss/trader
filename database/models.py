"""SQLAlchemy ORM models for Trader Machine V1 raw market data foundation."""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import BigInteger, Numeric, String, DateTime, func, CheckConstraint, UniqueConstraint
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
