#!/usr/bin/env python3
"""
Test script for Market Scanner.
Uses live CCXT connection (or fallback) and CoinGecko API.
"""

import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.utils import setup_logging
from core.exchange_client import ExchangeClient
from core.scanner import MarketScanner
import yaml

def load_config(config_path: str) -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def main():
    logger = setup_logging()
    
    # Load config to get scanner settings
    try:
        # Load config but OVERRIDE for testing purposes to ensure we see output
        # config = load_config("config/live.yaml")
        # scanner_config = config.get("scanner", {})
        scanner_config = {
            "min_volume": 10000,       # $10k
            "min_change_pct": 0.5,     # 0.5%
            "max_symbols": 5
        }
    except Exception as e:
        logger.warning(f"Could not load config: {e}. Using defaults.")
        scanner_config = {
            "min_volume": 1000000,
            "min_change_pct": 2.0, # Lower for testing
            "max_symbols": 5
        }

    logger.info("Initializing Exchange Client...")
    try:
        # Use kraken public for testing
        client = ExchangeClient(exchange_name="kraken")
    except Exception as e:
        logger.error(f"Failed to init exchange: {e}")
        return

    logger.info("Initializing Scanner...")
    scanner = MarketScanner(client, scanner_config)
    
    # Test 1: CoinGecko Trending
    logger.info("\n--- Test 1: CoinGecko Trending ---")
    trending = scanner.get_coingecko_trending_tickers()
    logger.info(f"Trending: {trending}")
    
    # Test 2: Exchange Movers
    logger.info("\n--- Test 2: Exchange Movers ---")
    # Note: Kraken has extensive pair support for USD markets
    movers = scanner.scan_exchange_movers()
    for m in movers[:5]:
        logger.info(f"Mover: {m}")
        
    # Test 3: Recommendation
    logger.info("\n--- Test 3: Hot Picks ---")
    hot_picks = scanner.find_hot_opportunities()
    logger.info(f"Final Recommendations: {hot_picks}")

if __name__ == "__main__":
    main()
