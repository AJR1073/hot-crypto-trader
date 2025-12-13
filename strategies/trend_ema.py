"""
Trend EMA Strategy: EMA crossover trend following.

Uses EMA(20) and EMA(50) for trend direction with ATR-based
position sizing and stop/take-profit levels.

Contains:
- TrendEmaBacktest: Backtesting.py Strategy class
- TrendEmaLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

from .base import BaseStrategy, StrategySignal


def EMA(arr: pd.Series, n: int) -> pd.Series:
    """Exponential Moving Average."""
    return pd.Series(arr).ewm(span=n, adjust=False).mean()


def ATR(high: pd.Series, low: pd.Series, close: pd.Series, n: int) -> pd.Series:
    """Average True Range."""
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(n).mean()


class TrendEmaBacktest(Strategy):
    """
    Backtesting.py implementation of Trend EMA strategy.
    
    LONG-only trend following using EMA crossovers.
    
    Entry: EMA(20) > EMA(50) and close > EMA(20)
    Exit: Close position when EMA(20) < EMA(50) or stop/TP hit
    
    Position sizing based on ATR and risk per trade.
    """
    
    # Strategy parameters (can be optimized)
    ema_fast = 20
    ema_slow = 50
    atr_period = 14
    atr_stop_mult = 1.5
    rr_ratio = 2.0
    risk_per_trade = 0.01  # 1% risk per trade

    def init(self):
        """Initialize indicators."""
        close = pd.Series(self.data.Close)
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        
        # EMAs for trend direction
        self.ema_fast_line = self.I(EMA, close, self.ema_fast)
        self.ema_slow_line = self.I(EMA, close, self.ema_slow)
        
        # ATR for stops and position sizing
        self.atr = self.I(ATR, high, low, close, self.atr_period)

    def next(self):
        """Process each bar and make trading decisions."""
        # Skip if not enough data for indicators
        if len(self.data) < self.ema_slow + 5:
            return
            
        # Get current values
        close = self.data.Close[-1]
        ema_fast = self.ema_fast_line[-1]
        ema_slow = self.ema_slow_line[-1]
        atr = self.atr[-1]
        
        # Skip if indicators are invalid
        if np.isnan(atr) or atr <= 0 or np.isnan(ema_fast) or np.isnan(ema_slow):
            return
        
        # Check for existing position
        if self.position:
            # Exit on trend reversal
            if ema_fast < ema_slow:
                self.position.close()
        else:
            # Entry conditions: uptrend and price above fast EMA
            if ema_fast > ema_slow and close > ema_fast:
                # Calculate stop and take profit based on ATR
                risk_per_unit = atr * self.atr_stop_mult
                stop_price = close - risk_per_unit
                tp_price = close + (self.rr_ratio * risk_per_unit)
                
                # Use simplified position sizing: 
                # Risk-based sizing - but express as fraction of equity
                # Size = (equity * risk%) / stop_distance / price
                risk_dollars = self.equity * self.risk_per_trade
                position_size_units = risk_dollars / risk_per_unit
                position_value = position_size_units * close
                size_fraction = position_value / self.equity
                
                # Cap between 1% and 50% of equity
                size_fraction = max(0.01, min(0.50, size_fraction))
                
                # Enter long with fractional sizing, stop loss and take profit
                self.buy(size=size_fraction, sl=stop_price, tp=tp_price)


class TrendEmaLive(BaseStrategy):
    """
    Live trading implementation of Trend EMA strategy.
    
    Uses the same logic as TrendEmaBacktest but returns StrategySignal
    objects for the live trading engine.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.ema_fast = config.get("ema_fast", 20)
        self.ema_slow = config.get("ema_slow", 50)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 1.5)
        self.rr_ratio = config.get("rr_ratio", 2.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """
        Process a new candle and return a signal.

        Returns OPEN_LONG when EMA20 > EMA50 and close > EMA20.
        Returns CLOSE_LONG when EMA20 < EMA50.
        """
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        # Need DataFrame with history
        df = state.get("df")
        if df is None or len(df) < self.ema_slow + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        # Calculate indicators
        close = df["close"]
        high = df["high"]
        low = df["low"]
        
        ema_fast = EMA(close, self.ema_fast).iloc[-1]
        ema_slow = EMA(close, self.ema_slow).iloc[-1]
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        
        current_close = candle["close"]
        in_position = state.get("position") is not None
        
        if in_position:
            # Check exit
            if ema_fast < ema_slow:
                state["position"] = None
                return StrategySignal(
                    symbol=symbol,
                    action="CLOSE_LONG",
                    extra={"reason": "trend_reversal"}
                )
        else:
            # Check entry
            if ema_fast > ema_slow and current_close > ema_fast:
                stop = current_close - (atr * self.atr_stop_mult)
                tp = current_close + (self.rr_ratio * atr * self.atr_stop_mult)
                
                state["position"] = {"entry": current_close, "stop": stop, "tp": tp}
                
                return StrategySignal(
                    symbol=symbol,
                    action="OPEN_LONG",
                    extra={
                        "stop": stop,
                        "tp": tp,
                        "atr": atr,
                        "ema_fast": ema_fast,
                        "ema_slow": ema_slow,
                    }
                )
        
        return StrategySignal(symbol=symbol, action="HOLD")
