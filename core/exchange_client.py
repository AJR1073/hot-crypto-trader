"""
ExchangeClient: ccxt wrapper for Kraken

Provides a thin abstraction over ccxt for exchange operations:
- Fetch OHLCV data
- Get account balances
- Create and manage orders (with minimum order size checks)
- Rate-limited API calls
"""

import logging
import os
import time
from datetime import datetime
from typing import Optional

import ccxt
import pandas as pd

from core.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Default minimum order value for Kraken (most pairs require ~$10 minimum)
DEFAULT_MIN_NOTIONAL = 10.0


class ExchangeClient:
    """
    Wrapper around ccxt for Kraken exchange access.

    Handles authentication, rate limiting, minimum order checks, and
    provides pandas-friendly methods for market data and order management.
    """

    def __init__(
        self,
        exchange_name: str = "kraken",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        sandbox: bool = False,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """
        Initialize the exchange client.

        Args:
            exchange_name: Name of the exchange (default: kraken)
            api_key: API key (defaults to EXCHANGE_API_KEY env var)
            api_secret: API secret (defaults to EXCHANGE_API_SECRET env var)
            sandbox: Enable sandbox/testnet mode if supported
            rate_limiter: Optional RateLimiter instance for request throttling
        """
        self.exchange_name = exchange_name
        self.api_key = api_key or os.getenv("EXCHANGE_API_KEY")
        self.api_secret = api_secret or os.getenv("EXCHANGE_API_SECRET")
        self.sandbox = sandbox
        self.rate_limiter = rate_limiter or RateLimiter()

        # Cache for market minimums
        self._min_notional_cache: dict[str, float] = {}
        self._markets_loaded = False

        # Initialize the ccxt exchange
        exchange_class = getattr(ccxt, exchange_name)
        self.exchange = exchange_class({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot",
            },
        })

        # Enable sandbox mode if requested and supported
        if sandbox:
            try:
                self.exchange.set_sandbox_mode(True)
                logger.info(f"Sandbox mode enabled for {exchange_name}")
            except Exception as e:
                logger.warning(f"Sandbox not supported for {exchange_name}: {e}")

    def _ensure_markets(self) -> None:
        """Load markets if not already loaded (for min notional info)."""
        if not self._markets_loaded:
            try:
                self.rate_limiter.acquire(weight=5)
                self.exchange.load_markets()
                self._markets_loaded = True
            except Exception as e:
                logger.warning("Failed to load markets: %s", e)

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

        self.rate_limiter.acquire(weight=5)

        ohlcv = self.exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            since=since,
        )

        if not ohlcv:
            logger.warning(f"No data returned for {symbol} {timeframe}")
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

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
        self.rate_limiter.acquire(weight=1)
        balance = self.exchange.fetch_balance()
        return balance.get(asset, {}).get("free", 0.0)

    def get_min_notional(self, symbol: str) -> float:
        """
        Get the minimum notional (order value) for a symbol.

        Exchanges enforce minimum order value filters — orders below
        this value will be rejected.

        Args:
            symbol: Trading pair (e.g., "BTC/USD")

        Returns:
            Minimum order value in quote currency.
        """
        if symbol in self._min_notional_cache:
            return self._min_notional_cache[symbol]

        self._ensure_markets()

        try:
            market = self.exchange.market(symbol)
            # ccxt stores limits in market['limits']
            min_cost = market.get("limits", {}).get("cost", {}).get("min")
            if min_cost:
                self._min_notional_cache[symbol] = float(min_cost)
                return float(min_cost)
        except Exception as e:
            logger.debug("Could not fetch min_notional for %s: %s", symbol, e)

        self._min_notional_cache[symbol] = DEFAULT_MIN_NOTIONAL
        return DEFAULT_MIN_NOTIONAL

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

        Pre-validates MIN_NOTIONAL, attaches clientOrderId for idempotency,
        and handles rate limiting.

        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            side: "buy" or "sell"
            order_type: "market" or "limit"
            amount: Order size in base currency
            price: Price for limit orders (ignored for market)
            params: Additional params (e.g., clientOrderId, postOnly)

        Returns:
            Order response dict from exchange

        Raises:
            ValueError: If order value is below MIN_NOTIONAL
            ccxt.ExchangeError: On exchange-level errors
        """
        params = params or {}

        # MIN_NOTIONAL check
        check_price = price or self._get_ticker_price(symbol)
        if check_price:
            notional = amount * check_price
            min_notional = self.get_min_notional(symbol)
            if notional < min_notional:
                raise ValueError(
                    f"Order value ${notional:.2f} below MIN_NOTIONAL "
                    f"${min_notional:.2f} for {symbol}"
                )

        self.rate_limiter.acquire(weight=1)

        logger.info(
            "📝 Creating %s %s order: %s %.6f @ %s  params=%s",
            side.upper(), order_type, symbol, amount,
            f"${price:.2f}" if price else "MARKET",
            {k: v for k, v in params.items() if k != "clientOrderId"},
        )

        response = self.exchange.create_order(
            symbol=symbol,
            type=order_type,
            side=side,
            amount=amount,
            price=price,
            params=params,
        )

        logger.info(
            "✅ Order created: id=%s status=%s filled=%s",
            response.get("id"),
            response.get("status"),
            response.get("filled"),
        )
        return response

    def cancel_order(
        self, order_id: str, symbol: str, max_retries: int = 3
    ) -> dict:
        """
        Cancel an open order with retry on transient errors.

        Args:
            order_id: Exchange order ID to cancel
            symbol: Trading pair
            max_retries: Max retry attempts on NetworkError

        Returns:
            Cancelled order dict from exchange
        """
        for attempt in range(1, max_retries + 1):
            try:
                self.rate_limiter.acquire(weight=1)
                result = self.exchange.cancel_order(order_id, symbol)
                logger.info("❌ Cancelled order %s on %s", order_id, symbol)
                return result
            except ccxt.NetworkError as e:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "Cancel retry %d/%d for %s: %s (waiting %ds)",
                        attempt, max_retries, order_id, e, wait,
                    )
                    time.sleep(wait)
                else:
                    raise
            except ccxt.OrderNotFound:
                logger.warning("Order %s not found (already filled/cancelled?)", order_id)
                return {"id": order_id, "status": "cancelled", "info": "not_found"}

    def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """
        Get all open orders, optionally filtered by symbol.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of open order dicts
        """
        self.rate_limiter.acquire(weight=1)
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            logger.debug("Found %d open orders%s",
                         len(orders), f" for {symbol}" if symbol else "")
            return orders
        except Exception as e:
            logger.error("Failed to fetch open orders: %s", e)
            return []

    def fetch_order(self, order_id: str, symbol: str) -> Optional[dict]:
        """
        Fetch a specific order by ID for reconciliation.

        Args:
            order_id: Exchange order ID
            symbol: Trading pair

        Returns:
            Order dict or None if not found
        """
        self.rate_limiter.acquire(weight=1)
        try:
            return self.exchange.fetch_order(order_id, symbol)
        except ccxt.OrderNotFound:
            logger.warning("Order %s not found on %s", order_id, symbol)
            return None
        except Exception as e:
            logger.error("Failed to fetch order %s: %s", order_id, e)
            return None

    def _get_ticker_price(self, symbol: str) -> Optional[float]:
        """Get last price for MIN_NOTIONAL estimation."""
        try:
            self.rate_limiter.acquire(weight=1)
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker.get("last")
        except Exception:
            return None

    @staticmethod
    def now() -> datetime:
        """Get current UTC time."""
        return datetime.utcnow()
