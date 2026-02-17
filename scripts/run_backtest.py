#!/usr/bin/env python3
"""
Run backtests for trading strategies.

Usage:
    # Single strategy backtest
    python scripts/run_backtest.py --symbol BTC/USDT --timeframe 4h --strategy TREND_EMA --use-sql

    # Multi-strategy comparison (all 4 strategies on BTC and ETH)
    python scripts/run_backtest.py --all --timeframe 4h --use-sql

    # Custom symbols for multi-strategy
    python scripts/run_backtest.py --all --symbols BTC/USDT,ETH/USDT,SOL/USDT --use-sql
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.utils import setup_logging
from core.backtester import run_single_backtest
from core.multi_backtester import run_all_backtests, format_results_table


def main():
    parser = argparse.ArgumentParser(
        description="Run trading strategy backtests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single strategy
  python scripts/run_backtest.py --symbol BTC/USDT --timeframe 4h --strategy TREND_EMA --use-sql

  # All strategies comparison
  python scripts/run_backtest.py --all --timeframe 4h --use-sql

  # All strategies with custom symbols
  python scripts/run_backtest.py --all --symbols BTC/USDT,ETH/USDT --use-sql --cash 50000
        """
    )
    
    # Mode selection
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all strategies on multiple symbols (multi-strategy comparison)"
    )
    
    # Symbol arguments
    parser.add_argument(
        "--symbol", 
        default="BTC/USDT", 
        help="Trading pair for single-strategy mode (default: BTC/USDT)"
    )
    parser.add_argument(
        "--symbols",
        default="BTC/USDT,ETH/USDT",
        help="Comma-separated symbols for --all mode (default: BTC/USDT,ETH/USDT)"
    )
    
    # Other arguments
    parser.add_argument(
        "--timeframe", 
        default="4h", 
        help="Candle timeframe (default: 4h)"
    )
    parser.add_argument(
        "--strategy", 
        default="TREND_EMA",
        choices=["TREND_EMA", "MR_BB", "SQZ_BO", "GRID_LR", "SUPERTREND", 
                 "RSI_DIV", "MACD_X", "ICHI", "VWAP", "DUAL_T", "TURTLE", 
                 "TRIPLE_MOMO", "TRIPLE_V2", "VOL_HUNT"],
        help="Strategy to run (default: TREND_EMA)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Number of candles to use (default: 500)"
    )
    parser.add_argument(
        "--cash",
        type=float,
        default=10000.0,
        help="Starting capital (default: 10000)"
    )
    parser.add_argument(
        "--commission",
        type=float,
        default=0.0005,
        help="Commission rate (default: 0.0005 = 0.05%%)"
    )
    parser.add_argument(
        "--use-sql", 
        action="store_true", 
        help="Use SQLite database for OHLCV data"
    )
    parser.add_argument(
        "--db-url", 
        help="Database URL override (default: from HOT_CRYPTO_DB_URL env)"
    )
    parser.add_argument(
        "--persist", 
        action="store_true", 
        help="Save results to database (Phase 5)"
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Show interactive plot after single-strategy backtest"
    )
    
    args = parser.parse_args()
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info("HOT-Crypto Backtester")
    logger.info("=" * 60)
    
    try:
        if args.all:
            # Multi-strategy mode
            symbols = [s.strip() for s in args.symbols.split(",")]
            
            logger.info(f"Mode: Multi-Strategy Comparison")
            logger.info(f"Symbols: {symbols}")
            
            results_df = run_all_backtests(
                symbols=symbols,
                timeframe=args.timeframe,
                limit=args.limit,
                cash=args.cash,
                commission=args.commission,
                use_sql=args.use_sql,
                db_url=args.db_url,
                persist=args.persist,
            )
            
            print("\n" + "=" * 80)
            print("MULTI-STRATEGY BACKTEST RESULTS")
            print("=" * 80)
            print(format_results_table(results_df))
            print("=" * 80)
            
            # Summary
            if not results_df.empty:
                best = results_df.iloc[0]
                print(f"\n🏆 Best performer: {best['strategy']} on {best['symbol']}")
                print(f"   Final Equity: ${best['final_equity']:,.2f}")
                print(f"   Return: {best['return_pct']:.2f}%")
                print(f"   Data Period: {best.get('start_date', 'N/A')} to {best.get('end_date', 'N/A')} ({best.get('days_span', 0)} days)")
            
        else:
            # Single-strategy mode
            stats, bt = run_single_backtest(
                strategy_name=args.strategy,
                symbol=args.symbol,
                timeframe=args.timeframe,
                limit=args.limit,
                cash=args.cash,
                commission=args.commission,
                use_sql=args.use_sql,
                db_url=args.db_url,
                persist=args.persist,
            )
            
            # Print full stats
            print("\n" + "=" * 60)
            print("FULL STATISTICS")
            print("=" * 60)
            print(stats)
            print("=" * 60)
            
            if args.plot:
                logger.info("Opening interactive plot...")
                bt.plot()
            
    except ValueError as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

# Examples:
#   python scripts/run_backtest.py --symbol BTC/USDT --timeframe 4h --strategy TREND_EMA --use-sql --persist
#   python scripts/run_backtest.py --all --timeframe 4h --use-sql --persist
#   python scripts/run_backtest.py --all --symbols BTC/USDT,ETH/USDT,SOL/USDT --use-sql --cash 50000
