"""
DataSource: Abstract base class for OHLCV data sources.

Provides a common interface for fetching candle data from different sources:
- SQLDataSource: Reads from local SQLite database
- CCXTDataSource: Fetches from exchange via ccxt

All implementations return a pandas DataFrame with:
- Index: timestamp (UTC datetime)
- Columns: open, high, low, close, volume (all float)
"""

from abc import ABC, abstractmethod

import pandas as pd


class DataSource(ABC):
    """
    Abstract base class for OHLCV data sources.
    
    Implementations should fetch and return candle data in a consistent
    pandas DataFrame format.
    
    DataFrame format:
        - Index: DatetimeIndex (UTC timestamps)
        - Columns: open, high, low, close, volume (float64)
    
    Example:
        >>> ds = SQLDataSource("sqlite:///data/hot_crypto.db")
        >>> df = ds.get_ohlcv("BTC/USDT", "4h", limit=500)
        >>> df.head()
                                   open     high      low    close      volume
        timestamp                                                              
        2025-09-21 12:00:00+00:00  62000.0  62500.0  61800.0  62300.0  1234.5678
    """

    @abstractmethod
    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candle data.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h", "4h", "1d")
            limit: Maximum number of candles to return

        Returns:
            DataFrame indexed by timestamp (UTC) with columns:
            open, high, low, close, volume
            
        Raises:
            ValueError: If no data found for the given parameters
        """
        pass
