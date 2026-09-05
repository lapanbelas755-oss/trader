"""Database connection and engine management for Trader Machine V1."""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from config.settings import get_database_url

_engine: Engine | None = None

def get_engine() -> Engine:
    """Get or create singleton SQLAlchemy Engine."""
    global _engine
    if _engine is None:
        db_url = get_database_url()
        _engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            future=True,
        )
    return _engine

def get_session_factory() -> sessionmaker[Session]:
    """Return configured sessionmaker."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)

def check_connection() -> bool:
    """Check database connectivity with SELECT 1."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        return result == 1
