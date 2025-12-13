"""
Squeeze Breakout Strategy.

Detects low volatility "squeeze" conditions using Bollinger Bandwidth,
then trades breakouts in the direction of the move.

A squeeze occurs when Bollinger Bandwidth falls below a threshold,
indicating consolidation. Breakouts from squeezes often produce
strong directional moves.

Contains:
- SqueezeBreakoutBacktest: Backtesting.py Strategy class
- SqueezeBreakoutLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import SMA, STD, ATR, Bollinger, BollingerBandwidth


class SqueezeBreakoutBacktest(Strategy):
    """
    Backtesting.py implementation of Squeeze Breakout strategy.
    
    Detects volatility squeeze using Bollinger Bandwidth, then enters
    on breakout above upper band (long) or below lower band (short).
    """
    
    # Strategy parameters
    bb_period = 20
    std_dev_mult = 2.0
    bandwidth_thresh = 0.04  # Squeeze threshold
    atr_period = 14
    atr_stop_mult = 1.5
    rr_ratio = 2.0
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators."""
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        
        # Bollinger Bands
        self.bb_middle = self.I(SMA, close, self.bb_period)
        self.bb_std = self.I(STD, close, self.bb_period)
        
        # ATR for stops
        self.atr = self.I(ATR, high, low, close, self.atr_period)
        
        # Track if we were in squeeze on previous bar
        self.was_in_squeeze = False

    def next(self):
        """Process each bar and make trading decisions."""
        # Skip if not enough data
        if len(self.data) < self.bb_period + 5:
            return
            
        close = self.data.Close[-1]
        middle = self.bb_middle[-1]
        std = self.bb_std[-1]
        atr = self.atr[-1]
        
        # Skip if indicators invalid
        if np.isnan(middle) or np.isnan(std) or np.isnan(atr) or atr <= 0 or middle <= 0:
            return
            
        upper = middle + (self.std_dev_mult * std)
        lower = middle - (self.std_dev_mult * std)
        bandwidth = (upper - lower) / middle
        
        in_squeeze = bandwidth < self.bandwidth_thresh
        
        if self.position:
            # Exit on trend reversal (when bandwidth expands and price reverses)
            if self.position.is_long and close < middle:
                self.position.close()
            elif self.position.is_short and close > middle:
                self.position.close()
        else:
            # Entry only when coming out of a squeeze
            if self.was_in_squeeze or in_squeeze:
                # Long breakout: price breaks above upper band
                if close > upper:
                    risk_per_unit = atr * self.atr_stop_mult
                    stop_price = close - risk_per_unit
                    tp_price = close + (self.rr_ratio * risk_per_unit)
                    
                    # Risk-based sizing
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = (size_units * close) / self.equity
                    size_fraction = max(0.01, min(0.50, size_fraction))
                    
                    self.buy(size=size_fraction, sl=stop_price, tp=tp_price)
                    
                # Short breakout: price breaks below lower band
                elif close < lower:
                    risk_per_unit = atr * self.atr_stop_mult
                    stop_price = close + risk_per_unit
                    tp_price = close - (self.rr_ratio * risk_per_unit)
                    
                    # Risk-based sizing
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = (size_units * close) / self.equity
                    size_fraction = max(0.01, min(0.50, size_fraction))
                    
                    self.sell(size=size_fraction, sl=stop_price, tp=tp_price)
        
        self.was_in_squeeze = in_squeeze


class SqueezeBreakoutLive(BaseStrategy):
    """
    Live trading implementation of Squeeze Breakout strategy.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.bb_period = config.get("bb_period", 20)
        self.std_dev_mult = config.get("std_dev_mult", 2.0)
        self.bandwidth_thresh = config.get("bandwidth_thresh", 0.04)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 1.5)
        self.rr_ratio = config.get("rr_ratio", 2.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        # Initialize squeeze tracking
        if "was_in_squeeze" not in state:
            state["was_in_squeeze"] = False
        
        df = state.get("df")
        if df is None or len(df) < self.bb_period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        
        middle = SMA(close, self.bb_period).iloc[-1]
        std = STD(close, self.bb_period).iloc[-1]
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        
        upper = middle + (self.std_dev_mult * std)
        lower = middle - (self.std_dev_mult * std)
        bandwidth = (upper - lower) / middle if middle > 0 else 0
        
        in_squeeze = bandwidth < self.bandwidth_thresh
        current_close = candle["close"]
        position = state.get("position")
        was_in_squeeze = state.get("was_in_squeeze", False)
        
        # Update squeeze state for next bar
        state["was_in_squeeze"] = in_squeeze
        
        if position:
            # Exit logic
            if position.get("side") == "LONG" and current_close < middle:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_LONG",
                                     extra={"reason": "price_below_midline"})
            elif position.get("side") == "SHORT" and current_close > middle:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_SHORT",
                                     extra={"reason": "price_above_midline"})
        else:
            # Entry only when coming out of squeeze
            if was_in_squeeze or in_squeeze:
                if current_close > upper:
                    risk_per_unit = atr * self.atr_stop_mult
                    stop = current_close - risk_per_unit
                    tp = current_close + (self.rr_ratio * risk_per_unit)
                    state["position"] = {"side": "LONG", "entry": current_close}
                    return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                         extra={"stop": stop, "tp": tp, "squeeze": True})
                elif current_close < lower:
                    risk_per_unit = atr * self.atr_stop_mult
                    stop = current_close + risk_per_unit
                    tp = current_close - (self.rr_ratio * risk_per_unit)
                    state["position"] = {"side": "SHORT", "entry": current_close}
                    return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                         extra={"stop": stop, "tp": tp, "squeeze": True})
        
        return StrategySignal(symbol=symbol, action="HOLD")
