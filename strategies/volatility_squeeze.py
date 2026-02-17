"""
Volatility Squeeze Strategy (TTM Squeeze).

From Deep Research — the breakout strategy:
- Detects squeeze: Bollinger Bands INSIDE Keltner Channel
- Trades breakout when squeeze releases
- Uses momentum (close - SMA) for direction
- More precise than basic SQZ_BO (uses KC comparison instead of raw bandwidth)

Active when: V_Ratio < 0.8 (compressed volatility), but runs standalone too.

Contains:
- VolatilitySqueezeBacktest: Backtesting.py Strategy class
- VolatilitySqueezeLive: BaseStrategy for live trading
"""

import numpy as np
import pandas as pd
from backtesting import Strategy

from .base import BaseStrategy, StrategySignal
from .indicators import EMA, SMA, STD, ATR, KeltnerChannel


class VolatilitySqueezeBacktest(Strategy):
    """
    Backtesting.py implementation of TTM Volatility Squeeze.

    Squeeze detection:
        BB_upper < KC_upper AND BB_lower > KC_lower
        (Bollinger Bands compressed inside Keltner Channel)

    Entry (on squeeze release):
        LONG: Squeeze fires off + momentum > 0 (close > SMA)
        SHORT: Squeeze fires off + momentum < 0 (close < SMA)

    Exit:
        Momentum reversal or ATR trailing stop
    """

    # Strategy parameters
    bb_period = 20
    bb_std = 2.0
    kc_ema_period = 20
    kc_atr_period = 10
    kc_atr_mult = 1.5
    atr_period = 14
    atr_stop_mult = 2.0
    rr_ratio = 2.0
    risk_per_trade = 0.01

    def init(self):
        """Initialize indicators inline."""
        close = np.array(self.data.Close, dtype=float)
        high = np.array(self.data.High, dtype=float)
        low = np.array(self.data.Low, dtype=float)

        close_s = pd.Series(close)
        high_s = pd.Series(high)
        low_s = pd.Series(low)

        # Bollinger Bands
        bb_mid = close_s.rolling(self.bb_period).mean().values
        bb_std = close_s.rolling(self.bb_period).std().values
        bb_upper = bb_mid + (self.bb_std * bb_std)
        bb_lower = bb_mid - (self.bb_std * bb_std)

        # Keltner Channel
        kc = KeltnerChannel(
            high_s, low_s, close_s,
            ema_period=self.kc_ema_period,
            atr_period=self.kc_atr_period,
            atr_mult=self.kc_atr_mult
        )
        kc_upper = kc['upper'].values
        kc_lower = kc['lower'].values

        # Squeeze detection: BB inside KC
        squeeze_arr = np.zeros(len(close))
        for i in range(len(close)):
            if np.isnan(bb_upper[i]) or np.isnan(kc_upper[i]):
                squeeze_arr[i] = np.nan
            elif bb_upper[i] < kc_upper[i] and bb_lower[i] > kc_lower[i]:
                squeeze_arr[i] = 1.0   # In squeeze
            else:
                squeeze_arr[i] = 0.0   # Not in squeeze

        # Momentum: simple (close - SMA)
        momentum = close - bb_mid

        # ATR
        atr = ATR(high_s, low_s, close_s, self.atr_period).values

        # Register
        self.squeeze = self.I(lambda: squeeze_arr, name='Squeeze', overlay=False)
        self.momentum = self.I(lambda: momentum, name='Momentum', overlay=False)
        self.bb_mid_line = self.I(lambda: bb_mid, name='BB_Mid', overlay=True)
        self.atr = self.I(lambda: atr, name='ATR', overlay=False)

    def next(self):
        """Process each bar."""
        if len(self.data) < max(self.bb_period, self.kc_ema_period) + 10:
            return

        close = self.data.Close[-1]
        current_squeeze = self.squeeze[-1]
        prev_squeeze = self.squeeze[-2] if len(self.data) > 1 else np.nan
        mom = self.momentum[-1]
        atr_val = self.atr[-1]

        if np.isnan(current_squeeze) or np.isnan(prev_squeeze) or np.isnan(mom) or np.isnan(atr_val):
            return
        if atr_val <= 0:
            return

        # Squeeze fire: was in squeeze, now released
        squeeze_fired = (prev_squeeze > 0.5) and (current_squeeze < 0.5)

        if self.position:
            # Exit on momentum reversal
            if self.position.is_long and mom < 0:
                self.position.close()
            elif self.position.is_short and mom > 0:
                self.position.close()
        else:
            if not squeeze_fired:
                return  # Only trade on squeeze release

            risk_per_unit = atr_val * self.atr_stop_mult

            # LONG: squeeze fires + positive momentum
            if mom > 0:
                stop_price = close - risk_per_unit
                tp_price = close + (self.rr_ratio * risk_per_unit)

                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = (size_units * close) / self.equity
                size_fraction = max(0.01, min(0.50, size_fraction))

                self.buy(size=size_fraction, sl=stop_price, tp=tp_price)

            # SHORT: squeeze fires + negative momentum
            elif mom < 0:
                stop_price = close + risk_per_unit
                tp_price = close - (self.rr_ratio * risk_per_unit)

                risk_dollars = self.equity * self.risk_per_trade
                size_units = risk_dollars / risk_per_unit
                size_fraction = (size_units * close) / self.equity
                size_fraction = max(0.01, min(0.50, size_fraction))

                self.sell(size=size_fraction, sl=stop_price, tp=tp_price)


class VolatilitySqueezeLive(BaseStrategy):
    """Live trading implementation of TTM Volatility Squeeze."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.bb_period = config.get("bb_period", 20)
        self.bb_std_mult = config.get("bb_std", 2.0)
        self.kc_ema_period = config.get("kc_ema_period", 20)
        self.kc_atr_period = config.get("kc_atr_period", 10)
        self.kc_atr_mult = config.get("kc_atr_mult", 1.5)
        self.atr_period = config.get("atr_period", 14)
        self.atr_stop_mult = config.get("atr_stop_mult", 2.0)
        self.rr_ratio = config.get("rr_ratio", 2.0)

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """Process a new candle and return a signal."""
        self.init_symbol(symbol)
        state = self.state[symbol]

        if "prev_squeeze" not in state:
            state["prev_squeeze"] = False

        df = state.get("df")
        if df is None or len(df) < max(self.bb_period, self.kc_ema_period) + 10:
            return StrategySignal(symbol=symbol, action="HOLD")

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # Bollinger Bands
        bb_mid_val = SMA(close, self.bb_period).iloc[-1]
        bb_std_val = STD(close, self.bb_period).iloc[-1]
        bb_upper = bb_mid_val + (self.bb_std_mult * bb_std_val)
        bb_lower = bb_mid_val - (self.bb_std_mult * bb_std_val)

        # Keltner Channel
        kc = KeltnerChannel(
            high, low, close,
            ema_period=self.kc_ema_period,
            atr_period=self.kc_atr_period,
            atr_mult=self.kc_atr_mult
        )
        kc_upper = kc['upper'].iloc[-1]
        kc_lower = kc['lower'].iloc[-1]

        # Squeeze detection
        in_squeeze = bb_upper < kc_upper and bb_lower > kc_lower
        was_squeezed = state.get("prev_squeeze", False)
        state["prev_squeeze"] = in_squeeze

        current_close = candle["close"]
        mom = current_close - bb_mid_val

        atr_val = ATR(high, low, close, self.atr_period).iloc[-1]
        position = state.get("position")

        squeeze_fired = was_squeezed and not in_squeeze

        if position:
            if position.get("side") == "LONG" and mom < 0:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_LONG",
                                     extra={"reason": "momentum_reversal"})
            elif position.get("side") == "SHORT" and mom > 0:
                state["position"] = None
                return StrategySignal(symbol=symbol, action="CLOSE_SHORT",
                                     extra={"reason": "momentum_reversal"})
        else:
            if not squeeze_fired:
                return StrategySignal(symbol=symbol, action="HOLD")

            risk_per_unit = atr_val * self.atr_stop_mult

            if mom > 0:
                stop = current_close - risk_per_unit
                tp = current_close + (self.rr_ratio * risk_per_unit)
                state["position"] = {"side": "LONG", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_LONG",
                                     extra={"stop": stop, "tp": tp,
                                            "squeeze_fired": True, "momentum": mom})

            elif mom < 0:
                stop = current_close + risk_per_unit
                tp = current_close - (self.rr_ratio * risk_per_unit)
                state["position"] = {"side": "SHORT", "entry": current_close}
                return StrategySignal(symbol=symbol, action="OPEN_SHORT",
                                     extra={"stop": stop, "tp": tp,
                                            "squeeze_fired": True, "momentum": mom})

        return StrategySignal(symbol=symbol, action="HOLD")
