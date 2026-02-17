"""
Dual Thrust Strategy.

Range breakout system based on previous session range:
- Long: Price > Open + K1 * Range
- Short: Price < Open - K2 * Range

Popular in futures and crypto markets.

Contains:
- DualThrustBacktest: Backtesting.py Strategy class
- DualThrustLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import ATR


class DualThrustBacktest(Strategy):
    """
    Backtesting.py implementation of Dual Thrust.
    """
    
    # Strategy parameters
    lookback = 4  # Days to calculate range
    k1 = 0.5  # Upper breakout multiplier
    k2 = 0.5  # Lower breakout multiplier
    atr_period = 14
    atr_stop_mult = 2.0
    rr_ratio = 2.0
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators."""
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        close = pd.Series(self.data.Close)
        
        self.atr = self.I(ATR, high, low, close, self.atr_period)

    def next(self):
        """Process each bar and make trading decisions."""
        if len(self.data) < self.lookback + 5:
            return
            
        close = self.data.Close[-1]
        open_price = self.data.Open[-1]
        atr = self.atr[-1]
        
        if np.isnan(atr) or atr <= 0:
            return
        
        # Calculate range from lookback period
        hh = max(self.data.High[-self.lookback:-1])  # Highest high
        hc = max(self.data.Close[-self.lookback:-1])  # Highest close
        lc = min(self.data.Close[-self.lookback:-1])  # Lowest close
        ll = min(self.data.Low[-self.lookback:-1])  # Lowest low
        
        range_val = max(hh - lc, hc - ll)
        
        # Calculate breakout levels based on today's open
        upper_break = open_price + (self.k1 * range_val)
        lower_break = open_price - (self.k2 * range_val)
        
        if self.position:
            # Exit on opposite breakout
            if self.position.is_long and close < lower_break:
                self.position.close()
            elif self.position.is_short and close > upper_break:
                self.position.close()
        else:
            if close > upper_break:
                # Long breakout
                stop_price = open_price  # Stop at open
                tp_price = close + (self.rr_ratio * (close - stop_price))
                
                risk_per_unit = close - stop_price
                if risk_per_unit > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                    self.buy(size=size_fraction, sl=stop_price, tp=tp_price)
                    
            elif close < lower_break:
                # Short breakout
                stop_price = open_price
                tp_price = close - (self.rr_ratio * (stop_price - close))
                
                risk_per_unit = stop_price - close
                if risk_per_unit > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                    self.sell(size=size_fraction, sl=stop_price, tp=tp_price)


class DualThrustLive(BaseStrategy):
    """Live trading implementation of Dual Thrust."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.lookback = config.get("lookback", 4)
        self.k1 = config.get("k1", 0.5)
        self.k2 = config.get("k2", 0.5)
        self.atr_period = config.get("atr_period", 14)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.lookback + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        high = df["high"]
        low = df["low"]
        close = df["close"]
        
        current_close = candle["close"]
        current_open = candle["open"]
        
        # Calculate range
        hh = high.iloc[-self.lookback:-1].max()
        hc = close.iloc[-self.lookback:-1].max()
        lc = close.iloc[-self.lookback:-1].min()
        ll = low.iloc[-self.lookback:-1].min()
        
        range_val = max(hh - lc, hc - ll)
        
        upper_break = current_open + (self.k1 * range_val)
        lower_break = current_open - (self.k2 * range_val)
        
        if current_close > upper_break:
            stop = current_open
            return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                 extra={"stop": stop, "reason": "dual_thrust_long"})
        elif current_close < lower_break:
            stop = current_open
            return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                 extra={"stop": stop, "reason": "dual_thrust_short"})
        
        return StrategySignal(symbol=symbol, action="HOLD")
