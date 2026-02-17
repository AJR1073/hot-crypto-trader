"""
MultiBacktester: Run and compare multiple strategies across symbols.

Provides utilities for running all strategies on given symbols and
returning a comparison DataFrame of results.
"""

import logging
from typing import Optional

import pandas as pd
from backtesting import Backtest

try:
    from backtesting.lib import FractionalBacktest
except ImportError:
    FractionalBacktest = Backtest

from .data_source import DataSource
from .sql_data_source import SQLDataSource
from .ccxt_data_source import CCXTDataSource
from .exchange_client import ExchangeClient
from .backtester import prepare_ohlcv_for_backtesting

# Import all strategies
from strategies.trend_ema import TrendEmaBacktest
from strategies.mean_reversion_bb import MeanReversionBBBacktest
from strategies.squeeze_breakout import SqueezeBreakoutBacktest
from strategies.grid_ladder import GridLadderBacktest
from strategies.supertrend import SuperTrendBacktest
from strategies.rsi_divergence import RSIDivergenceBacktest
from strategies.macd_crossover import MACDCrossoverBacktest
from strategies.ichimoku import IchimokuBacktest
from strategies.vwap_bounce import VWAPBounceBacktest
from strategies.dual_thrust import DualThrustBacktest
from strategies.turtle import TurtleBacktest
from strategies.triple_momentum import TripleMomentumBacktest
from strategies.triple_momentum_v2 import TripleMomentumV2Backtest
from strategies.volatility_hunter import VolatilityHunterBacktest

logger = logging.getLogger(__name__)

# Strategy registry
STRATEGIES = {
    "TREND_EMA": TrendEmaBacktest,
    "MR_BB": MeanReversionBBBacktest,
    "SQZ_BO": SqueezeBreakoutBacktest,
    "GRID_LR": GridLadderBacktest,
    "SUPERTREND": SuperTrendBacktest,
    "RSI_DIV": RSIDivergenceBacktest,
    "MACD_X": MACDCrossoverBacktest,
    "ICHI": IchimokuBacktest,
    "VWAP": VWAPBounceBacktest,
    "DUAL_T": DualThrustBacktest,
    "TURTLE": TurtleBacktest,
    "TRIPLE_MOMO": TripleMomentumBacktest,
    "TRIPLE_V2": TripleMomentumV2Backtest,
    "VOL_HUNT": VolatilityHunterBacktest,
}


def run_all_backtests(
    symbols: list[str],
    timeframe: str = "4h",
    limit: int = 1000,
    cash: float = 10000.0,
    commission: float = 0.0005,
    use_sql: bool = False,
    db_url: Optional[str] = None,
    persist: bool = False,
) -> pd.DataFrame:
    """
    Run all strategies (TREND_EMA, MR_BB, SQZ_BO, GRID_LR) for each symbol.

    Args:
        symbols: List of trading pairs (e.g., ["BTC/USDT", "ETH/USDT"])
        timeframe: Candle timeframe to use
        limit: Number of candles to use
        cash: Starting capital per backtest
        commission: Commission rate
        use_sql: Use SQLDataSource if True, else CCXTDataSource
        db_url: Database URL override
        persist: If True, save each run to DB via save_backtest_to_db() (Phase 5)

    Returns:
        DataFrame with columns: symbol, strategy, final_equity,
        return_pct, max_drawdown_pct, sharpe_ratio, trades_count
    """
    logger.info("=" * 60)
    logger.info("Multi-Strategy Backtest Comparison")
    logger.info(f"Symbols: {symbols}")
    logger.info(f"Timeframe: {timeframe}, Limit: {limit}")
    logger.info(f"Cash: ${cash:,.2f}, Commission: {commission*100:.3f}%")
    logger.info("=" * 60)
    
    results = []
    
    for symbol in symbols:
        logger.info(f"\n{'='*40}")
        logger.info(f"Processing {symbol}")
        logger.info(f"{'='*40}")
        
        # Get data source
        if use_sql:
            data_source: DataSource = SQLDataSource(db_url=db_url)
        else:
            client = ExchangeClient()
            data_source = CCXTDataSource(client)
        
        # Fetch OHLCV data once per symbol
        try:
            df = data_source.get_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
            df = prepare_ohlcv_for_backtesting(df)
            
            # Extract date range info
            start_date = df.index.min().strftime('%Y-%m-%d') if len(df) > 0 else 'N/A'
            end_date = df.index.max().strftime('%Y-%m-%d') if len(df) > 0 else 'N/A'
            days_span = (df.index.max() - df.index.min()).days if len(df) > 1 else 0
            
            logger.info(f"Loaded {len(df)} candles for {symbol}")
            logger.info(f"Data Period: {start_date} to {end_date} ({days_span} days)")
        except Exception as e:
            logger.error(f"Failed to load data for {symbol}: {e}")
            continue
            start_date, end_date, days_span = 'N/A', 'N/A', 0
        
        # Run each strategy
        for strategy_name, strategy_class in STRATEGIES.items():
            try:
                logger.info(f"  Running {strategy_name}...")
                
                bt = FractionalBacktest(
                    df,
                    strategy_class,
                    cash=cash,
                    commission=commission,
                    exclusive_orders=True,
                )
                
                stats = bt.run()
                
                results.append({
                    "symbol": symbol,
                    "strategy": strategy_name,
                    "final_equity": stats["Equity Final [$]"],
                    "return_pct": stats["Return [%]"],
                    "max_drawdown_pct": stats["Max. Drawdown [%]"],
                    "sharpe_ratio": stats["Sharpe Ratio"] if not pd.isna(stats["Sharpe Ratio"]) else 0.0,
                    "trades_count": stats["# Trades"],
                    "win_rate": stats["Win Rate [%]"] if not pd.isna(stats["Win Rate [%]"]) else 0.0,
                    "start_date": start_date,
                    "end_date": end_date,
                    "days_span": days_span,
                })
                
                logger.info(f"    -> {strategy_name}: ${stats['Equity Final [$]']:,.2f} "
                           f"({stats['Return [%]']:.2f}%), {stats['# Trades']} trades")
                
                # Save to database if persist=True
                if persist:
                    from db.persistence import save_backtest_to_db
                    # Trades are stored in stats['_trades']
                    trades_df = stats.get('_trades', pd.DataFrame())
                    run_id = save_backtest_to_db(
                        stats=stats,
                        trades_df=trades_df,
                        symbol=symbol,
                        timeframe=timeframe,
                        strategy_name=strategy_name,
                        initial_cash=cash,
                        db_url=db_url,
                    )
                    logger.info(f"      Saved as run #{run_id}")
                
            except Exception as e:
                logger.error(f"  Failed to run {strategy_name}: {e}")
                results.append({
                    "symbol": symbol,
                    "strategy": strategy_name,
                    "final_equity": cash,
                    "return_pct": 0.0,
                    "max_drawdown_pct": 0.0,
                    "sharpe_ratio": 0.0,
                    "trades_count": 0,
                    "win_rate": 0.0,
                })
    
    # Create results DataFrame
    results_df = pd.DataFrame(results)
    
    # Sort by final equity descending
    if not results_df.empty:
        results_df = results_df.sort_values("final_equity", ascending=False)
    
    logger.info("\n" + "=" * 60)
    logger.info("MULTI-STRATEGY COMPARISON COMPLETE")
    logger.info("=" * 60)
    
    return results_df


def format_results_table(df: pd.DataFrame) -> str:
    """
    Format results DataFrame as a readable table.
    
    Args:
        df: Results DataFrame from run_all_backtests
        
    Returns:
        Formatted string table
    """
    if df.empty:
        return "No results to display"
    
    # Format for display
    display_df = df.copy()
    display_df["final_equity"] = display_df["final_equity"].apply(lambda x: f"${x:,.2f}")
    display_df["return_pct"] = display_df["return_pct"].apply(lambda x: f"{x:.2f}%")
    display_df["max_drawdown_pct"] = display_df["max_drawdown_pct"].apply(lambda x: f"{x:.2f}%")
    display_df["sharpe_ratio"] = display_df["sharpe_ratio"].apply(lambda x: f"{x:.3f}")
    display_df["win_rate"] = display_df["win_rate"].apply(lambda x: f"{x:.1f}%")
    
    return display_df.to_string(index=False)
