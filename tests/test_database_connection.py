"""Tests for database connectivity, schema integrity, and precision."""
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import text, inspect
from sqlalchemy.exc import IntegrityError
from database.connection import get_engine, get_session_factory, check_connection
from database.models import MarketTick, MarketCandle
from database.migrate import get_applied_migrations

def test_database_connection():
    """Verify direct SELECT 1 database connectivity."""
    assert check_connection() is True

def test_raw_psycopg_connection():
    """Verify underlying psycopg connectivity via SQLAlchemy raw connection."""
    engine = get_engine()
    with engine.raw_connection() as raw_conn:
        with raw_conn.cursor() as cursor:
            cursor.execute("SELECT 1;")
            result = cursor.fetchone()
            assert result is not None
            assert result[0] == 1

def test_schema_tables_exist():
    """Verify that required raw market tables exist in PostgreSQL."""
    engine = get_engine()
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "market_ticks" in tables
    assert "market_candles" in tables
    assert "schema_migrations" in tables

def test_migration_version_recorded():
    """Verify that migration 001 is recorded in schema_migrations."""
    applied = get_applied_migrations()
    assert "001" in applied

def test_market_tick_precision():
    """Verify exact financial decimal precision without floating point distortion."""
    session_factory = get_session_factory()
    test_ts = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    bid_val = Decimal("1.085235")
    ask_val = Decimal("1.085355")

    with session_factory() as session:
        tick = MarketTick(
            timestamp=test_ts,
            symbol="EURUSD",
            bid=bid_val,
            ask=ask_val,
            volume=Decimal("1.5000"),
            tick_direction="UP",
            source="MT5_EXNESS",
        )
        session.add(tick)
        session.commit()

        # Query back and check precision
        retrieved = session.query(MarketTick).filter_by(symbol="EURUSD", timestamp=test_ts).first()
        assert retrieved is not None
        assert retrieved.bid == bid_val
        assert retrieved.ask == ask_val
        assert retrieved.volume == Decimal("1.5000")

        # Cleanup test row
        session.delete(retrieved)
        session.commit()

def test_market_candle_valid_and_invalid_timeframe():
    """Verify timeframe validation check constraint on market_candles."""
    session_factory = get_session_factory()
    test_ts = datetime(2026, 9, 5, 12, 5, 0, tzinfo=timezone.utc)

    # Valid candle insertion
    with session_factory() as session:
        candle = MarketCandle(
            symbol="EURUSD",
            timeframe="M5",
            timestamp=test_ts,
            open=Decimal("1.085000"),
            high=Decimal("1.085500"),
            low=Decimal("1.084900"),
            close=Decimal("1.085400"),
            tick_volume=120,
            real_volume=0,
            spread=Decimal("1.2"),
        )
        session.add(candle)
        session.commit()

        queried = session.query(MarketCandle).filter_by(symbol="EURUSD", timeframe="M5", timestamp=test_ts).first()
        assert queried is not None
        assert queried.close == Decimal("1.085400")

        session.delete(queried)
        session.commit()

    # Invalid timeframe (e.g. 'TICK' or 'M3') must be rejected by check constraint
    with session_factory() as session:
        invalid_candle = MarketCandle(
            symbol="EURUSD",
            timeframe="TICK",
            timestamp=test_ts,
            open=Decimal("1.085000"),
            high=Decimal("1.085500"),
            low=Decimal("1.084900"),
            close=Decimal("1.085400"),
            tick_volume=1,
            real_volume=0,
            spread=Decimal("1.0"),
        )
        session.add(invalid_candle)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
