"""
Triple Momentum Leveraged Strategy (TRIPLE_MOMO).

Advanced strategy combining RSI, MACD, and Stochastic with:
- Triple confirmation for high-conviction entries
- Conviction-based position sizing (1x-3x leverage simulation)
- Pyramid entries for adding to winners
- Trailing stop exits

Contains:
- TripleMomentumBacktest: Backtesting.py Strategy class
- TripleMomentumLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import RSI, MACD, Stochastic, ATR, EMA


class TripleMomentumBacktest(Strategy):
    """
    Backtesting.py implementation of Triple Momentum Leveraged.
    
    Entry: RSI + MACD + Stochastic all confirm direction
    Sizing: Based on conviction (1/2/3 indicators agreeing)
    Exit: Trailing stop or opposite signal
    """
    
    # Indicator parameters
    rsi_period = 14
    rsi_oversold = 30
    rsi_overbought = 70
    macd_fast = 12
    macd_slow = 26
    macd_signal = 9
    stoch_k = 14
    stoch_d = 3
    stoch_oversold = 20
    stoch_overbought = 80
    
    # Risk parameters
    atr_period = 14
    trailing_atr_mult = 2.0
    base_risk = 0.01  # Base risk per trade (1%)
    max_leverage = 2.0  # Max position size multiplier

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
        self.stoch_k = self.I(lambda x: stoch_df['k'], close)
        self.stoch_d_line = self.I(lambda x: stoch_df['d'], close)
        
        # ATR for stops
        self.atr = self.I(ATR, high, low, close, self.atr_period)
        
        # Trend filter (50 EMA)
        self.ema_50 = self.I(EMA, close, 50)
        
        # Trailing stop tracking
        self.highest_since_entry = None
        self.lowest_since_entry = None

    def _count_confirmations(self, direction: str) -> int:
        """Count how many indicators confirm the direction."""
        confirmations = 0
        
        if direction == "LONG":
            # RSI: rising or oversold
            if self.rsi[-1] < 40 or (self.rsi[-1] > self.rsi[-2] and self.rsi[-1] > 40):
                confirmations += 1
            
            # MACD: bullish
            if self.macd_line[-1] > self.macd_signal_line[-1]:
                confirmations += 1
            
            # Stochastic: bullish crossover or rising from oversold
            if self.stoch_k[-1] > self.stoch_d_line[-1]:
                confirmations += 1
                    
        elif direction == "SHORT":
            # RSI: falling or overbought
            if self.rsi[-1] > 60 or (self.rsi[-1] < self.rsi[-2] and self.rsi[-1] < 60):
                confirmations += 1
            
            # MACD: bearish
            if self.macd_line[-1] < self.macd_signal_line[-1]:
                confirmations += 1
            
            # Stochastic: bearish crossover or falling from overbought
            if self.stoch_k[-1] < self.stoch_d_line[-1]:
                confirmations += 1
        
        return confirmations

    def _get_leverage_mult(self, confirmations: int) -> float:
        """Get leverage multiplier based on confirmations."""
        if confirmations >= 3:
            return 2.0
        elif confirmations >= 2:
            return 1.5
        elif confirmations >= 1:
            return 1.0
        return 0.0

    def next(self):
        """Process each bar."""
        if len(self.data) < max(self.macd_slow, 50) + 5:
            return
            
        close = self.data.Close[-1]
        atr = self.atr[-1]
        
        if np.isnan(atr) or atr <= 0:
            return
        
        # Trend filter
        above_ema = close > self.ema_50[-1]
        below_ema = close < self.ema_50[-1]
        
        # Handle existing position
        if self.position:
            # Update trailing stop tracking
            if self.position.is_long:
                if self.highest_since_entry is None or close > self.highest_since_entry:
                    self.highest_since_entry = close
                
                # Check trailing stop
                trailing_stop = self.highest_since_entry - (self.trailing_atr_mult * atr)
                if close < trailing_stop:
                    self.position.close()
                    self.highest_since_entry = None
                    return
                
                # Check for opposite signal
                short_confirms = self._count_confirmations("SHORT")
                if short_confirms >= 2 and below_ema:
                    self.position.close()
                    self.highest_since_entry = None
                    
            elif self.position.is_short:
                if self.lowest_since_entry is None or close < self.lowest_since_entry:
                    self.lowest_since_entry = close
                
                trailing_stop = self.lowest_since_entry + (self.trailing_atr_mult * atr)
                if close > trailing_stop:
                    self.position.close()
                    self.lowest_since_entry = None
                    return
                
                long_confirms = self._count_confirmations("LONG")
                if long_confirms >= 2 and above_ema:
                    self.position.close()
                    self.lowest_since_entry = None
        else:
            # Look for new entries
            long_confirms = self._count_confirmations("LONG")
            short_confirms = self._count_confirmations("SHORT")
            
            # Long entry with trend filter
            if long_confirms >= 2 and above_ema:
                leverage = self._get_leverage_mult(long_confirms)
                stop_price = close - (self.trailing_atr_mult * atr)
                
                risk_per_unit = close - stop_price
                risk_dollars = self.equity * self.base_risk * leverage
                size_units = risk_dollars / risk_per_unit
                size_fraction = max(0.01, min(0.80, (size_units * close) / self.equity))
                
                self.buy(size=size_fraction, sl=stop_price)
                self.highest_since_entry = close
                
            # Short entry with trend filter
            elif short_confirms >= 2 and below_ema:
                leverage = self._get_leverage_mult(short_confirms)
                stop_price = close + (self.trailing_atr_mult * atr)
                
                risk_per_unit = stop_price - close
                risk_dollars = self.equity * self.base_risk * leverage
                size_units = risk_dollars / risk_per_unit
                size_fraction = max(0.01, min(0.80, (size_units * close) / self.equity))
                
                self.sell(size=size_fraction, sl=stop_price)
                self.lowest_since_entry = close


class TripleMomentumLive(BaseStrategy):
    """Live trading implementation of Triple Momentum Leveraged."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.rsi_period = config.get("rsi_period", 14)
        self.macd_fast = config.get("macd_fast", 12)
        self.macd_slow = config.get("macd_slow", 26)
        self.macd_signal = config.get("macd_signal", 9)
        self.stoch_k = config.get("stoch_k", 14)
        self.stoch_d = config.get("stoch_d", 3)
        self.atr_period = config.get("atr_period", 14)
        self.trailing_atr_mult = config.get("trailing_atr_mult", 2.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < max(self.macd_slow, 50) + 5:
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
        ema_50 = EMA(close, 50).iloc[-1]
        
        # Count confirmations
        confirmations = 0
        direction = None
        
        # Check for long signals
        rsi_bull = rsi.iloc[-2] < 40 and rsi.iloc[-1] > rsi.iloc[-2]
        macd_bull = macd_df['macd'].iloc[-1] > macd_df['signal'].iloc[-1]
        stoch_bull = stoch['k'].iloc[-1] > stoch['d'].iloc[-1] and stoch['k'].iloc[-1] < 50
        
        if rsi_bull: confirmations += 1
        if macd_bull: confirmations += 1
        if stoch_bull: confirmations += 1
        
        above_ema = current_close > ema_50
        below_ema = current_close < ema_50
        
        if confirmations >= 2 and above_ema:
            leverage = 1.5 if confirmations >= 2 else 1.0
            if confirmations >= 3: leverage = 2.0
            
            stop = current_close - (self.trailing_atr_mult * atr)
            return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                 extra={"stop": stop, "atr": atr, "leverage": leverage,
                                       "confirmations": confirmations, "reason": "triple_momo_long"})
        
        # Check for short signals
        confirmations = 0
        rsi_bear = rsi.iloc[-2] > 60 and rsi.iloc[-1] < rsi.iloc[-2]
        macd_bear = macd_df['macd'].iloc[-1] < macd_df['signal'].iloc[-1]
        stoch_bear = stoch['k'].iloc[-1] < stoch['d'].iloc[-1] and stoch['k'].iloc[-1] > 50
        
        if rsi_bear: confirmations += 1
        if macd_bear: confirmations += 1
        if stoch_bear: confirmations += 1
        
        if confirmations >= 2 and below_ema:
            leverage = 1.5 if confirmations >= 2 else 1.0
            if confirmations >= 3: leverage = 2.0
            
            stop = current_close + (self.trailing_atr_mult * atr)
            return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                 extra={"stop": stop, "atr": atr, "leverage": leverage,
                                       "confirmations": confirmations, "reason": "triple_momo_short"})
        
        return StrategySignal(symbol=symbol, action="HOLD")
