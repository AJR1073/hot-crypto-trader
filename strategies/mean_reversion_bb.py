"""
Mean Reversion Bollinger Bands Strategy.

Trades reversals at Bollinger Band extremes:
- Long entries below lower band (oversold)
- Short entries above upper band (overbought)
- Take profit at middle band (mean)

Contains:
- MeanReversionBBBacktest: Backtesting.py Strategy class
- MeanReversionBBLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import SMA, STD, ATR, Bollinger


class MeanReversionBBBacktest(Strategy):
    """
    Backtesting.py implementation of Bollinger Bands mean reversion.
    
    LONG: Enter when close < lower band (oversold)
    SHORT: Enter when close > upper band (overbought)
    Exit: Take profit at middle band (SMA)
    """
    
    # Strategy parameters
    sma_period = 20
    std_dev_mult = 2.0
    atr_period = 14
    atr_stop_mult = 2.0
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators."""
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        
        # Bollinger Bands
        self.bb_middle = self.I(SMA, close, self.sma_period)
        self.bb_std = self.I(STD, close, self.sma_period)
        
        # ATR for stops
        self.atr = self.I(ATR, high, low, close, self.atr_period)

    def next(self):
        """Process each bar and make trading decisions."""
        # Skip if not enough data
        if len(self.data) < self.sma_period + 5:
            return
            
        close = self.data.Close[-1]
        low_price = self.data.Low[-1]
        high_price = self.data.High[-1]
        
        middle = self.bb_middle[-1]
        std = self.bb_std[-1]
        atr = self.atr[-1]
        
        # Skip if indicators invalid
        if np.isnan(middle) or np.isnan(std) or np.isnan(atr) or atr <= 0:
            return
            
        upper = middle + (self.std_dev_mult * std)
        lower = middle - (self.std_dev_mult * std)
        
        if self.position:
            # Exit at middle band (mean reversion target)
            if self.position.is_long and close >= middle:
                self.position.close()
            elif self.position.is_short and close <= middle:
                self.position.close()
        else:
            # Long entry: price below lower band
            if close < lower:
                stop_price = close - (self.atr_stop_mult * atr)
                tp_price = middle  # TP at mean
                
                # Risk-based sizing
                risk_per_unit = close - stop_price
                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = (size_units * close) / self.equity
                size_fraction = max(0.01, min(0.50, size_fraction))
                
                self.buy(size=size_fraction, sl=stop_price, tp=tp_price)
                
            # Short entry: price above upper band
            elif close > upper:
                stop_price = close + (self.atr_stop_mult * atr)
                tp_price = middle  # TP at mean
                
                # Risk-based sizing
                risk_per_unit = stop_price - close
                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = (size_units * close) / self.equity
                size_fraction = max(0.01, min(0.50, size_fraction))
                
                self.sell(size=size_fraction, sl=stop_price, tp=tp_price)


class MeanReversionBBLive(BaseStrategy):
    """
    Live trading implementation of Bollinger Bands mean reversion.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.sma_period = config.get("sma_period", 20)
        self.std_dev_mult = config.get("std_dev_mult", 2.0)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 2.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.sma_period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        
        middle = SMA(close, self.sma_period).iloc[-1]
        std = STD(close, self.sma_period).iloc[-1]
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        
        upper = middle + (self.std_dev_mult * std)
        lower = middle - (self.std_dev_mult * std)
        
        current_close = candle["close"]
        position = state.get("position")
        
        if position:
            # Check exit at mean
            if position.get("side") == "LONG" and current_close >= middle:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_LONG", 
                                     extra={"reason": "mean_reversion_target"})
            elif position.get("side") == "SHORT" and current_close <= middle:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_SHORT",
                                     extra={"reason": "mean_reversion_target"})
        else:
            # Long entry
            if current_close < lower:
                stop = current_close - (self.atr_stop_mult * atr)
                state["position"] = {"side": "LONG", "entry": current_close, "stop": stop}
                return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                     extra={"stop": stop, "tp": middle, "atr": atr})
            # Short entry
            elif current_close > upper:
                stop = current_close + (self.atr_stop_mult * atr)
                state["position"] = {"side": "SHORT", "entry": current_close, "stop": stop}
                return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                     extra={"stop": stop, "tp": middle, "atr": atr})
        
        return StrategySignal(symbol=symbol, action="HOLD")
