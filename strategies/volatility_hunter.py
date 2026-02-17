"""
Volatility Hunter Strategy (VOL_HUNT).

Advanced mean reversion strategy for highly volatile small-cap coins:
- Extreme Bollinger Band entries (3.0 StdDev)
- RSI exhaustion confirmation
- Volume spike filter
- Dynamic volatility-based position sizing
- Multi-target take-profit system

Contains:
- VolatilityHunterBacktest: Backtesting.py Strategy class
- VolatilityHunterLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import SMA, STD, RSI, ATR, Bollinger


class VolatilityHunterBacktest(Strategy):
    """
    Backtesting.py implementation of Volatility Hunter.
    
    Entry: Extreme BB touch (3 StdDev) + RSI exhaustion + volume spike
    Sizing: Dynamic based on ATR volatility
    Exit: Multi-target TP (50% @ 1.5 ATR, 25% @ 3 ATR, trail rest)
    """
    
    # Bollinger parameters
    bb_period = 20
    bb_std = 2.5  # Aggressive bands for volatile coins
    
    # RSI parameters
    rsi_period = 14
    rsi_oversold = 35  # Aggressive oversold
    rsi_overbought = 65  # Aggressive overbought
    
    # Volume filter
    volume_period = 20
    volume_mult = 1.3  # 1.3x average volume
    
    # Risk parameters
    atr_period = 14
    stop_atr_mult = 1.5
    tp1_atr_mult = 1.5  # First target
    tp2_atr_mult = 3.0  # Second target
    trail_atr_mult = 1.0  # Trailing after TP1
    
    # Position sizing
    base_risk = 0.02  # 2% base risk
    max_risk = 0.03   # 3% max risk

    def init(self):
        """Initialize indicators."""
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        volume = pd.Series(self.data.Volume)
        
        # Bollinger Bands (3 StdDev for extremes)
        middle, upper, lower = Bollinger(close, self.bb_period, self.bb_std)
        self.bb_upper = self.I(lambda: upper)
        self.bb_lower = self.I(lambda: lower)
        self.bb_middle = self.I(lambda: middle)
        
        # RSI
        self.rsi = self.I(RSI, close, self.rsi_period)
        
        # ATR
        self.atr = self.I(ATR, high, low, close, self.atr_period)
        
        # Volume average
        self.volume_avg = self.I(SMA, volume, self.volume_period)
        
        # Position tracking
        self.entry_price = None
        self.highest_since_entry = None
        self.lowest_since_entry = None
        self.tp1_hit = False
        self.initial_size = 0

    def _is_volume_spike(self) -> bool:
        """Check if current volume is above average."""
        if np.isnan(self.volume_avg[-1]) or self.volume_avg[-1] <= 0:
            return True  # Allow if no volume data
        return self.data.Volume[-1] > self.volume_avg[-1] * self.volume_mult

    def _is_bullish_rejection(self) -> bool:
        """Check for bullish rejection candle (long lower wick)."""
        candle_range = self.data.High[-1] - self.data.Low[-1]
        if candle_range <= 0:
            return False
        lower_wick = min(self.data.Open[-1], self.data.Close[-1]) - self.data.Low[-1]
        return lower_wick / candle_range > 0.4  # 40% lower wick

    def _is_bearish_rejection(self) -> bool:
        """Check for bearish rejection candle (long upper wick)."""
        candle_range = self.data.High[-1] - self.data.Low[-1]
        if candle_range <= 0:
            return False
        upper_wick = self.data.High[-1] - max(self.data.Open[-1], self.data.Close[-1])
        return upper_wick / candle_range > 0.4

    def _get_volatility_adjusted_size(self, atr: float, price: float) -> float:
        """Calculate position size based on volatility."""
        atr_pct = (atr / price) * 100
        
        # Higher volatility = smaller position
        if atr_pct > 10:
            risk = self.base_risk * 0.5  # Half size on extreme volatility
        elif atr_pct > 5:
            risk = self.base_risk * 0.75
        else:
            risk = self.base_risk
            
        risk = min(risk, self.max_risk)
        
        stop_distance = self.stop_atr_mult * atr
        risk_dollars = self.equity * risk
        size_units = risk_dollars / stop_distance
        size_fraction = max(0.01, min(0.90, (size_units * price) / self.equity))
        
        return size_fraction

    def next(self):
        """Process each bar."""
        if len(self.data) < self.bb_period + 5:
            return
            
        close = self.data.Close[-1]
        atr = self.atr[-1]
        
        if np.isnan(atr) or atr <= 0:
            return
        
        # Handle existing position
        if self.position:
            if self.position.is_long:
                # Update highest
                if self.highest_since_entry is None or close > self.highest_since_entry:
                    self.highest_since_entry = close
                
                # Check TP1 (1.5 ATR)
                if self.entry_price and not self.tp1_hit:
                    if close >= self.entry_price + (self.tp1_atr_mult * atr):
                        self.tp1_hit = True
                        # Close 50% at TP1
                        self.position.close(0.5)
                
                # Trailing stop (tighter after TP1)
                trail_mult = self.trail_atr_mult if self.tp1_hit else self.stop_atr_mult
                trailing_stop = self.highest_since_entry - (trail_mult * atr)
                
                if close < trailing_stop:
                    self.position.close()
                    self._reset_tracking()
                    return
                
                # TP2 (3 ATR) - close 50% of remaining
                if self.tp1_hit and self.entry_price:
                    if close >= self.entry_price + (self.tp2_atr_mult * atr):
                        self.position.close(0.5)
                    
            elif self.position.is_short:
                if self.lowest_since_entry is None or close < self.lowest_since_entry:
                    self.lowest_since_entry = close
                
                if self.entry_price and not self.tp1_hit:
                    if close <= self.entry_price - (self.tp1_atr_mult * atr):
                        self.tp1_hit = True
                        self.position.close(0.5)
                
                trail_mult = self.trail_atr_mult if self.tp1_hit else self.stop_atr_mult
                trailing_stop = self.lowest_since_entry + (trail_mult * atr)
                
                if close > trailing_stop:
                    self.position.close()
                    self._reset_tracking()
                    return
                    
                if self.tp1_hit and self.entry_price:
                    if close <= self.entry_price - (self.tp2_atr_mult * atr):
                        self.position.close(0.5)
        else:
            # Look for entries
            volume_ok = self._is_volume_spike()
            
            # Long entry: price below lower BB + RSI oversold (removed rejection requirement)
            if (close <= self.bb_lower[-1] and 
                self.rsi[-1] < self.rsi_oversold and
                volume_ok):
                
                size = self._get_volatility_adjusted_size(atr, close)
                stop_price = close - (self.stop_atr_mult * atr)
                
                self.buy(size=size, sl=stop_price)
                self.entry_price = close
                self.highest_since_entry = close
                self.tp1_hit = False
                
            # Short entry: price above upper BB + RSI overbought
            elif (close >= self.bb_upper[-1] and 
                  self.rsi[-1] > self.rsi_overbought and
                  volume_ok):
                
                size = self._get_volatility_adjusted_size(atr, close)
                stop_price = close + (self.stop_atr_mult * atr)
                
                self.sell(size=size, sl=stop_price)
                self.entry_price = close
                self.lowest_since_entry = close
                self.tp1_hit = False

    def _reset_tracking(self):
        """Reset position tracking."""
        self.entry_price = None
        self.highest_since_entry = None
        self.lowest_since_entry = None
        self.tp1_hit = False


class VolatilityHunterLive(BaseStrategy):
    """Live trading implementation of Volatility Hunter."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.bb_period = config.get("bb_period", 20)
        self.bb_std = config.get("bb_std", 3.0)
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_oversold = config.get("rsi_oversold", 25)
        self.rsi_overbought = config.get("rsi_overbought", 75)
        self.atr_period = config.get("atr_period", 14)
        self.stop_atr_mult = config.get("stop_atr_mult", 1.5)
        self.volume_mult = config.get("volume_mult", 1.3)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.bb_period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        current_close = candle["close"]
        
        # Calculate indicators
        middle, upper, lower = Bollinger(close, self.bb_period, self.bb_std)
        rsi = RSI(close, self.rsi_period)
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        volume_avg = SMA(volume, 20).iloc[-1]
        
        # Check conditions
        below_lower_bb = current_close <= lower.iloc[-1]
        above_upper_bb = current_close >= upper.iloc[-1]
        rsi_oversold = rsi.iloc[-1] < self.rsi_oversold
        rsi_overbought = rsi.iloc[-1] > self.rsi_overbought
        volume_spike = candle["volume"] > volume_avg * self.volume_mult if volume_avg > 0 else True
        
        # Candle analysis
        candle_range = candle["high"] - candle["low"]
        if candle_range > 0:
            lower_wick = min(candle["open"], candle["close"]) - candle["low"]
            upper_wick = candle["high"] - max(candle["open"], candle["close"])
            bullish_rejection = lower_wick / candle_range > 0.4
            bearish_rejection = upper_wick / candle_range > 0.4
        else:
            bullish_rejection = bearish_rejection = False
        
        # Long signal
        if below_lower_bb and rsi_oversold and bullish_rejection and volume_spike:
            stop = current_close - (self.stop_atr_mult * atr)
            tp = current_close + (1.5 * atr)
            return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                 extra={"stop": stop, "tp": tp, "atr": atr,
                                       "reason": "vol_hunt_long", "rsi": rsi.iloc[-1]})
        
        # Short signal
        if above_upper_bb and rsi_overbought and bearish_rejection and volume_spike:
            stop = current_close + (self.stop_atr_mult * atr)
            tp = current_close - (1.5 * atr)
            return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                 extra={"stop": stop, "tp": tp, "atr": atr,
                                       "reason": "vol_hunt_short", "rsi": rsi.iloc[-1]})
        
        return StrategySignal(symbol=symbol, action="HOLD")
