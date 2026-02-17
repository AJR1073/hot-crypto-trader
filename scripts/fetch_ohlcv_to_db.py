#!/usr/bin/env python3
"""
Fetch OHLCV data from exchange and store in SQLite database.

Uses INSERT ... ON CONFLICT DO UPDATE for upsert semantics.

Usage:
    python scripts/fetch_ohlcv_to_db.py --symbol BTC/USDT --timeframe 4h --limit 500
    python scripts/fetch_ohlcv_to_db.py --symbol ETH/USDT --timeframe 1d --limit 1000

Arguments:
    --exchange: Exchange name (default: kraken)
    --symbol: Trading pair (required)
    --timeframe: Candle timeframe (default: 4h)
    --limit: Number of candles to fetch (default: 500)
    --db-url: Database URL override
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.exchange_client import ExchangeClient
from core.utils import setup_logging
from db import init_db, get_engine, OHLCV


def fetch_and_store_ohlcv(
    exchange_name: str,
    symbol: str,
    timeframe: str,
    limit: int,
    db_url: str = None,
) -> int:
    """
    Fetch OHLCV data from exchange and store in database.
    
    Args:
        exchange_name: Name of the exchange
        symbol: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "4h")
        limit: Number of candles to fetch
        db_url: Optional database URL override
        
    Returns:
        Number of rows upserted
    """
    logger = logging.getLogger(__name__)
    
    # Initialize database
    logger.info("Initializing database...")
    engine = init_db(db_url)
    
    # Fetch OHLCV data from exchange
    logger.info(f"Connecting to {exchange_name}...")
    client = ExchangeClient(exchange_name=exchange_name)
    
    logger.info(f"Fetching {limit} {timeframe} candles for {symbol}...")
    df = client.fetch_ohlcv(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
    )
    
    if df.empty:
        logger.warning("No data fetched from exchange")
        return 0
    
    logger.info(f"Fetched {len(df)} candles from {df.index.min()} to {df.index.max()}")
    
    # Prepare data for upsert
    records = []
    for ts, row in df.iterrows():
        # Convert pandas Timestamp to Python datetime
        if hasattr(ts, 'to_pydatetime'):
            ts_dt = ts.to_pydatetime().replace(tzinfo=None)  # Store as naive UTC
        else:
            ts_dt = ts
            
        records.append({
            "exchange": exchange_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "ts": ts_dt,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })
    
    # Execute upsert
    logger.info(f"Upserting {len(records)} records into database...")
    
    with engine.connect() as conn:
        stmt = OHLCV.upsert_stmt(records)
        result = conn.execute(stmt)
        conn.commit()
    
    logger.info(f"Successfully upserted {len(records)} candles")
    return len(records)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch OHLCV data from exchange and store in SQLite database"
    )
    parser.add_argument("--exchange", default="kraken", help="Exchange name")
    parser.add_argument("--symbol", required=True, help="Trading pair (e.g., BTC/USDT)")
    parser.add_argument("--timeframe", default="4h", help="Candle timeframe")
    parser.add_argument("--limit", type=int, default=500, help="Number of candles to fetch")
    parser.add_argument("--db-url", help="Database URL override")
    
    args = parser.parse_args()
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info(f"HOT-Crypto OHLCV Fetcher")
    logger.info("=" * 60)
    logger.info(f"Exchange: {args.exchange}")
    logger.info(f"Symbol: {args.symbol}")
    logger.info(f"Timeframe: {args.timeframe}")
    logger.info(f"Limit: {args.limit}")
    logger.info("=" * 60)
    
    try:
        count = fetch_and_store_ohlcv(
            exchange_name=args.exchange,
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=args.limit,
            db_url=args.db_url,
        )
        
        logger.info("=" * 60)
        logger.info(f"SUCCESS: Stored {count} candles in database")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
