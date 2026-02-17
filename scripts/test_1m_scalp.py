#!/usr/bin/env python3
"""
Test 1m Scalping specific configuration.
"""
import sys
from pathlib import Path
import logging

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.mean_reversion_bb import MeanReversionBBBacktest
from backtesting import Backtest
from backtesting.lib import FractionalBacktest
from core.sql_data_source import SQLDataSource
from core.backtester import prepare_ohlcv_for_backtesting
from core.utils import setup_logging

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    symbol = "BTC/USDT"
    timeframe = "1m"
    
    # 1. Load Data
    data_source = SQLDataSource(db_url="sqlite:///data/hot_crypto.db")
    df = data_source.get_ohlcv(symbol, timeframe, limit=1000)
    df = prepare_ohlcv_for_backtesting(df)
    
    logger.info(f"Loaded {len(df)} candles for {symbol} {timeframe}")

    # 2. Configure Strategy for 1m Scalping
    # Using stricter parameters to filter noise
    class ScalpMRBB(MeanReversionBBBacktest):
        sma_period = 50        # Default 20
        std_dev_mult = 3.0     # Default 2.0
        atr_stop_mult = 1.5    # Tighter stops
        
    logger.info("Running Backtest with: SMA=50, STD=3.0, Stop=1.5ATR")
    
    # 3. Run Backtest
    bt = FractionalBacktest(
        df,
        ScalpMRBB,
        cash=10000,
        commission=0.0005,
        exclusive_orders=True
    )
    
    stats = bt.run()
    
    print("\n" + "="*50)
    print("SCALP TEST RESULTS")
    print("="*50)
    print(stats)
    print("="*50)

if __name__ == "__main__":
    main()
