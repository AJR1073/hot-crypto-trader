"""
Market Scanner Module.

Responsible for discovering potential trading opportunities by:
1. Scanning exchange for high volatility/volume movers.
2. Checking external APIs (CoinGecko) for trending search terms.
3. Combining signals to recommend "Hot" symbols.
"""

import logging
import time
from typing import List, Dict, Optional

import requests
import ccxt

from .exchange_client import ExchangeClient

logger = logging.getLogger(__name__)


class MarketScanner:
    """
    Scans the market for trending and high-volatility assets.
    """

    def __init__(self, exchange_client: ExchangeClient, config: dict):
        """
        Initialize scanner.

        Args:
            exchange_client: Initialized ExchangeClient
            config: Scanner configuration dict
        """
        self.client = exchange_client
        self.config = config
        self.min_volume = config.get("min_volume", 1000000)
        self.min_change_pct = config.get("min_change_pct", 5.0)
        self.coingecko_url = "https://api.coingecko.com/api/v3/search/trending"
        
        logger.info(f"MarketScanner initialized (Vol>${self.min_volume:,.0f}, Chg>{self.min_change_pct}%)")

    def get_coingecko_trending_tickers(self) -> List[str]:
        """
        Fetch trending search coins from CoinGecko.
        Returns a list of ticker symbols (e.g., ['BTC', 'ETH', 'PEPE']).
        """
        try:
            response = requests.get(self.coingecko_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Extract symbols from 'coins' list
                trending = [item['item']['symbol'].upper() for item in data.get('coins', [])]
                logger.info(f"CoinGecko Trending: {trending}")
                return trending
            else:
                logger.warning(f"CoinGecko API failed: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching CoinGecko trending: {e}")
            return []

    def scan_exchange_movers(self, quote_currency: str = "USDT") -> List[Dict]:
        """
        Scan exchange for high volume/volatility movers.
        
        Args:
            quote_currency: Filter for pairs ending in this (e.g., 'USDT')
            
        Returns:
            List of dicts with symbol info: {'symbol': 'BTC/USDT', 'change': 5.5, 'volume': 100M}
        """
        try:
            # Fetch all tickers (snapshot)
            # using ccxt fetch_tickers if available
            if not self.client.exchange.has['fetchTickers']:
                logger.warning("Exchange does not support fetchTickers")
                return []
                
            tickers = self.client.exchange.fetch_tickers()
            
            movers = []
            for symbol, data in tickers.items():
                # Filter by quote currency
                if not symbol.endswith(f"/{quote_currency}"):
                    continue
                    
                # Safeget stats
                quote_vol = data.get('quoteVolume')
                percentage = data.get('percentage')
                
                if quote_vol is None or percentage is None:
                    continue
                    
                # Apply filters
                if quote_vol >= self.min_volume and abs(percentage) >= self.min_change_pct:
                    movers.append({
                        "symbol": symbol,
                        "change": percentage,
                        "volume": quote_vol
                    })
            
            # Sort by change % descending
            movers.sort(key=lambda x: abs(x['change']), reverse=True)
            
            logger.info(f"Found {len(movers)} exchange movers meeting criteria")
            return movers
            
        except Exception as e:
            logger.error(f"Error scanning exchange: {e}")
            return []

    def find_hot_opportunities(self) -> List[str]:
        """
        Combine Social Trends and Technical Movers to find top opportunities.
        
        Strategy:
        1. Get Exchange Movers (Hard Data).
        2. Get Social Trending (Soft Data).
        3. Prioritize intersection, then high momentum movers.
        """
        logger.info("Starting Market Scan...")
        
        # 1. Get Technical Movers
        movers = self.scan_exchange_movers()
        mover_symbols = {m['symbol'].split('/')[0] for m in movers} # Base asset set
        
        # 2. Get Social Trending
        trending = self.get_coingecko_trending_tickers()
        trending_set = set(trending)
        
        # 3. Find Intersection (Hot Picks)
        hot_picks = []
        
        # Check movers against trending
        for mover in movers:
            base = mover['symbol'].split('/')[0]
            if base in trending_set:
                logger.info(f"🔥 HOT PICK: {mover['symbol']} (Trending + Mover {mover['change']}%)")
                hot_picks.append(mover['symbol'])
        
        # If not enough hot picks, add top movers
        if len(hot_picks) < self.config.get("max_symbols", 3):
            remaining = self.config.get("max_symbols", 3) - len(hot_picks)
            for mover in movers:
                if mover['symbol'] not in hot_picks:
                    hot_picks.append(mover['symbol'])
                    if len(hot_picks) >= self.config.get("max_symbols", 3):
                        break
        
        logger.info(f"Scanner Recommendations: {hot_picks}")
        return hot_picks
