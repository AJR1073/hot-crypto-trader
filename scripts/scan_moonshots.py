"""
CLI Tool for Moonshot Scanner.
Run: python scripts/scan_moonshots.py
"""
import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.moonshot import MoonshotScanner

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("moonshot")

def main():
    print("🚀 Initializing Moonshot Scanner...")
    scanner = MoonshotScanner()
    
    print("🔍 Scanning CoinGecko for low-cap gems (<$100M)...")
    try:
        gems = scanner.find_moonshots()
        
        if not gems:
            print("⚠️ No moonshots found. Market might be quiet.")
            return
            
        print(f"\n✅ Found {len(gems)} Potential Moonshots:\n")
        print(f"{'SYMBOL':<10} {'PRICE':<12} {'MCAP':<12} {'VOL/MCAP':<10} {'24H %':<10}")
        print("-" * 60)
        
        for gem in gems:
            symbol = gem['symbol']
            price = f"${gem['price']:.6f}"
            mcap = f"${gem['mcap']/1e6:.1f}M"
            ratio = f"{gem['ratio']:.2f}"
            change = f"{gem['change_24h']:+.2f}%"
            
            print(f"{symbol:<10} {price:<12} {mcap:<12} {ratio:<10} {change:<10}")
            
        print("\n💡 Tip: Add these to 'config/strategies.yaml' (Volatility Hunter) to trade them!")
        
    except Exception as e:
        logger.error(f"Scan failed: {e}")

if __name__ == "__main__":
    main()
