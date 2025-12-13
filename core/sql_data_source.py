"""
SQLDataSource: DataSource implementation using local SQLite database.

Reads cached OHLCV data from SQLite for backtesting without 
requiring exchange API calls.
"""

import logging
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from .data_source import DataSource
from db import get_db_url, OHLCV

logger = logging.getLogger(__name__)


class SQLDataSource(DataSource):
    """
    DataSource implementation that reads OHLCV from local SQL database.
    
    Uses SQLAlchemy to query the ohlcv table and return data as a
    pandas DataFrame indexed by timestamp.
    """

    def __init__(self, db_url: Optional[str] = None, exchange: str = "binanceus"):
        """
        Initialize with database connection.

        Args:
            db_url: SQLAlchemy database URL (defaults to HOT_CRYPTO_DB_URL env var)
            exchange: Exchange name to filter data by
        """
        self.db_url = get_db_url(db_url)
        self.exchange = exchange
        self.engine = create_engine(self.db_url, echo=False)
        logger.info(f"SQLDataSource initialized: {self.db_url}")

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data from the database.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h", "4h", "1d")
            limit: Maximum number of candles to return

        Returns:
            DataFrame indexed by timestamp with OHLCV columns
            
        Raises:
            ValueError: If no data found for the given parameters
        """
        logger.info(f"Fetching {limit} {timeframe} candles for {symbol} from SQL")
        
        # Build query
        stmt = (
            select(OHLCV)
            .where(OHLCV.exchange == self.exchange)
            .where(OHLCV.symbol == symbol)
            .where(OHLCV.timeframe == timeframe)
            .order_by(OHLCV.ts.desc())
            .limit(limit)
        )
        
        with Session(self.engine) as session:
            results = session.execute(stmt).scalars().all()
        
        if not results:
            raise ValueError(
                f"No data found for {symbol} {timeframe} on {self.exchange}. "
                f"Run fetch_ohlcv_to_db.py first."
            )
        
        # Convert to DataFrame
        data = [
            {
                "timestamp": row.ts,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in results
        ]
        
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)  # Oldest first
        
        logger.info(f"Loaded {len(df)} candles from {df.index.min()} to {df.index.max()}")
        
        return df
