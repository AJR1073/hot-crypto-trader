"""
CCXTDataSource: DataSource implementation using ccxt exchange client.

Wraps ExchangeClient to provide live OHLCV data from the exchange.
"""

import logging

import pandas as pd

from .data_source import DataSource
from .exchange_client import ExchangeClient

logger = logging.getLogger(__name__)


class CCXTDataSource(DataSource):
    """
    DataSource implementation that fetches OHLCV from exchange via ccxt.
    
    Wraps an ExchangeClient instance to fetch live market data.
    """

    def __init__(self, exchange_client: ExchangeClient):
        """
        Initialize with an ExchangeClient instance.

        Args:
            exchange_client: Configured ExchangeClient for API access
        """
        self.client = exchange_client
        logger.info(f"CCXTDataSource initialized for {exchange_client.exchange_name}")

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data from the exchange.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h", "4h", "1d")
            limit: Maximum number of candles to return

        Returns:
            DataFrame indexed by timestamp with OHLCV columns
        """
        logger.info(f"Fetching {limit} {timeframe} candles for {symbol} via CCXT")
        
        df = self.client.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )
        
        if df.empty:
            raise ValueError(f"No data returned from exchange for {symbol} {timeframe}")
        
        return df
