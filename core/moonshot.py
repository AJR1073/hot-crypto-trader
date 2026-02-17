"""
Moonshot Scanner.

Specialized scanner for 100x potential gems:
1. Low Market Cap (via CoinGecko API)
2. High Volume/MCap Ratios (Momentum)
3. New Listings (Recent additions)
"""

import logging
import requests
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class MoonshotScanner:
    def __init__(self):
        self.cg_url = "https://api.coingecko.com/api/v3"
        self.min_vol_mcap_ratio = 0.1  # High volume relative to size
        self.max_mcap = 100_000_000    # $100M Cap (Small Cap)
        
    def find_moonshots(self) -> List[Dict]:
        """Find potential 100x gems."""
        try:
            # Get coins with market data (Top 250 per page)
            # We want smaller ones, so maybe page 3-4? 
            # Actually, let's get markets and filter
            url = f"{self.cg_url}/coins/markets"
            params = {
                "vs_currency": "usd",
                "order": "volume_desc", # High volume
                "per_page": 100,
                "page": 1,
                "sparkline": False
            }
            
            gems = []
            
            # Scan top 300 by volume to find low cap high volume
            for page in range(1, 4):
                params["page"] = page
                response = requests.get(url, params=params, timeout=10)
                if response.status_code != 200:
                    break
                    
                data = response.json()
                for coin in data:
                    mcap = coin.get("market_cap") or 0
                    vol = coin.get("total_volume") or 0
                    
                    if mcap > 0 and mcap < self.max_mcap:
                        ratio = vol / mcap
                        if ratio > self.min_vol_mcap_ratio:
                            gems.append({
                                "symbol": coin["symbol"].upper(),
                                "name": coin["name"],
                                "price": coin["current_price"],
                                "mcap": mcap,
                                "volume": vol,
                                "ratio": ratio,
                                "change_24h": coin["price_change_percentage_24h"]
                            })
                            
            # Sort by "Hype Ratio" (Volume/Mcap)
            gems.sort(key=lambda x: x["ratio"], reverse=True)
            return gems[:10]
            
        except Exception as e:
            logger.error(f"Moonshot scan failed: {e}")
            return []
