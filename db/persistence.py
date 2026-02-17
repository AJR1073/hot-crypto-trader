"""
Backtest persistence: Save backtest runs and trades to the database.

Provides functions to save Backtesting.py results to SQLite for later
analysis via the Streamlit dashboard.
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

import pandas as pd
from sqlalchemy.orm import Session

from .init_db import get_engine
from .models import BacktestRun, BacktestTrade

logger = logging.getLogger(__name__)


def save_backtest_to_db(
    stats: Any,
    trades_df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    strategy_name: str,
    initial_cash: float,
    exchange: str = "kraken",
    db_url: Optional[str] = None,
) -> int:
    """
    Save a backtest run and its trades to the database.

    Args:
        stats: Backtesting.py stats Series
        trades_df: DataFrame of trades from bt._trades
        symbol: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "4h")
        strategy_name: Name of the strategy
        initial_cash: Starting capital
        exchange: Exchange name
        db_url: Database URL override

    Returns:
        The ID of the saved BacktestRun
    """
    engine = get_engine(db_url)
    
    # Extract key stats
    final_equity = float(stats["Equity Final [$]"]) if not pd.isna(stats["Equity Final [$]"]) else initial_cash
    max_drawdown = float(stats["Max. Drawdown [%]"]) if not pd.isna(stats["Max. Drawdown [%]"]) else 0.0
    sharpe = float(stats["Sharpe Ratio"]) if not pd.isna(stats["Sharpe Ratio"]) else 0.0
    trades_count = int(stats["# Trades"]) if not pd.isna(stats["# Trades"]) else 0
    
    # Serialize full stats to JSON (convert problematic values)
    stats_dict = {}
    for key, val in stats.items():
        if key.startswith("_"):
            continue  # Skip internal objects like _equity_curve, _trades, _strategy
        try:
            if pd.isna(val):
                stats_dict[key] = None
            elif isinstance(val, (datetime, pd.Timestamp)):
                stats_dict[key] = str(val)
            elif isinstance(val, pd.Timedelta):
                stats_dict[key] = str(val)
            else:
                stats_dict[key] = val
        except Exception:
            stats_dict[key] = str(val)
    
    stats_json = json.dumps(stats_dict, default=str)
    
    with Session(engine) as session:
        # Create run record
        run = BacktestRun(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            strategy_name=strategy_name,
            initial_cash=initial_cash,
            final_equity=final_equity,
            max_drawdown_pct=max_drawdown,
            sharpe_ratio=sharpe,
            trades_count=trades_count,
            stats_json=stats_json,
        )
        session.add(run)
        session.flush()  # Get the run ID
        run_id = run.id
        
        # Save trades
        if not trades_df.empty:
            for _, trade in trades_df.iterrows():
                # Backtesting.py trade columns: Size, EntryBar, ExitBar, EntryPrice, ExitPrice,
                # PnL, ReturnPct, EntryTime, ExitTime, Duration
                trade_record = BacktestTrade(
                    backtest_run_id=run_id,
                    symbol=symbol,
                    strategy_name=strategy_name,
                    side="LONG" if trade.get("Size", 0) > 0 else "SHORT",
                    size=abs(float(trade.get("Size", 0))),
                    entry_ts=pd.to_datetime(trade.get("EntryTime")),
                    exit_ts=pd.to_datetime(trade.get("ExitTime")) if trade.get("ExitTime") is not None else None,
                    entry_price=float(trade.get("EntryPrice", 0)),
                    exit_price=float(trade.get("ExitPrice", 0)) if trade.get("ExitPrice") is not None else None,
                    pnl=float(trade.get("PnL", 0)) if trade.get("PnL") is not None else None,
                    pnl_pct=float(trade.get("ReturnPct", 0)) * 100 if trade.get("ReturnPct") is not None else None,
                )
                session.add(trade_record)
        
        session.commit()
        logger.info(f"Saved backtest run #{run_id}: {strategy_name} on {symbol} ({trades_count} trades)")
    
    return run_id
