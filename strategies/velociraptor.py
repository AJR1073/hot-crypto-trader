"""
Velociraptor Strategy: Volatility-Adjusted Trend Following.

From Deep Research — the "aggressive trend-following" strategy:
- EMA(20/50) crossover for trend direction
- ADX > 25 filter (only trade in strong trends)
- VWAP confirmation (price above/below VWAP)
- ATR-based volatility-adjusted position sizing

Active when: Hurst > 0.55 (trending market), but runs standalone too.

Contains:
- VelociraptorBacktest: Backtesting.py Strategy class
- VelociraptorLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import EMA, ATR, ADX, VWAP


class VelociraptorBacktest(Strategy):
    """
    Backtesting.py implementation of the Velociraptor strategy.

    Entry (LONG):
        - EMA(20) > EMA(50) (bullish crossover/trend)
        - ADX > adx_threshold (strong trend)
        - Close > VWAP (buying above value)
    Entry (SHORT):
        - EMA(20) < EMA(50) (bearish)
        - ADX > adx_threshold
        - Close < VWAP (selling below value)
    Exit:
        - Trend reversal (EMA cross back) or trailing stop
    """

    # Strategy parameters
    ema_fast = 20
    ema_slow = 50
    adx_period = 14
    adx_threshold = 25
    atr_period = 14
    atr_stop_mult = 2.0
    rr_ratio = 2.5          # Wider R:R for trend trades
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators using numpy inline (safe for backtesting.py)."""
        close = np.array(self.data.Close, dtype=float)
        high = np.array(self.data.High, dtype=float)
        low = np.array(self.data.Low, dtype=float)
        volume = np.array(self.data.Volume, dtype=float)

        # EMA fast / slow
        ema_f = pd.Series(close).ewm(span=self.ema_fast, adjust=False).mean().values
        ema_s = pd.Series(close).ewm(span=self.ema_slow, adjust=False).mean().values

        # ADX
        adx_series = ADX(
            pd.Series(high), pd.Series(low), pd.Series(close), self.adx_period
        ).values

        # VWAP (cumulative)
        tp = (high + low + close) / 3.0
        cum_tp_vol = np.cumsum(tp * volume)
        cum_vol = np.cumsum(volume)
        vwap_arr = np.where(cum_vol > 0, cum_tp_vol / cum_vol, close)

        # ATR
        atr_series = ATR(
            pd.Series(high), pd.Series(low), pd.Series(close), self.atr_period
        ).values

        # Register with backtesting.py
        self.ema_fast_line = self.I(lambda: ema_f, name='EMA_Fast', overlay=True)
        self.ema_slow_line = self.I(lambda: ema_s, name='EMA_Slow', overlay=True)
        self.adx = self.I(lambda: adx_series, name='ADX', overlay=False)
        self.vwap = self.I(lambda: vwap_arr, name='VWAP', overlay=True)
        self.atr = self.I(lambda: atr_series, name='ATR', overlay=False)

    def next(self):
        """Process each bar."""
        if len(self.data) < self.ema_slow + 10:
            return

        close = self.data.Close[-1]
        ema_f = self.ema_fast_line[-1]
        ema_s = self.ema_slow_line[-1]
        adx_val = self.adx[-1]
        vwap_val = self.vwap[-1]
        atr_val = self.atr[-1]

        if np.isnan(ema_f) or np.isnan(ema_s) or np.isnan(adx_val) or np.isnan(atr_val):
            return
        if atr_val <= 0:
            return

        bullish_trend = ema_f > ema_s
        bearish_trend = ema_f < ema_s
        strong_trend = adx_val > self.adx_threshold

        if self.position:
            # Exit on trend reversal
            if self.position.is_long and bearish_trend:
                self.position.close()
            elif self.position.is_short and bullish_trend:
                self.position.close()
        else:
            if not strong_trend:
                return  # No trade without strong trend

            risk_per_unit = atr_val * self.atr_stop_mult

            # LONG entry
            if bullish_trend and close > vwap_val:
                stop_price = close - risk_per_unit
                tp_price = close + (self.rr_ratio * risk_per_unit)

                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = (size_units * close) / self.equity
                size_fraction = max(0.01, min(0.50, size_fraction))

                self.buy(size=size_fraction, sl=stop_price, tp=tp_price)

            # SHORT entry
            elif bearish_trend and close < vwap_val:
                stop_price = close + risk_per_unit
                tp_price = close - (self.rr_ratio * risk_per_unit)

                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = (size_units * close) / self.equity
                size_fraction = max(0.01, min(0.50, size_fraction))

                self.sell(size=size_fraction, sl=stop_price, tp=tp_price)


class VelociraptorLive(BaseStrategy):
    """Live trading implementation of the Velociraptor strategy."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.ema_fast = config.get("ema_fast", 20)
        self.ema_slow = config.get("ema_slow", 50)
        self.adx_period = config.get("adx_period", 14)
        self.adx_threshold = config.get("adx_threshold", 25)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 2.0)
        self.rr_ratio = config.get("rr_ratio", 2.5)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]

        df = state.get("df")
        if df is None or len(df) < self.ema_slow + 10:
            return StrategySignal(symbol=symbol, action="HOLD")

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        ema_f = EMA(close, self.ema_fast).iloc[-1]
        ema_s = EMA(close, self.ema_slow).iloc[-1]
        adx_val = ADX(high, low, close, self.adx_period).iloc[-1]
        vwap_val = VWAP(high, low, close, volume).iloc[-1]
        atr_val = ATR(high, low, close, self.atr_period).iloc[-1]

        current_close = candle["close"]
        position = state.get("position")

        bullish = ema_f > ema_s
        bearish = ema_f < ema_s
        strong = adx_val > self.adx_threshold

        if position:
            if position.get("side") == "LONG" and bearish:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_LONG",
                                     extra={"reason": "trend_reversal"})
            elif position.get("side") == "SHORT" and bullish:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_SHORT",
                                     extra={"reason": "trend_reversal"})
        else:
            if not strong:
                return StrategySignal(symbol=symbol, action="HOLD")

            risk_per_unit = atr_val * self.atr_stop_mult

            if bullish and current_close > vwap_val:
                stop = current_close - risk_per_unit
                tp = current_close + (self.rr_ratio * risk_per_unit)
                state["position"] = {"side": "LONG", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                     extra={"stop": stop, "tp": tp, "adx": adx_val})

            elif bearish and current_close < vwap_val:
                stop = current_close + risk_per_unit
                tp = current_close - (self.rr_ratio * risk_per_unit)
                state["position"] = {"side": "SHORT", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                     extra={"stop": stop, "tp": tp, "adx": adx_val})

        return StrategySignal(symbol=symbol, action="HOLD")
