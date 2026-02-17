"""
VWAP Bounce Strategy.

Mean reversion to Volume Weighted Average Price:
- Long: Price bounces off VWAP from below in uptrend
- Short: Price bounces off VWAP from above in downtrend

Contains:
- VWAPBounceBacktest: Backtesting.py Strategy class
- VWAPBounceLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import VWAP, EMA, ATR


class VWAPBounceBacktest(Strategy):
    """
    Backtesting.py implementation of VWAP Bounce.
    """
    
    # Strategy parameters
    ema_period = 50  # Trend filter
    vwap_threshold = 0.002  # Price must be within 0.2% of VWAP
    atr_period = 14
    atr_stop_mult = 1.5
    rr_ratio = 2.0
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators."""
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        close = pd.Series(self.data.Close)
        volume = pd.Series(self.data.Volume)
        
        self.vwap = self.I(VWAP, high, low, close, volume)
        self.ema = self.I(EMA, close, self.ema_period)
        self.atr = self.I(ATR, high, low, close, self.atr_period)

    def next(self):
        """Process each bar and make trading decisions."""
        if len(self.data) < self.ema_period + 5:
            return
            
        close = self.data.Close[-1]
        low_price = self.data.Low[-1]
        high_price = self.data.High[-1]
        vwap_val = self.vwap[-1]
        ema_val = self.ema[-1]
        atr = self.atr[-1]
        
        if any(np.isnan([vwap_val, ema_val, atr])) or atr <= 0:
            return
        
        # Trend direction
        uptrend = close > ema_val
        downtrend = close < ema_val
        
        # Price touching VWAP
        near_vwap = abs(close - vwap_val) / vwap_val < self.vwap_threshold
        touched_vwap_from_above = low_price <= vwap_val <= high_price and close > vwap_val
        touched_vwap_from_below = low_price <= vwap_val <= high_price and close < vwap_val
        
        if self.position:
            # Exit on opposite condition or target
            pass  # Let SL/TP handle
        else:
            if uptrend and touched_vwap_from_above:
                # Bullish bounce off VWAP
                stop_price = vwap_val - (self.atr_stop_mult * atr)
                tp_price = close + (self.rr_ratio * (close - stop_price))
                
                risk_per_unit = close - stop_price
                if risk_per_unit > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                    self.buy(size=size_fraction, sl=stop_price, tp=tp_price)
                
            elif downtrend and touched_vwap_from_below:
                # Bearish rejection at VWAP
                stop_price = vwap_val + (self.atr_stop_mult * atr)
                tp_price = close - (self.rr_ratio * (stop_price - close))
                
                risk_per_unit = stop_price - close
                if risk_per_unit > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                    self.sell(size=size_fraction, sl=stop_price, tp=tp_price)


class VWAPBounceLive(BaseStrategy):
    """Live trading implementation of VWAP Bounce."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.ema_period = config.get("ema_period", 50)
        self.vwap_threshold = config.get("vwap_threshold", 0.002)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 1.5)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.ema_period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        high = df["high"]
        low = df["low"]
        close = df["close"]
        volume = df["volume"]
        
        vwap_val = VWAP(high, low, close, volume).iloc[-1]
        ema_val = EMA(close, self.ema_period).iloc[-1]
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        
        current_close = candle["close"]
        current_low = candle["low"]
        current_high = candle["high"]
        
        uptrend = current_close > ema_val
        downtrend = current_close < ema_val
        
        touched_vwap_from_above = current_low <= vwap_val <= current_high and current_close > vwap_val
        touched_vwap_from_below = current_low <= vwap_val <= current_high and current_close < vwap_val
        
        if uptrend and touched_vwap_from_above:
            stop = vwap_val - (self.atr_stop_mult * atr)
            return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                 extra={"stop": stop, "atr": atr, "reason": "vwap_bounce_long"})
        elif downtrend and touched_vwap_from_below:
            stop = vwap_val + (self.atr_stop_mult * atr)
            return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                 extra={"stop": stop, "atr": atr, "reason": "vwap_bounce_short"})
        
        return StrategySignal(symbol=symbol, action="HOLD")
