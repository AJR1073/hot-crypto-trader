"""
SuperTrend Strategy: Trend following using ATR-based trailing stop.

Strategy:
- Enter LONG when Close > SuperTrend (Trend becomes Bullish).
- Enter SHORT when Close < SuperTrend (Trend becomes Bearish).
- Exit: Trend reversal acting as trailing stop.
"""

from backtesting import Strategy
import pandas as pd
import numpy as np

from .base import BaseStrategy, StrategySignal
from .indicators import SuperTrend, ATR


class SuperTrendBacktest(Strategy):
    """
    SuperTrend Strategy for Backtesting.py.
    """
    
    # Parameters
    period = 10
    multiplier = 2.0
    risk_per_trade = 0.01  # 1% risk per trade
    
    def init(self):
        """Initialize indicators."""
        high = np.array(self.data.High, dtype=float)
        low = np.array(self.data.Low, dtype=float)
        close = np.array(self.data.Close, dtype=float)
        
        # Compute ATR manually (numpy)
        tr = np.empty(len(close))
        tr[0] = high[0] - low[0]
        for i in range(1, len(close)):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
        
        atr = np.full(len(close), np.nan)
        if len(close) >= self.period:
            atr[self.period - 1] = np.mean(tr[:self.period])
            for i in range(self.period, len(close)):
                atr[i] = (atr[i-1] * (self.period - 1) + tr[i]) / self.period
        
        # Compute SuperTrend
        hl2 = (high + low) / 2
        basic_upper = hl2 + self.multiplier * atr
        basic_lower = hl2 - self.multiplier * atr
        
        supertrend_arr = np.full(len(close), np.nan)
        trend_arr = np.full(len(close), np.nan)
        
        final_upper = 0.0
        final_lower = 0.0
        trend_val = 1
        
        for i in range(len(close)):
            if np.isnan(basic_upper[i]):
                continue
                
            if i == 0 or np.isnan(supertrend_arr[i-1]):
                final_upper = basic_upper[i]
                final_lower = basic_lower[i]
                trend_val = 1
            else:
                if basic_upper[i] < final_upper or close[i-1] > final_upper:
                    final_upper = basic_upper[i]
                if basic_lower[i] > final_lower or close[i-1] < final_lower:
                    final_lower = basic_lower[i]
                    
                if trend_val == 1 and close[i] < final_lower:
                    trend_val = -1
                elif trend_val == -1 and close[i] > final_upper:
                    trend_val = 1
            
            supertrend_arr[i] = final_lower if trend_val == 1 else final_upper
            trend_arr[i] = float(trend_val)
        
        # Register with backtesting.py
        self.supertrend = self.I(lambda: supertrend_arr, name='SuperTrend', overlay=True)
        self.trend = self.I(lambda: trend_arr, name='Trend', overlay=False)
        
    def next(self):
        """Process each bar."""
        # Skip if indicators not ready
        if len(self.data) < self.period + 2:
            return

        current_trend = self.trend[-1]
        prev_trend = self.trend[-2]
        current_close = self.data.Close[-1]
        st_value = self.supertrend[-1]
        
        # Skip if NaN (self.I wraps can produce NaN)
        if np.isnan(current_trend) or np.isnan(prev_trend) or np.isnan(st_value):
            return
        
        # Check for Trend Reversal (Entry Signals)
        # Compare with < 0 / > 0 instead of == -1 / == 1 (float safety)
        
        # Bullish Reversal (Bear -> Bull)
        if prev_trend < 0 and current_trend > 0:
            if self.position.is_short:
                self.position.close()
            
            if not self.position:
                risk_per_share = abs(current_close - st_value)
                if risk_per_share > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_share
                    size_fraction = max(0.01, min(0.50, (size_units * current_close) / self.equity))
                    self.buy(size=size_fraction, sl=st_value)
        
        # Bearish Reversal (Bull -> Bear)
        elif prev_trend > 0 and current_trend < 0:
            if self.position.is_long:
                self.position.close()
                
            if not self.position:
                risk_per_share = abs(current_close - st_value)
                if risk_per_share > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_share
                    size_fraction = max(0.01, min(0.50, (size_units * current_close) / self.equity))
                    self.sell(size=size_fraction, sl=st_value)
        
        # Update trailing stop for existing position
        if self.position.is_long and current_trend > 0:
            self.position.sl = st_value
            
        elif self.position.is_short and current_trend < 0:
            self.position.sl = st_value


class SuperTrendLive(BaseStrategy):
    """
    Live trading implementation of SuperTrend strategy.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.period = config.get("period", 10)
        self.multiplier = config.get("multiplier", 3.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        # Calculate SuperTrend
        st_df = SuperTrend(df["high"], df["low"], df["close"], self.period, self.multiplier)
        
        current_trend = st_df["Trend"].iloc[-1]
        prev_trend = st_df["Trend"].iloc[-2]
        st_value = st_df["SuperTrend"].iloc[-1]
        
        current_close = candle["close"]
        position = state.get("position")
        
        # Trend Reversal Logic
        
        # Bullish Reversal (Bear -> Bull)
        if prev_trend == -1 and current_trend == 1:
            if position:
                if position.get("side") == "SHORT":
                    state["position"] = None
                    # Close Short AND Open Long (Flip)
                    # For simplicity, live runner usually handles one action per bar.
                    # We'll return CLOSE_SHORT and assume next bar (or logic) handles entry?
                    # Or simpler: Just return OPEN_LONG which implies closing short in some systems.
                    # In our system: return CLOSE_SHORT, then next cycle will see Bull trend and enter?
                    # Actually, better to just signal OPEN_LONG and let execution handle flipping.
                    # But our RiskManager might block new trade if short exists.
                    # Let's check position side.
                    return StrategySignal(symbol=symbol, action="CLOSE_SHORT", 
                                         extra={"reason": "trend_reversal_bullish"})
            
            # If no position, enter LONG
            risk_dist = abs(current_close - st_value)
            tp = current_close + (risk_dist * 3) # Optional 3R TP
            state["position"] = {"side": "LONG", "entry": current_close}
            return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                 extra={"stop": st_value, "tp": tp, "strategy": "SuperTrend"})

        # Bearish Reversal (Bull -> Bear)
        elif prev_trend == 1 and current_trend == -1:
            if position:
                if position.get("side") == "LONG":
                    state["position"] = None
                    return StrategySignal(symbol=symbol, action="CLOSE_LONG",
                                         extra={"reason": "trend_reversal_bearish"})
            
            # If no position, enter SHORT
            risk_dist = abs(current_close - st_value)
            tp = current_close - (risk_dist * 3)
            state["position"] = {"side": "SHORT", "entry": current_close}
            return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                 extra={"stop": st_value, "tp": tp, "strategy": "SuperTrend"})
            
        # Update trailing stop for existing position
        if position:
            if position.get("side") == "LONG" and current_trend == 1:
                # We could emit a fake "UPDATE" signal but our system doesn't support order mods yet.
                # Just HOLD.
                pass
            elif position.get("side") == "SHORT" and current_trend == -1:
                pass
                
        return StrategySignal(symbol=symbol, action="HOLD")
