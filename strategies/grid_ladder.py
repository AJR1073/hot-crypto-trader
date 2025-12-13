"""
Grid Ladder Strategy.

DCA-style grid trading that places laddered buy orders below a
moving average and takes profit at the mean.

Creates multiple entry levels below the SMA, each at fixed
ATR intervals. Takes profit when price returns to the mean.

Contains:
- GridLadderBacktest: Backtesting.py Strategy class
- GridLadderLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import SMA, ATR


class GridLadderBacktest(Strategy):
    """
    Backtesting.py implementation of Grid Ladder strategy.
    
    Places laddered entries below the moving average and
    takes profit when price returns to the mean.
    """
    
    # Strategy parameters
    sma_period = 50
    atr_period = 14
    levels = 5  # Number of grid levels
    step_atr_mult = 0.5  # Distance between levels in ATR units
    size_per_level = 0.05  # 5% of equity per level

    def init(self):
        """Initialize indicators."""
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        
        # SMA for mean and grid center
        self.sma = self.I(SMA, close, self.sma_period)
        
        # ATR for level spacing
        self.atr = self.I(ATR, high, low, close, self.atr_period)
        
        # Track which levels are filled
        self.level_filled = [False] * self.levels

    def next(self):
        """Process each bar and make trading decisions."""
        # Skip if not enough data
        if len(self.data) < self.sma_period + 5:
            return
            
        close = self.data.Close[-1]
        low_price = self.data.Low[-1]
        high_price = self.data.High[-1]
        ma = self.sma[-1]
        atr = self.atr[-1]
        
        # Skip if indicators invalid
        if np.isnan(ma) or np.isnan(atr) or atr <= 0:
            return
        
        # Check for take profit: close all positions when price >= MA
        if self.position and close >= ma:
            self.position.close()
            # Reset all levels
            self.level_filled = [False] * self.levels
            return
        
        # Check each grid level for entry
        for i in range(self.levels):
            level_num = i + 1  # 1-indexed
            buy_level = ma - (level_num * self.step_atr_mult * atr)
            
            # Check if price touched this level (low <= level <= high)
            if not self.level_filled[i] and low_price <= buy_level <= high_price:
                # Enter at this level
                # Use smaller size per level
                size_fraction = self.size_per_level
                
                # Simple stop below the lowest grid level
                stop_price = ma - ((self.levels + 1) * self.step_atr_mult * atr)
                tp_price = ma  # TP at mean
                
                self.buy(size=size_fraction, sl=stop_price, tp=tp_price)
                self.level_filled[i] = True


class GridLadderLive(BaseStrategy):
    """
    Live trading implementation of Grid Ladder strategy.
    
    Maintains per-level state and emits signals for each level independently.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.sma_period = config.get("sma_period", 50)
        self.atr_period = config.get("atr_period", 14)
        self.levels = config.get("levels", 5)
        self.step_atr_mult = config.get("step_atr_mult", 0.5)
        self.size_per_level = config.get("size_per_level", 0.05)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        # Initialize level tracking
        if "levels_filled" not in state:
            state["levels_filled"] = [False] * self.levels
        
        df = state.get("df")
        if df is None or len(df) < self.sma_period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        
        ma = SMA(close, self.sma_period).iloc[-1]
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        
        current_close = candle["close"]
        current_low = candle["low"]
        current_high = candle["high"]
        
        levels_filled = state["levels_filled"]
        any_position = any(levels_filled)
        
        # Take profit: close all when price >= MA
        if any_position and current_close >= ma:
            state["levels_filled"] = [False] * self.levels
            return StrategySignal(symbol=symbol, action="CLOSE_LONG",
                                 extra={"reason": "grid_take_profit", "levels_closed": sum(levels_filled)})
        
        # Check each level for entry
        for i in range(self.levels):
            level_num = i + 1
            buy_level = ma - (level_num * self.step_atr_mult * atr)
            
            if not levels_filled[i] and current_low <= buy_level <= current_high:
                levels_filled[i] = True
                state["levels_filled"] = levels_filled
                
                stop = ma - ((self.levels + 1) * self.step_atr_mult * atr)
                return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                     extra={
                                         "level": level_num,
                                         "entry_price": buy_level,
                                         "stop": stop,
                                         "tp": ma,
                                     })
        
        return StrategySignal(symbol=symbol, action="HOLD")
