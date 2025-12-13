"""
Database package for HOT-Crypto.

Provides SQLAlchemy models and database utilities.
"""

from .base import Base
from .models import OHLCV, BacktestRun, BacktestTrade
from .init_db import init_db, get_db_url, get_session, get_engine
from .persistence import save_backtest_to_db

__all__ = [
    "Base",
    "OHLCV",
    "BacktestRun", 
    "BacktestTrade",
    "init_db",
    "get_db_url",
    "get_session",
    "get_engine",
    "save_backtest_to_db",
]
