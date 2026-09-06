import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Ensure core is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.worker.adapter import RealMT5Adapter, MockMT5Adapter, MT5ConnectionState
from core.research.engine import HistoricalResearchEngine
from core.data_source.contract import DatasetProvenance
from core.data_source.hashing import CanonicalHasher
from core.research.contract import DataProvenance

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    # 1. Setup DB
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not found in environment.")
        sys.exit(1)
        
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    
    symbol = "EURUSD"
    timeframe = "M5"
    count = 5000  # Default count to fetch, representing approx 1 week of M5 data
    
    # 2. Setup MT5
    logger.info("Initializing MT5 Connection...")
    if os.name == 'nt':
        mt5_path = os.getenv("MT5_TERMINAL_PATH")
        mt5_server = os.getenv("MT5_SERVER")
        mt5_login = os.getenv("MT5_LOGIN")
        mt5_password = os.getenv("MT5_PASSWORD")
        
        login_int = int(mt5_login) if mt5_login else None
        adapter = RealMT5Adapter(path=mt5_path, server=mt5_server, login=login_int, password=mt5_password)
    else:
        logger.info("Non-Windows OS detected. Using MockMT5Adapter.")
        adapter = MockMT5Adapter()
        
    if not adapter.initialize():
        logger.error(f"Failed to initialize MT5 adapter. State: {adapter.get_connection_state()}")
        sys.exit(1)
        
    try:
        # 3. Fetch Historical Rates
        logger.info(f"Fetching {count} historical bars for {symbol} {timeframe}...")
        rates = adapter.get_historical_rates(symbol, timeframe, count)
        
        if not rates:
            logger.error("No rates fetched from MT5. Aborting.")
            sys.exit(1)
            
        logger.info(f"Successfully fetched {len(rates)} bars. First bar: {rates[0]['timestamp'].isoformat()}, Last bar: {rates[-1]['timestamp'].isoformat()}")
        
        # 4. Construct Provenance
        # Compute canonical hash
        from core.research.hashing import hash_candles
        content_hash = hash_candles(rates)
        
        # Core data_source provenance expects DataProvenance type for ResearchEngine
        provenance = DataProvenance(
            source="MT5_TERMINAL",
            source_type="API",
            source_file="IN_MEMORY",
            source_format="MT5_RATES",
            symbol=symbol,
            timeframe=timeframe,
            first_timestamp=rates[0]['timestamp'],
            last_timestamp=rates[-1]['timestamp'],
            row_count=len(rates),
            declared_timezone="UTC",
            content_hash=content_hash,
            metadata={"fetch_count": count},
            created_at=datetime.now(timezone.utc)
        )
        
        # 5. Run Research Pipeline
        logger.info("Starting Historical Research Pipeline...")
        research_engine = HistoricalResearchEngine(symbol=symbol, timeframe=timeframe)
        result = research_engine.run_pipeline(
            candles=rates,
            provenance=provenance,
            dataset_name=f"MT5_{symbol}_{timeframe}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            dataset_version="1.0.0",
            run_version="1.0.0"
        )
        
        # 6. Persist Results
        logger.info(f"Pipeline finished with status: {result.status.value}")
        logger.info(f"Validation Errors: {len(result.validation_report.errors)}")
        logger.info(f"Detected Setups: {len(result.occurrences)}")
        
        with SessionLocal() as session:
            logger.info("Persisting results to PostgreSQL...")
            dataset_id, run_id, occ_inserted = research_engine.persist_results(session, result)
            logger.info(f"Persisted successfully! Dataset ID: {dataset_id}, Run ID: {run_id}, Occurrences Inserted: {occ_inserted}")
            
        # 7. Print Report
        print("\n--- RESEARCH REPORT ---")
        print(result.report_text)
        print("-----------------------\n")
        
    finally:
        logger.info("Shutting down MT5 adapter.")
        adapter.shutdown()

if __name__ == "__main__":
    main()
