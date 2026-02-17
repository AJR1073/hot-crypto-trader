"""
Triple Momentum V2 - Aggressive Version (TRIPLE_MOMO_V2).

Enhanced version with:
- 2-of-3 confirmation (more trades)
- Trailing take-profit at 1.5 ATR
- Reduced stop to 1.5 ATR
- Faster entries with momentum bias

Contains:
- TripleMomentumV2Backtest: Backtesting.py Strategy class
- TripleMomentumV2Live: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import RSI, MACD, Stochastic, ATR, EMA


class TripleMomentumV2Backtest(Strategy):
    """
    Aggressive Triple Momentum with 2-of-3 confirmation.
    
    Entry: 2 out of 3 indicators confirm + trend filter
    Exit: Trailing stop OR trailing take-profit
    """
    
    # Indicator parameters
    rsi_period = 14
    macd_fast = 12
    macd_slow = 26
    macd_signal = 9
    stoch_k = 14
    stoch_d = 3
    
    # Risk parameters  
    atr_period = 14
    stop_atr_mult = 1.5    # Tighter stop
    tp_atr_mult = 2.5      # Take profit target
    trail_atr_mult = 1.5   # Trailing stop after TP hit
    base_risk = 0.015      # 1.5% risk per trade

    def init(self):
        """Initialize indicators."""
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        
        # RSI
        self.rsi = self.I(RSI, close, self.rsi_period)
        
        # MACD
        macd_df = MACD(close, self.macd_fast, self.macd_slow, self.macd_signal)
        self.macd_line = self.I(lambda x: macd_df['macd'], close)
        self.macd_signal_line = self.I(lambda x: macd_df['signal'], close)
        
        # Stochastic
        stoch_df = Stochastic(high, low, close, self.stoch_k, self.stoch_d)
        self.stoch_k_line = self.I(lambda x: stoch_df['k'], close)
        self.stoch_d_line = self.I(lambda x: stoch_df['d'], close)
        
        # ATR for stops
        self.atr = self.I(ATR, high, low, close, self.atr_period)
        
        # Trend filter (20 EMA - faster)
        self.ema_20 = self.I(EMA, close, 20)
        
        # Position tracking
        self.entry_price = None
        self.highest_since_entry = None
        self.lowest_since_entry = None
        self.tp_hit = False

    def _get_signal_strength(self, direction: str) -> int:
        """Get number of confirming indicators (0-3)."""
        confirms = 0
        
        if direction == "LONG":
            # RSI bullish: rising or oversold or above 50
            if self.rsi[-1] > self.rsi[-2] or self.rsi[-1] < 35 or self.rsi[-1] > 55:
                confirms += 1
            # MACD bullish
            if self.macd_line[-1] > self.macd_signal_line[-1]:
                confirms += 1
            # Stochastic bullish
            if self.stoch_k_line[-1] > self.stoch_d_line[-1]:
                confirms += 1
                
        elif direction == "SHORT":
            # RSI bearish: falling or overbought or below 50
            if self.rsi[-1] < self.rsi[-2] or self.rsi[-1] > 65 or self.rsi[-1] < 45:
                confirms += 1
            # MACD bearish
            if self.macd_line[-1] < self.macd_signal_line[-1]:
                confirms += 1
            # Stochastic bearish
            if self.stoch_k_line[-1] < self.stoch_d_line[-1]:
                confirms += 1
        
        return confirms

    def next(self):
        """Process each bar."""
        if len(self.data) < self.macd_slow + 5:
            return
            
        close = self.data.Close[-1]
        atr = self.atr[-1]
        
        if np.isnan(atr) or atr <= 0:
            return
        
        # Trend filter
        above_ema = close > self.ema_20[-1]
        below_ema = close < self.ema_20[-1]
        
        # Handle existing position
        if self.position:
            if self.position.is_long:
                # Update highest
                if self.highest_since_entry is None or close > self.highest_since_entry:
                    self.highest_since_entry = close
                
                # Check take profit target
                if self.entry_price and close >= self.entry_price + (self.tp_atr_mult * atr):
                    self.tp_hit = True
                
                # Trailing stop (tighter after TP hit)
                trail_mult = self.trail_atr_mult if self.tp_hit else self.stop_atr_mult
                trailing_stop = self.highest_since_entry - (trail_mult * atr)
                
                if close < trailing_stop:
                    self.position.close()
                    self._reset_tracking()
                    return
                    
            elif self.position.is_short:
                if self.lowest_since_entry is None or close < self.lowest_since_entry:
                    self.lowest_since_entry = close
                
                if self.entry_price and close <= self.entry_price - (self.tp_atr_mult * atr):
                    self.tp_hit = True
                    
                trail_mult = self.trail_atr_mult if self.tp_hit else self.stop_atr_mult
                trailing_stop = self.lowest_since_entry + (trail_mult * atr)
                
                if close > trailing_stop:
                    self.position.close()
                    self._reset_tracking()
                    return
        else:
            # Look for entries - 2 of 3 confirmation
            long_strength = self._get_signal_strength("LONG")
            short_strength = self._get_signal_strength("SHORT")
            
            # Long entry
            if long_strength >= 2 and above_ema:
                leverage = 1.5 if long_strength == 2 else 2.0
                stop_price = close - (self.stop_atr_mult * atr)
                
                risk_per_unit = close - stop_price
                risk_dollars = self.equity * self.base_risk * leverage
                size_units = risk_dollars / risk_per_unit
                size_fraction = max(0.01, min(0.90, (size_units * close) / self.equity))
                
                self.buy(size=size_fraction, sl=stop_price)
                self.entry_price = close
                self.highest_since_entry = close
                self.tp_hit = False
                
            # Short entry
            elif short_strength >= 2 and below_ema:
                leverage = 1.5 if short_strength == 2 else 2.0
                stop_price = close + (self.stop_atr_mult * atr)
                
                risk_per_unit = stop_price - close
                risk_dollars = self.equity * self.base_risk * leverage
                size_units = risk_dollars / risk_per_unit
                size_fraction = max(0.01, min(0.90, (size_units * close) / self.equity))
                
                self.sell(size=size_fraction, sl=stop_price)
                self.entry_price = close
                self.lowest_since_entry = close
                self.tp_hit = False

    def _reset_tracking(self):
        """Reset position tracking."""
        self.entry_price = None
        self.highest_since_entry = None
        self.lowest_since_entry = None
        self.tp_hit = False


class TripleMomentumV2Live(BaseStrategy):
    """Live trading implementation of Triple Momentum V2."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.rsi_period = config.get("rsi_period", 14)
        self.macd_fast = config.get("macd_fast", 12)
        self.macd_slow = config.get("macd_slow", 26)
        self.macd_signal = config.get("macd_signal", 9)
        self.stoch_k = config.get("stoch_k", 14)
        self.stoch_d = config.get("stoch_d", 3)
        self.atr_period = config.get("atr_period", 14)
        self.stop_atr_mult = config.get("stop_atr_mult", 1.5)
        self.tp_atr_mult = config.get("tp_atr_mult", 2.5)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.macd_slow + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        current_close = candle["close"]
        
        # Calculate indicators
        rsi = RSI(close, self.rsi_period)
        macd_df = MACD(close, self.macd_fast, self.macd_slow, self.macd_signal)
        stoch = Stochastic(high, low, close, self.stoch_k, self.stoch_d)
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        ema_20 = EMA(close, 20).iloc[-1]
        
        # Count confirmations
        long_confirms = 0
        short_confirms = 0
        
        # RSI
        if rsi.iloc[-1] > rsi.iloc[-2] or rsi.iloc[-1] < 35 or rsi.iloc[-1] > 55:
            long_confirms += 1
        if rsi.iloc[-1] < rsi.iloc[-2] or rsi.iloc[-1] > 65 or rsi.iloc[-1] < 45:
            short_confirms += 1
            
        # MACD
        if macd_df['macd'].iloc[-1] > macd_df['signal'].iloc[-1]:
            long_confirms += 1
        else:
            short_confirms += 1
            
        # Stochastic
        if stoch['k'].iloc[-1] > stoch['d'].iloc[-1]:
            long_confirms += 1
        else:
            short_confirms += 1
        
        above_ema = current_close > ema_20
        below_ema = current_close < ema_20
        
        if long_confirms >= 2 and above_ema:
            leverage = 1.5 if long_confirms == 2 else 2.0
            stop = current_close - (self.stop_atr_mult * atr)
            tp = current_close + (self.tp_atr_mult * atr)
            return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                 extra={"stop": stop, "tp": tp, "atr": atr, 
                                       "leverage": leverage, "confirms": long_confirms})
        
        if short_confirms >= 2 and below_ema:
            leverage = 1.5 if short_confirms == 2 else 2.0
            stop = current_close + (self.stop_atr_mult * atr)
            tp = current_close - (self.tp_atr_mult * atr)
            return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                 extra={"stop": stop, "tp": tp, "atr": atr,
                                       "leverage": leverage, "confirms": short_confirms})
        
        return StrategySignal(symbol=symbol, action="HOLD")
