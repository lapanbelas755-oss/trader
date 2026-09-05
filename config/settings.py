"""Database configuration module for Trader Machine V1."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

def get_database_url() -> str:
    """Return database URL from environment or constructed from components."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    
    user = os.getenv("DB_USER", "trader_machine")
    password = os.getenv("DB_PASSWORD", "")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5433")
    dbname = os.getenv("DB_NAME", "trader_machine")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"
