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
