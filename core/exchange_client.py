"""
ExchangeClient: ccxt wrapper for Binance.US

Provides a thin abstraction over ccxt for exchange operations:
- Fetch OHLCV data
- Get account balances
- Create and manage orders
"""

import logging
import os
from datetime import datetime
from typing import Optional

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)


class ExchangeClient:
    """
    Thin wrapper around ccxt for Binance.US exchange access.
    
    Handles authentication, rate limiting, and provides pandas-friendly
    methods for market data and order management.
    """

    def __init__(
        self,
        exchange_name: str = "binanceus",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        sandbox: bool = False,
    ):
        """
        Initialize the exchange client.

        Args:
            exchange_name: Name of the exchange (default: binanceus)
            api_key: API key (defaults to EXCHANGE_API_KEY env var)
            api_secret: API secret (defaults to EXCHANGE_API_SECRET env var)
            sandbox: Enable sandbox/testnet mode if supported
        """
        self.exchange_name = exchange_name
        self.api_key = api_key or os.getenv("EXCHANGE_API_KEY")
        self.api_secret = api_secret or os.getenv("EXCHANGE_API_SECRET")
        self.sandbox = sandbox

        # Initialize the ccxt exchange
        exchange_class = getattr(ccxt, exchange_name)
        self.exchange = exchange_class({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
        })

        # Enable sandbox mode if requested and supported
        if sandbox:
            try:
                self.exchange.set_sandbox_mode(True)
                logger.info(f"Sandbox mode enabled for {exchange_name}")
            except Exception as e:
                logger.warning(f"Sandbox not supported for {exchange_name}: {e}")

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "4h",
        limit: int = 500,
        since: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candle data from the exchange.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h", "4h", "1d")
            limit: Number of candles to fetch
            since: Timestamp in milliseconds to start from

        Returns:
            DataFrame indexed by timestamp (UTC) with columns:
            open, high, low, close, volume
        """
        logger.info(f"Fetching {limit} {timeframe} candles for {symbol}")
        
        # Fetch raw OHLCV data from exchange
        # Format: [[timestamp, open, high, low, close, volume], ...]
        ohlcv = self.exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            since=since,
        )
        
        if not ohlcv:
            logger.warning(f"No data returned for {symbol} {timeframe}")
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        
        # Convert to DataFrame
        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        
        # Convert timestamp (ms) to datetime index
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        
        logger.info(f"Fetched {len(df)} candles from {df.index.min()} to {df.index.max()}")
        
        return df

    def get_balance(self, asset: str = "USDT") -> float:
        """
        Get the balance for a specific asset.

        Args:
            asset: Asset symbol (e.g., "USDT", "BTC")

        Returns:
            Available balance as float
        """
        balance = self.exchange.fetch_balance()
        return balance.get(asset, {}).get("free", 0.0)

    def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """
        Create an order on the exchange.

        Args:
            symbol: Trading pair
            side: "buy" or "sell"
            order_type: "market" or "limit"
            amount: Order size
            price: Price for limit orders
            params: Additional exchange-specific parameters

        Returns:
            Order response dict from exchange
        """
        # TODO: Implement in Phase 6
        raise NotImplementedError("Will be implemented in Phase 6")

    def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Cancel an open order."""
        # TODO: Implement in Phase 6
        raise NotImplementedError("Will be implemented in Phase 6")

    def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """Get all open orders, optionally filtered by symbol."""
        # TODO: Implement in Phase 6
        raise NotImplementedError("Will be implemented in Phase 6")

    @staticmethod
    def now() -> datetime:
        """Get current UTC time."""
        return datetime.utcnow()
