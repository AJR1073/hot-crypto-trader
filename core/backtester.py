"""
Backtester: Single-strategy backtest runner using Backtesting.py

Provides utilities for running backtests with different data sources
and returning standardized results.

NOTE: Uses FractionalBacktest from backtesting.lib to support crypto
trading where asset prices may exceed account balance.
"""

import logging
from typing import Optional, Tuple, Any

import pandas as pd
from backtesting import Backtest
from backtesting.lib import SignalStrategy, TrailingStrategy

# Import for fractional trading support (crypto where price > cash)
try:
    from backtesting.lib import FractionalBacktest
    USE_FRACTIONAL = True
except ImportError:
    FractionalBacktest = Backtest
    USE_FRACTIONAL = False

from .data_source import DataSource
from .sql_data_source import SQLDataSource
from .ccxt_data_source import CCXTDataSource
from .exchange_client import ExchangeClient
from strategies.trend_ema import TrendEmaBacktest

logger = logging.getLogger(__name__)


def prepare_ohlcv_for_backtesting(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare OHLCV DataFrame for Backtesting.py.
    
    Backtesting.py expects columns: Open, High, Low, Close, Volume (capitalized)
    and a DatetimeIndex.
    
    Args:
        df: DataFrame with lowercase columns (open, high, low, close, volume)
        
    Returns:
        DataFrame with capitalized column names ready for Backtesting.py
    """
    # Make a copy to avoid modifying original
    df = df.copy()
    
    # Rename columns to match Backtesting.py expectations
    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    })
    
    # Ensure index is datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must have a DatetimeIndex")
    
    # Remove timezone info if present (Backtesting.py prefers naive datetimes)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    
    return df


def run_trend_ema_backtest(
    symbol: str,
    timeframe: str = "4h",
    limit: int = 1000,
    cash: float = 10000.0,
    commission: float = 0.0005,
    use_sql: bool = False,
    db_url: Optional[str] = None,
    persist: bool = False,
    # Strategy parameters (optional overrides)
    ema_fast: int = 20,
    ema_slow: int = 50,
    atr_period: int = 14,
    atr_stop_mult: float = 1.5,
    rr_ratio: float = 2.0,
    risk_per_trade: float = 0.01,
) -> Tuple[Any, Backtest]:
    """
    Run a Trend EMA backtest.

    Args:
        symbol: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe
        limit: Number of candles to use
        cash: Starting capital
        commission: Commission rate (0.0005 = 0.05%)
        use_sql: Use SQLDataSource if True, else CCXTDataSource
        db_url: Database URL override
        persist: Save results to database if True (not yet implemented)
        ema_fast: Fast EMA period
        ema_slow: Slow EMA period
        atr_period: ATR period
        atr_stop_mult: ATR multiplier for stop loss
        rr_ratio: Risk/reward ratio for take profit
        risk_per_trade: Risk per trade as fraction of equity

    Returns:
        Tuple of (stats, Backtest object)
    """
    logger.info("=" * 60)
    logger.info(f"Running Trend EMA Backtest")
    logger.info(f"Symbol: {symbol}, Timeframe: {timeframe}")
    logger.info(f"Cash: ${cash:,.2f}, Commission: {commission*100:.3f}%")
    logger.info("=" * 60)
    
    # Get data source
    if use_sql:
        logger.info(f"Using SQL data source")
        data_source: DataSource = SQLDataSource(db_url=db_url)
    else:
        logger.info(f"Using CCXT data source (live)")
        client = ExchangeClient()
        data_source = CCXTDataSource(client)
    
    # Fetch OHLCV data
    df = data_source.get_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    logger.info(f"Loaded {len(df)} candles")
    
    # Prepare for backtesting
    df = prepare_ohlcv_for_backtesting(df)
    
    # Create and configure strategy class with parameters
    class ConfiguredTrendEma(TrendEmaBacktest):
        pass
    
    ConfiguredTrendEma.ema_fast = ema_fast
    ConfiguredTrendEma.ema_slow = ema_slow
    ConfiguredTrendEma.atr_period = atr_period
    ConfiguredTrendEma.atr_stop_mult = atr_stop_mult
    ConfiguredTrendEma.rr_ratio = rr_ratio
    ConfiguredTrendEma.risk_per_trade = risk_per_trade
    
    # Run backtest - use FractionalBacktest for crypto (price > cash)
    bt = FractionalBacktest(
        df,
        ConfiguredTrendEma,
        cash=cash,
        commission=commission,
        exclusive_orders=True,
    )
    
    stats = bt.run()
    
    # Log results
    logger.info("=" * 60)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 60)
    logger.info(f"Final Equity: ${stats['Equity Final [$]']:,.2f}")
    logger.info(f"Return: {stats['Return [%]']:.2f}%")
    logger.info(f"Max Drawdown: {stats['Max. Drawdown [%]']:.2f}%")
    logger.info(f"# Trades: {stats['# Trades']}")
    if stats['# Trades'] > 0:
        logger.info(f"Win Rate: {stats['Win Rate [%]']:.1f}%")
        logger.info(f"Avg Trade: {stats['Avg. Trade [%]']:.2f}%")
    logger.info("=" * 60)
    
    if persist:
        logger.warning("Persistence not yet implemented (Phase 5)")
    
    return stats, bt


def run_single_backtest(
    strategy_name: str,
    symbol: str,
    timeframe: str = "4h",
    limit: int = 1000,
    cash: float = 10000.0,
    commission: float = 0.0005,
    use_sql: bool = False,
    db_url: Optional[str] = None,
    persist: bool = False,
) -> Tuple[Any, Backtest]:
    """
    Run a single-strategy backtest by name.

    Args:
        strategy_name: Name of strategy (TREND_EMA, MR_BB, SQZ_BO, GRID_LR)
        symbol: Trading pair
        timeframe: Candle timeframe
        limit: Number of candles
        cash: Starting capital
        commission: Commission rate
        use_sql: Use SQL data source
        db_url: Database URL override
        persist: Save to database

    Returns:
        Tuple of (stats, Backtest object)
    """
    strategy_name = strategy_name.upper()
    
    # Import strategies
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
    
    if strategy_name not in STRATEGIES:
        raise ValueError(
            f"Unknown strategy: {strategy_name}. "
            f"Available: {', '.join(STRATEGIES.keys())}"
        )
    
    strategy_class = STRATEGIES[strategy_name]
    
    logger.info("=" * 60)
    logger.info(f"Running {strategy_name} Backtest")
    logger.info(f"Symbol: {symbol}, Timeframe: {timeframe}")
    logger.info(f"Cash: ${cash:,.2f}, Commission: {commission*100:.3f}%")
    logger.info("=" * 60)
    
    # Get data source
    if use_sql:
        logger.info(f"Using SQL data source")
        data_source: DataSource = SQLDataSource(db_url=db_url)
    else:
        logger.info(f"Using CCXT data source (live)")
        client = ExchangeClient()
        data_source = CCXTDataSource(client)
    
    # Fetch OHLCV data
    df = data_source.get_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    logger.info(f"Loaded {len(df)} candles")
    
    # Prepare for backtesting
    df = prepare_ohlcv_for_backtesting(df)
    
    # Run backtest
    bt = FractionalBacktest(
        df,
        strategy_class,
        cash=cash,
        commission=commission,
        exclusive_orders=True,
    )
    
    stats = bt.run()
    
    # Log results
    logger.info("=" * 60)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 60)
    logger.info(f"Final Equity: ${stats['Equity Final [$]']:,.2f}")
    logger.info(f"Return: {stats['Return [%]']:.2f}%")
    logger.info(f"Max Drawdown: {stats['Max. Drawdown [%]']:.2f}%")
    logger.info(f"# Trades: {stats['# Trades']}")
    if stats['# Trades'] > 0:
        win_rate = stats['Win Rate [%]']
        avg_trade = stats['Avg. Trade [%]']
        if not pd.isna(win_rate):
            logger.info(f"Win Rate: {win_rate:.1f}%")
        if not pd.isna(avg_trade):
            logger.info(f"Avg Trade: {avg_trade:.2f}%")
    logger.info("=" * 60)
    
    if persist:
        from db.persistence import save_backtest_to_db
        # Trades are stored in stats['_trades'], not bt._trades
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
        logger.info(f"Saved to database as run #{run_id}")
    
    return stats, bt
