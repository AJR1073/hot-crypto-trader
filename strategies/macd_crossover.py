"""
MACD Crossover Strategy.

Trades MACD line crossing signal line:
- Long: MACD crosses above signal line
- Short: MACD crosses below signal line

Contains:
- MACDCrossoverBacktest: Backtesting.py Strategy class
- MACDCrossoverLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import MACD, ATR


class MACDCrossoverBacktest(Strategy):
    """
    Backtesting.py implementation of MACD Crossover.
    """
    
    # Strategy parameters
    fast_period = 12
    slow_period = 26
    signal_period = 9
    atr_period = 14
    atr_stop_mult = 2.0
    rr_ratio = 2.0
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators."""
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        
        macd_df = MACD(close, self.fast_period, self.slow_period, self.signal_period)
        self.macd_line = self.I(lambda x: macd_df['macd'], close)
        self.signal_line = self.I(lambda x: macd_df['signal'], close)
        self.histogram = self.I(lambda x: macd_df['histogram'], close)
        self.atr = self.I(ATR, high, low, close, self.atr_period)

    def next(self):
        """Process each bar and make trading decisions."""
        if len(self.data) < self.slow_period + self.signal_period + 5:
            return
            
        close = self.data.Close[-1]
        atr = self.atr[-1]
        
        if np.isnan(atr) or atr <= 0:
            return
        
        # Check for crossover
        macd_curr = self.macd_line[-1]
        macd_prev = self.macd_line[-2]
        signal_curr = self.signal_line[-1]
        signal_prev = self.signal_line[-2]
        
        if np.isnan(macd_curr) or np.isnan(signal_curr):
            return
        
        # Bullish crossover
        bullish_cross = (macd_prev <= signal_prev) and (macd_curr > signal_curr)
        # Bearish crossover
        bearish_cross = (macd_prev >= signal_prev) and (macd_curr < signal_curr)
        
        if self.position:
            # Exit on opposite crossover
            if self.position.is_long and bearish_cross:
                self.position.close()
            elif self.position.is_short and bullish_cross:
                self.position.close()
        else:
            if bullish_cross:
                stop_price = close - (self.atr_stop_mult * atr)
                tp_price = close + (self.rr_ratio * self.atr_stop_mult * atr)
                
                risk_per_unit = close - stop_price
                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                
                self.buy(size=size_fraction, sl=stop_price, tp=tp_price)
                
            elif bearish_cross:
                stop_price = close + (self.atr_stop_mult * atr)
                tp_price = close - (self.rr_ratio * self.atr_stop_mult * atr)
                
                risk_per_unit = stop_price - close
                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                
                self.sell(size=size_fraction, sl=stop_price, tp=tp_price)


class MACDCrossoverLive(BaseStrategy):
    """Live trading implementation of MACD Crossover."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.fast_period = config.get("fast_period", 12)
        self.slow_period = config.get("slow_period", 26)
        self.signal_period = config.get("signal_period", 9)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 2.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.slow_period + self.signal_period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        
        macd_df = MACD(close, self.fast_period, self.slow_period, self.signal_period)
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        current_close = candle["close"]
        
        macd_curr = macd_df['macd'].iloc[-1]
        macd_prev = macd_df['macd'].iloc[-2]
        signal_curr = macd_df['signal'].iloc[-1]
        signal_prev = macd_df['signal'].iloc[-2]
        
        bullish_cross = (macd_prev <= signal_prev) and (macd_curr > signal_curr)
        bearish_cross = (macd_prev >= signal_prev) and (macd_curr < signal_curr)
        
        position = state.get("position")
        
        if position:
            if position.get("side") == "LONG" and bearish_cross:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_LONG",
                                     extra={"reason": "macd_bearish_cross"})
            elif position.get("side") == "SHORT" and bullish_cross:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_SHORT",
                                     extra={"reason": "macd_bullish_cross"})
        else:
            if bullish_cross:
                stop = current_close - (self.atr_stop_mult * atr)
                state["position"] = {"side": "LONG", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                     extra={"stop": stop, "atr": atr})
            elif bearish_cross:
                stop = current_close + (self.atr_stop_mult * atr)
                state["position"] = {"side": "SHORT", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                     extra={"stop": stop, "atr": atr})
        
        return StrategySignal(symbol=symbol, action="HOLD")
