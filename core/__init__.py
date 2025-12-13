"""
HOT-Crypto Core Module

This module contains the core components of the trading engine:
- Exchange client (ccxt wrapper)
- Data sources (SQL and ccxt)
- Backtesting runners
- Portfolio and risk management
- Trade execution
"""

from .utils import setup_logging

__all__ = [
    "setup_logging",
]
