"""
RSI Divergence Strategy.

Detects bullish/bearish divergence between price and RSI:
- Bullish: Price makes lower low, RSI makes higher low
- Bearish: Price makes higher high, RSI makes lower high

Contains:
- RSIDivergenceBacktest: Backtesting.py Strategy class
- RSIDivergenceLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import RSI, ATR


class RSIDivergenceBacktest(Strategy):
    """
    Backtesting.py implementation of RSI Divergence.
    """
    
    # Strategy parameters
    rsi_period = 14
    lookback = 10  # Bars to look back for divergence
    rsi_oversold = 30
    rsi_overbought = 70
    atr_period = 14
    atr_stop_mult = 2.0
    rr_ratio = 2.0
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators."""
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        
        self.rsi = self.I(RSI, close, self.rsi_period)
        self.atr = self.I(ATR, high, low, close, self.atr_period)

    def next(self):
        """Process each bar and make trading decisions."""
        if len(self.data) < self.lookback + self.rsi_period + 5:
            return
            
        close = self.data.Close[-1]
        atr = self.atr[-1]
        
        if np.isnan(atr) or atr <= 0:
            return
        
        # Check for divergence
        bullish_div = self._check_bullish_divergence()
        bearish_div = self._check_bearish_divergence()
        
        if self.position:
            # Let stop/TP handle exits
            pass
        else:
            if bullish_div and self.rsi[-1] < self.rsi_oversold + 10:
                # Bullish divergence entry
                stop_price = close - (self.atr_stop_mult * atr)
                tp_price = close + (self.rr_ratio * self.atr_stop_mult * atr)
                
                risk_per_unit = close - stop_price
                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                
                self.buy(size=size_fraction, sl=stop_price, tp=tp_price)
                
            elif bearish_div and self.rsi[-1] > self.rsi_overbought - 10:
                # Bearish divergence entry
                stop_price = close + (self.atr_stop_mult * atr)
                tp_price = close - (self.rr_ratio * self.atr_stop_mult * atr)
                
                risk_per_unit = stop_price - close
                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                
                self.sell(size=size_fraction, sl=stop_price, tp=tp_price)
    
    def _check_bullish_divergence(self) -> bool:
        """Price lower low, RSI higher low."""
        prices = list(self.data.Low[-self.lookback:])
        rsi_vals = list(self.rsi[-self.lookback:])
        
        if len(prices) < self.lookback or any(np.isnan(rsi_vals)):
            return False
        
        # Find local lows
        price_low_idx = np.argmin(prices)
        
        # Check if recent low is lower than previous and RSI is higher
        if price_low_idx > 0 and price_low_idx < len(prices) - 1:
            prev_price_low = min(prices[:price_low_idx])
            curr_price_low = prices[price_low_idx]
            
            if curr_price_low < prev_price_low:
                # Price made lower low
                prev_rsi_at_low = min(rsi_vals[:price_low_idx]) if price_low_idx > 0 else rsi_vals[0]
                curr_rsi = rsi_vals[price_low_idx]
                
                if curr_rsi > prev_rsi_at_low:
                    return True
        return False
    
    def _check_bearish_divergence(self) -> bool:
        """Price higher high, RSI lower high."""
        prices = list(self.data.High[-self.lookback:])
        rsi_vals = list(self.rsi[-self.lookback:])
        
        if len(prices) < self.lookback or any(np.isnan(rsi_vals)):
            return False
        
        price_high_idx = np.argmax(prices)
        
        if price_high_idx > 0 and price_high_idx < len(prices) - 1:
            prev_price_high = max(prices[:price_high_idx])
            curr_price_high = prices[price_high_idx]
            
            if curr_price_high > prev_price_high:
                prev_rsi_at_high = max(rsi_vals[:price_high_idx]) if price_high_idx > 0 else rsi_vals[0]
                curr_rsi = rsi_vals[price_high_idx]
                
                if curr_rsi < prev_rsi_at_high:
                    return True
        return False


class RSIDivergenceLive(BaseStrategy):
    """Live trading implementation of RSI Divergence."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.rsi_period = config.get("rsi_period", 14)
        self.lookback = config.get("lookback", 10)
        self.rsi_oversold = config.get("rsi_oversold", 30)
        self.rsi_overbought = config.get("rsi_overbought", 70)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 2.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.lookback + self.rsi_period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        
        rsi = RSI(close, self.rsi_period)
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        current_close = candle["close"]
        
        # Simple divergence check (simplified for live)
        recent_rsi = rsi.iloc[-self.lookback:]
        recent_low = low.iloc[-self.lookback:]
        recent_high = high.iloc[-self.lookback:]
        
        # Bullish: price new low, RSI not new low
        if recent_low.iloc[-1] == recent_low.min() and recent_rsi.iloc[-1] > recent_rsi.min():
            if rsi.iloc[-1] < self.rsi_oversold + 10:
                stop = current_close - (self.atr_stop_mult * atr)
                return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                     extra={"stop": stop, "atr": atr, "reason": "bullish_divergence"})
        
        # Bearish: price new high, RSI not new high
        if recent_high.iloc[-1] == recent_high.max() and recent_rsi.iloc[-1] < recent_rsi.max():
            if rsi.iloc[-1] > self.rsi_overbought - 10:
                stop = current_close + (self.atr_stop_mult * atr)
                return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                     extra={"stop": stop, "atr": atr, "reason": "bearish_divergence"})
        
        return StrategySignal(symbol=symbol, action="HOLD")
