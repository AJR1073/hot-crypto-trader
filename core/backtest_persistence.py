"""
BacktestPersistence: Save backtest runs and trades to the database.

Provides utilities for persisting Backtesting.py results to SQL
for analysis and comparison.
"""

from typing import Optional

import pandas as pd


def save_backtest_to_db(
    stats: dict,
    trades_df: pd.DataFrame,
    exchange: str,
    symbol: str,
    timeframe: str,
    strategy_name: str,
    initial_cash: float,
    db_url: Optional[str] = None,
) -> int:
    """
    Save backtest results to the database.

    Args:
        stats: Backtesting.py stats dict
        trades_df: DataFrame of trades from backtest
        exchange: Exchange name
        symbol: Trading pair
        timeframe: Candle timeframe
        strategy_name: Name of the strategy
        initial_cash: Starting capital
        db_url: Database URL override

    Returns:
        ID of the created BacktestRun record
    """
    # TODO: Implement in Phase 5
    raise NotImplementedError("Will be implemented in Phase 5")
