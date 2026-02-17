"""
Rubber Band Strategy: Mean Reversion with RSI Filter.

From Deep Research — the enhanced mean-reversion strategy:
- Bollinger Bands (2.5σ) for extreme levels
- RSI(14) confirmation (oversold < 30 / overbought > 70)
- Take profit at middle band (mean)
- Wider entry threshold than basic MR_BB (2.5σ vs 2.0σ)

Active when: Hurst < 0.45 (mean-reverting market), but runs standalone too.

Contains:
- RubberBandBacktest: Backtesting.py Strategy class
- RubberBandLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import SMA, STD, ATR, RSI


class RubberBandBacktest(Strategy):
    """
    Backtesting.py implementation of the Rubber Band strategy.

    Entry (LONG):
        - Close < Lower BB (2.5σ oversold)
        - RSI < rsi_oversold (confirms exhaustion)
    Entry (SHORT):
        - Close > Upper BB (2.5σ overbought)
        - RSI > rsi_overbought (confirms exhaustion)
    Exit:
        - Take profit at middle band (SMA)
        - Stop loss via ATR
    """

    # Strategy parameters
    sma_period = 20
    std_dev_mult = 2.5       # Wider bands = fewer, better entries
    rsi_period = 14
    rsi_oversold = 30
    rsi_overbought = 70
    atr_period = 14
    atr_stop_mult = 2.0
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators using numpy inline (safe for backtesting.py)."""
        close = np.array(self.data.Close, dtype=float)
        high = np.array(self.data.High, dtype=float)
        low = np.array(self.data.Low, dtype=float)

        # Bollinger Bands
        close_s = pd.Series(close)
        sma = close_s.rolling(self.sma_period).mean().values
        std = close_s.rolling(self.sma_period).std().values

        # RSI
        rsi = RSI(close_s, self.rsi_period).values

        # ATR
        atr = ATR(pd.Series(high), pd.Series(low), close_s, self.atr_period).values

        # Register
        self.bb_middle = self.I(lambda: sma, name='BB_Middle', overlay=True)
        self.bb_std = self.I(lambda: std, name='BB_Std', overlay=False)
        self.rsi_line = self.I(lambda: rsi, name='RSI', overlay=False)
        self.atr = self.I(lambda: atr, name='ATR', overlay=False)

    def next(self):
        """Process each bar."""
        if len(self.data) < self.sma_period + 10:
            return

        close = self.data.Close[-1]
        middle = self.bb_middle[-1]
        std = self.bb_std[-1]
        rsi_val = self.rsi_line[-1]
        atr_val = self.atr[-1]

        if np.isnan(middle) or np.isnan(std) or np.isnan(rsi_val) or np.isnan(atr_val):
            return
        if atr_val <= 0 or std <= 0:
            return

        upper = middle + (self.std_dev_mult * std)
        lower = middle - (self.std_dev_mult * std)

        if self.position:
            # Exit at middle band (mean reversion target)
            if self.position.is_long and close >= middle:
                self.position.close()
            elif self.position.is_short and close <= middle:
                self.position.close()
        else:
            # LONG: price below lower band + RSI oversold
            if close < lower and rsi_val < self.rsi_oversold:
                stop_price = close - (self.atr_stop_mult * atr_val)
                tp_price = middle  # TP at mean

                risk_per_unit = close - stop_price
                if risk_per_unit <= 0:
                    return
                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = (size_units * close) / self.equity
                size_fraction = max(0.01, min(0.50, size_fraction))

                self.buy(size=size_fraction, sl=stop_price, tp=tp_price)

            # SHORT: price above upper band + RSI overbought
            elif close > upper and rsi_val > self.rsi_overbought:
                stop_price = close + (self.atr_stop_mult * atr_val)
                tp_price = middle  # TP at mean

                risk_per_unit = stop_price - close
                if risk_per_unit <= 0:
                    return
                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = (size_units * close) / self.equity
                size_fraction = max(0.01, min(0.50, size_fraction))

                self.sell(size=size_fraction, sl=stop_price, tp=tp_price)


class RubberBandLive(BaseStrategy):
    """Live trading implementation of the Rubber Band strategy."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.sma_period = config.get("sma_period", 20)
        self.std_dev_mult = config.get("std_dev_mult", 2.5)
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_oversold = config.get("rsi_oversold", 30)
        self.rsi_overbought = config.get("rsi_overbought", 70)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 2.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]

        df = state.get("df")
        if df is None or len(df) < self.sma_period + 10:
            return StrategySignal(symbol=symbol, action="HOLD")

        close = df["close"]
        high = df["high"]
        low = df["low"]

        middle = SMA(close, self.sma_period).iloc[-1]
        std = STD(close, self.sma_period).iloc[-1]
        rsi_val = RSI(close, self.rsi_period).iloc[-1]
        atr_val = ATR(high, low, close, self.atr_period).iloc[-1]

        upper = middle + (self.std_dev_mult * std)
        lower = middle - (self.std_dev_mult * std)

        current_close = candle["close"]
        position = state.get("position")

        if position:
            if position.get("side") == "LONG" and current_close >= middle:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_LONG",
                                     extra={"reason": "mean_reversion_target"})
            elif position.get("side") == "SHORT" and current_close <= middle:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_SHORT",
                                     extra={"reason": "mean_reversion_target"})
        else:
            if current_close < lower and rsi_val < self.rsi_oversold:
                stop = current_close - (self.atr_stop_mult * atr_val)
                state["position"] = {"side": "LONG", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                     extra={"stop": stop, "tp": middle,
                                            "rsi": rsi_val, "atr": atr_val})

            elif current_close > upper and rsi_val > self.rsi_overbought:
                stop = current_close + (self.atr_stop_mult * atr_val)
                state["position"] = {"side": "SHORT", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                     extra={"stop": stop, "tp": middle,
                                            "rsi": rsi_val, "atr": atr_val})

        return StrategySignal(symbol=symbol, action="HOLD")
