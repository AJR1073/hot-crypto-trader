"""
Ichimoku Cloud Strategy.

Uses the Ichimoku Kinko Hyo indicator:
- Long: Price above cloud, Tenkan > Kijun
- Short: Price below cloud, Tenkan < Kijun

Contains:
- IchimokuBacktest: Backtesting.py Strategy class
- IchimokuLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import Ichimoku, ATR


class IchimokuBacktest(Strategy):
    """
    Backtesting.py implementation of Ichimoku Cloud.
    """
    
    # Strategy parameters
    tenkan_period = 9
    kijun_period = 26
    senkou_b_period = 52
    atr_period = 14
    atr_stop_mult = 2.0
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators."""
        high = pd.Series(self.data.High)
        low = pd.Series(self.data.Low)
        close = pd.Series(self.data.Close)
        
        ichi = Ichimoku(high, low, close, self.tenkan_period, self.kijun_period, self.senkou_b_period)
        
        self.tenkan = self.I(lambda x: ichi['tenkan_sen'], close)
        self.kijun = self.I(lambda x: ichi['kijun_sen'], close)
        self.senkou_a = self.I(lambda x: ichi['senkou_a'], close)
        self.senkou_b = self.I(lambda x: ichi['senkou_b'], close)
        self.atr = self.I(ATR, high, low, close, self.atr_period)

    def next(self):
        """Process each bar and make trading decisions."""
        if len(self.data) < self.senkou_b_period + self.kijun_period + 5:
            return
            
        close = self.data.Close[-1]
        atr = self.atr[-1]
        tenkan = self.tenkan[-1]
        kijun = self.kijun[-1]
        senkou_a = self.senkou_a[-1]
        senkou_b = self.senkou_b[-1]
        
        if any(np.isnan([atr, tenkan, kijun])) or atr <= 0:
            return
        
        # Determine cloud boundaries
        cloud_top = max(senkou_a, senkou_b) if not np.isnan(senkou_a) and not np.isnan(senkou_b) else np.nan
        cloud_bottom = min(senkou_a, senkou_b) if not np.isnan(senkou_a) and not np.isnan(senkou_b) else np.nan
        
        if np.isnan(cloud_top):
            return
        
        # Check conditions
        above_cloud = close > cloud_top
        below_cloud = close < cloud_bottom
        tenkan_above_kijun = tenkan > kijun
        tenkan_below_kijun = tenkan < kijun
        
        # TK Cross
        tk_cross_bull = self.tenkan[-2] <= self.kijun[-2] and tenkan > kijun
        tk_cross_bear = self.tenkan[-2] >= self.kijun[-2] and tenkan < kijun
        
        if self.position:
            # Exit on opposite conditions
            if self.position.is_long and (below_cloud or tk_cross_bear):
                self.position.close()
            elif self.position.is_short and (above_cloud or tk_cross_bull):
                self.position.close()
        else:
            if above_cloud and tk_cross_bull:
                stop_price = kijun - (0.5 * atr)  # Use Kijun as dynamic support
                tp_price = close + (2 * (close - stop_price))
                
                risk_per_unit = close - stop_price
                if risk_per_unit > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                    self.buy(size=size_fraction, sl=stop_price, tp=tp_price)
                
            elif below_cloud and tk_cross_bear:
                stop_price = kijun + (0.5 * atr)
                tp_price = close - (2 * (stop_price - close))
                
                risk_per_unit = stop_price - close
                if risk_per_unit > 0:
                    risk_dollars = self.equity * self.risk_per_trade
                    size_units = risk_dollars / risk_per_unit
                    size_fraction = max(0.01, min(0.50, (size_units * close) / self.equity))
                    self.sell(size=size_fraction, sl=stop_price, tp=tp_price)


class IchimokuLive(BaseStrategy):
    """Live trading implementation of Ichimoku Cloud."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.tenkan_period = config.get("tenkan_period", 9)
        self.kijun_period = config.get("kijun_period", 26)
        self.senkou_b_period = config.get("senkou_b_period", 52)
        self.atr_period = config.get("atr_period", 14)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]
        
        df = state.get("df")
        if df is None or len(df) < self.senkou_b_period + self.kijun_period + 5:
            return StrategySignal(symbol=symbol, action="HOLD")
        
        high = df["high"]
        low = df["low"]
        close = df["close"]
        current_close = candle["close"]
        
        ichi = Ichimoku(high, low, close, self.tenkan_period, self.kijun_period, self.senkou_b_period)
        atr = ATR(high, low, close, self.atr_period).iloc[-1]
        
        tenkan = ichi['tenkan_sen'].iloc[-1]
        kijun = ichi['kijun_sen'].iloc[-1]
        senkou_a = ichi['senkou_a'].iloc[-1]
        senkou_b = ichi['senkou_b'].iloc[-1]
        
        if any(pd.isna([tenkan, kijun, senkou_a, senkou_b])):
            return StrategySignal(symbol=symbol, action="HOLD")
        
        cloud_top = max(senkou_a, senkou_b)
        cloud_bottom = min(senkou_a, senkou_b)
        
        above_cloud = current_close > cloud_top
        below_cloud = current_close < cloud_bottom
        
        tenkan_prev = ichi['tenkan_sen'].iloc[-2]
        kijun_prev = ichi['kijun_sen'].iloc[-2]
        tk_cross_bull = tenkan_prev <= kijun_prev and tenkan > kijun
        tk_cross_bear = tenkan_prev >= kijun_prev and tenkan < kijun
        
        position = state.get("position")
        
        if position:
            if position.get("side") == "LONG" and (below_cloud or tk_cross_bear):
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_LONG",
                                     extra={"reason": "ichimoku_exit"})
            elif position.get("side") == "SHORT" and (above_cloud or tk_cross_bull):
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_SHORT",
                                     extra={"reason": "ichimoku_exit"})
        else:
            if above_cloud and tk_cross_bull:
                stop = kijun - (0.5 * atr)
                state["position"] = {"side": "LONG", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                     extra={"stop": stop, "atr": atr})
            elif below_cloud and tk_cross_bear:
                stop = kijun + (0.5 * atr)
                state["position"] = {"side": "SHORT", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                     extra={"stop": stop, "atr": atr})
        
        return StrategySignal(symbol=symbol, action="HOLD")
