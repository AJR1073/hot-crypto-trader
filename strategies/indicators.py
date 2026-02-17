"""
Shared indicator helper functions for trading strategies.

These functions are used by both Backtesting.py and Live strategies
to ensure consistent indicator calculations.
"""

import numpy as np
import pandas as pd


def EMA(arr: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average.
    
    Args:
        arr: Price series (typically close prices)
        period: EMA period
        
    Returns:
        EMA series
    """
    return pd.Series(arr).ewm(span=period, adjust=False).mean()


def SMA(arr: pd.Series, period: int) -> pd.Series:
    """
    Simple Moving Average.
    
    Args:
        arr: Price series
        period: SMA period
        
    Returns:
        SMA series
    """
    return pd.Series(arr).rolling(window=period).mean()


def STD(arr: pd.Series, period: int) -> pd.Series:
    """
    Rolling Standard Deviation.
    
    Args:
        arr: Price series
        period: Period for standard deviation
        
    Returns:
        Standard deviation series
    """
    return pd.Series(arr).rolling(window=period).std()


def ATR(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """
    Average True Range.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ATR period
        
    Returns:
        ATR series
    """
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def Bollinger(arr: pd.Series, period: int = 20, std_mult: float = 2.0) -> tuple:
    """
    Bollinger Bands.
    
    Args:
        arr: Price series (typically close prices)
        period: SMA period for middle band
        std_mult: Standard deviation multiplier for band width
        
    Returns:
        Tuple of (middle, upper, lower) band series
    """
    middle = SMA(arr, period)
    std = STD(arr, period)
    upper = middle + (std * std_mult)
    lower = middle - (std * std_mult)
    return middle, upper, lower


def BollingerBandwidth(upper: pd.Series, lower: pd.Series, middle: pd.Series) -> pd.Series:
    """
    Bollinger Bandwidth indicator.
    
    Bandwidth = (Upper - Lower) / Middle
    Low bandwidth indicates a "squeeze" (low volatility).
    
    Args:
        upper: Upper band
        lower: Lower band
        middle: Middle band (SMA)
        
    Returns:
        Bandwidth series
    """
    return (upper - lower) / middle


def SuperTrend(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """
    SuperTrend Indicator.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ATR period
        multiplier: ATR multiplier
        
    Returns:
        DataFrame with columns: 'SuperTrend', 'Trend' (1: Bullish, -1: Bearish)
    """
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    
    # Calculate ATR
    atr = ATR(high, low, close, period)
    
    # Calculate basic upper and lower bands
    hl2 = (high + low) / 2
    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)
    
    # Initialize final bands
    final_upper = pd.Series(index=close.index, dtype='float64')
    final_lower = pd.Series(index=close.index, dtype='float64')
    supertrend = pd.Series(index=close.index, dtype='float64')
    trend = pd.Series(index=close.index, dtype='int64')
    
    # Optimization: Iterate using numpy arrays for speed
    close_arr = close.values
    basic_upper_arr = basic_upper.values
    basic_lower_arr = basic_lower.values
    
    final_upper_val = 0.0
    final_lower_val = 0.0
    trend_val = 1  # 1 for bull, -1 for bear
    
    final_upper_list = []
    final_lower_list = []
    supertrend_list = []
    trend_list = []
    
    for i in range(len(close)):
        curr_close = close_arr[i]
        curr_basic_upper = basic_upper_arr[i]
        curr_basic_lower = basic_lower_arr[i]
        prev_close = close_arr[i-1] if i > 0 else 0
        
        # Calculate Final Upper Band
        if i == 0:
            final_upper_val = curr_basic_upper
        else:
            if (curr_basic_upper < final_upper_val) or (prev_close > final_upper_val):
                final_upper_val = curr_basic_upper
            # else keep previous final_upper_val
            
        # Calculate Final Lower Band
        if i == 0:
            final_lower_val = curr_basic_lower
        else:
            if (curr_basic_lower > final_lower_val) or (prev_close < final_lower_val):
                final_lower_val = curr_basic_lower
                
        # Calculate Trend
        if i == 0:
            trend_val = 1
        else:
            if (trend_val == 1) and (curr_close < final_lower_val):
                trend_val = -1
            elif (trend_val == -1) and (curr_close > final_upper_val):
                trend_val = 1
        
        # Calculate SuperTrend Line
        if trend_val == 1:
            st_val = final_lower_val
        else:
            st_val = final_upper_val
            
        final_upper_list.append(final_upper_val)
        final_lower_list.append(final_lower_val)
        supertrend_list.append(st_val)
        trend_list.append(trend_val)
        
    return pd.DataFrame({
        'SuperTrend': supertrend_list,
        'Trend': trend_list
    }, index=close.index)


def RSI(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index.
    
    Args:
        close: Close prices
        period: RSI period (default 14)
        
    Returns:
        RSI series (0-100)
    """
    close = pd.Series(close)
    delta = close.diff()
    
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def MACD(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """
    Moving Average Convergence Divergence.
    
    Args:
        close: Close prices
        fast: Fast EMA period (default 12)
        slow: Slow EMA period (default 26)
        signal: Signal line period (default 9)
        
    Returns:
        DataFrame with 'macd', 'signal', 'histogram'
    """
    close = pd.Series(close)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return pd.DataFrame({
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    }, index=close.index)


def Ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
             tenkan: int = 9, kijun: int = 26, senkou_b: int = 52) -> pd.DataFrame:
    """
    Ichimoku Cloud indicator.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        tenkan: Tenkan-sen period (default 9)
        kijun: Kijun-sen period (default 26)
        senkou_b: Senkou Span B period (default 52)
        
    Returns:
        DataFrame with tenkan_sen, kijun_sen, senkou_a, senkou_b, chikou_span
    """
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    
    # Tenkan-sen (Conversion Line)
    tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    
    # Kijun-sen (Base Line)
    kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2
    
    # Senkou Span A (Leading Span A) - shifted forward 26 periods
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
    
    # Senkou Span B (Leading Span B) - shifted forward 26 periods
    senkou_span_b_val = (high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2
    senkou_span_b_shifted = senkou_span_b_val.shift(kijun)
    
    # Chikou Span (Lagging Span) - shifted back 26 periods
    chikou_span = close.shift(-kijun)
    
    return pd.DataFrame({
        'tenkan_sen': tenkan_sen,
        'kijun_sen': kijun_sen,
        'senkou_a': senkou_span_a,
        'senkou_b': senkou_span_b_shifted,
        'chikou_span': chikou_span
    }, index=close.index)


def VWAP(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    Volume Weighted Average Price.
    
    Note: This is a cumulative VWAP. For intraday, reset at session start.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        volume: Volume
        
    Returns:
        VWAP series
    """
    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).cumsum() / volume.cumsum()
    return vwap


def DonchianChannel(high: pd.Series, low: pd.Series, period: int = 20) -> pd.DataFrame:
    """
    Donchian Channel (for Turtle Trading).
    
    Args:
        high: High prices
        low: Low prices
        period: Lookback period (default 20)
        
    Returns:
        DataFrame with 'upper', 'lower', 'middle'
    """
    high = pd.Series(high)
    low = pd.Series(low)
    
    upper = high.rolling(period).max()
    lower = low.rolling(period).min()
    middle = (upper + lower) / 2
    
    return pd.DataFrame({
        'upper': upper,
        'lower': lower,
        'middle': middle
    }, index=high.index)


def Stochastic(high: pd.Series, low: pd.Series, close: pd.Series, 
               k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    """
    Stochastic Oscillator (%K and %D).
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        k_period: Lookback period for %K (default 14)
        d_period: Smoothing period for %D (default 3)
        
    Returns:
        DataFrame with 'k' and 'd' columns
    """
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    
    # %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    
    k = ((close - lowest_low) / (highest_high - lowest_low)) * 100
    
    # %D = SMA of %K
    d = k.rolling(window=d_period).mean()
    
    return pd.DataFrame({'k': k, 'd': d})


def ADX(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Average Directional Index — measures trend strength (0-100).

    ADX > 25 = strong trend, ADX < 20 = weak/no trend.

    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ADX smoothing period (default 14)

    Returns:
        ADX series (0-100)
    """
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr = ATR(high, low, close, period)

    plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)

    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=1/period, min_periods=period).mean()
    return adx


def KeltnerChannel(high: pd.Series, low: pd.Series, close: pd.Series,
                   ema_period: int = 20, atr_period: int = 10,
                   atr_mult: float = 1.5) -> pd.DataFrame:
    """
    Keltner Channel — EMA ± ATR*mult.

    Used with Bollinger Bands for TTM Squeeze detection:
    when BB is inside KC, volatility is compressed (squeeze).

    Args:
        high: High prices
        low: Low prices
        close: Close prices
        ema_period: EMA period for middle line
        atr_period: ATR period
        atr_mult: ATR multiplier for channel width

    Returns:
        DataFrame with 'middle', 'upper', 'lower'
    """
    close = pd.Series(close)
    middle = EMA(close, ema_period)
    atr = ATR(high, low, close, atr_period)
    upper = middle + (atr_mult * atr)
    lower = middle - (atr_mult * atr)
    return pd.DataFrame({
        'middle': middle,
        'upper': upper,
        'lower': lower
    }, index=close.index)
