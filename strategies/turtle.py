"""
Turtle Trading Strategy.

Classic breakout system using Donchian Channels:
- Long: Price breaks above 20-day high
- Short: Price breaks below 20-day low
- Exit: 10-day opposite channel

Contains:
- TurtleBacktest: Backtesting.py Strategy class
- TurtleLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import DonchianChannel, ATR


class TurtleBacktest(Strategy):
    """
    Backtesting.py implementation of Turtle Trading.
    """
    
    # Strategy parameters
    entry_period = 20  # 20-day breakout for entry
    exit_period = 10   # 10-day breakout for exit
    atr_period = 20
    atr_stop_mult = 2.0  # N-based stop (2N)
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators."""
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        close = pd.Series(self.data.Close)
        
        entry_dc = DonchianChannel(high, low, self.entry_period)
        exit_dc = DonchianChannel(high, low, self.exit_period)
        
        self.entry_upper = self.I(lambda x: entry_dc['upper'], close)
        self.entry_lower = self.I(lambda x: entry_dc['lower'], close)
        self.exit_upper = self.I(lambda x: exit_dc['upper'], close)
        self.exit_lower = self.I(lambda x: exit_dc['lower'], close)
        self.atr = self.I(ATR, high, low, close, self.atr_period)

    def next(self):
        """Process each bar and make trading decisions."""
        if len(self.data) < self.entry_period + 5:
            return
            
        close = self.data.Close[-1]
        high_price = self.data.High[-1]
        low_price = self.data.Low[-1]
        atr = self.atr[-1]
        
        # Use previous bar's channel (don't include current)
        entry_upper = self.entry_upper[-2]
        entry_lower = self.entry_lower[-2]
        exit_upper = self.exit_upper[-2]
        exit_lower = self.exit_lower[-2]
        
        if any(np.isnan([entry_upper, entry_lower, atr])) or atr <= 0:
            return
        
        if self.position:
            # Exit rules
            if self.position.is_long and low_price < exit_lower:
                self.position.close()
            elif self.position.is_short and high_price > exit_upper:
                self.position.close()
        else:
            # Entry rules
            if high_price > entry_upper:
                # Long breakout
                stop_price = close - (self.atr_stop_mult * atr)
                
                risk_per_unit = close - stop_price
                if risk_per_unit > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                    self.buy(size=size_fraction, sl=stop_price)
                    
            elif low_price < entry_lower:
                # Short breakout
                stop_price = close + (self.atr_stop_mult * atr)
                
                risk_per_unit = stop_price - close
                if risk_per_unit > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                    self.sell(size=size_fraction, sl=stop_price)


class TurtleLive(BaseStrategy):
    """Live trading implementation of Turtle Trading."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.entry_period = config.get("entry_period", 20)
        self.exit_period = config.get("exit_period", 10)
        self.atr_period = config.get("atr_period", 20)
        self.atr_stop_mult = config.get("atr_stop_mult", 2.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.entry_period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        high = df["high"]
        low = df["low"]
        close = df["close"]
        
        current_high = candle["high"]
        current_low = candle["low"]
        current_close = candle["close"]
        
        entry_dc = DonchianChannel(high, low, self.entry_period)
        exit_dc = DonchianChannel(high, low, self.exit_period)
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        
        entry_upper = entry_dc['upper'].iloc[-2]
        entry_lower = entry_dc['lower'].iloc[-2]
        exit_upper = exit_dc['upper'].iloc[-2]
        exit_lower = exit_dc['lower'].iloc[-2]
        
        position = state.get("position")
        
        if position:
            if position.get("side") == "LONG" and current_low < exit_lower:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_LONG",
                                     extra={"reason": "turtle_exit_low"})
            elif position.get("side") == "SHORT" and current_high > exit_upper:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_SHORT",
                                     extra={"reason": "turtle_exit_high"})
        else:
            if current_high > entry_upper:
                stop = current_close - (self.atr_stop_mult * atr)
                state["position"] = {"side": "LONG", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                     extra={"stop": stop, "atr": atr})
            elif current_low < entry_lower:
                stop = current_close + (self.atr_stop_mult * atr)
                state["position"] = {"side": "SHORT", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                     extra={"stop": stop, "atr": atr})
        
        return StrategySignal(symbol=symbol, action="HOLD")
