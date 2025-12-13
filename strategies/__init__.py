"""
HOT-Crypto Strategies Module

Contains trading strategies with both Backtesting.py and Live versions:
- Trend EMA: EMA crossover trend following
- Mean Reversion BB: Bollinger Bands mean reversion
- Squeeze Breakout: Volatility squeeze breakout
- Grid Ladder: DCA grid trading
"""

from .base import BaseStrategy, StrategySignal
from .indicators import EMA, SMA, STD, ATR, Bollinger, BollingerBandwidth
from .trend_ema import TrendEmaBacktest, TrendEmaLive
from .mean_reversion_bb import MeanReversionBBBacktest, MeanReversionBBLive
from .squeeze_breakout import SqueezeBreakoutBacktest, SqueezeBreakoutLive
from .grid_ladder import GridLadderBacktest, GridLadderLive
from .supertrend import SuperTrendBacktest, SuperTrendLive

__all__ = [
    # Base
    "BaseStrategy",
    "StrategySignal",
    # Indicators
    "EMA", "SMA", "STD", "ATR", "Bollinger", "BollingerBandwidth",
    # Strategies
    "TrendEmaBacktest", "TrendEmaLive",
    "MeanReversionBBBacktest", "MeanReversionBBLive",
    "SqueezeBreakoutBacktest", "SqueezeBreakoutLive",
    "GridLadderBacktest", "GridLadderLive",
    "SuperTrendBacktest", "SuperTrendLive",
]
