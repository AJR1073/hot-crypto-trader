"""
Market Regime Detector using Hurst Exponent and ADX.

Classifies the current market into one of four regimes:
  - TRENDING_STRONG: H > 0.60, ADX > 25  → favour trend-following strategies
  - TRENDING_WEAK:   H > 0.55, ADX > 20  → hybrid allocation
  - MEAN_REVERTING:  H < 0.45, ADX < 20  → favour mean-reversion strategies
  - RANDOM_WALK:     0.45 ≤ H ≤ 0.55     → cash / grid only

Reference: doc/research_images/image12.png (Regime Classification Table)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regime enum
# ---------------------------------------------------------------------------

class Regime(Enum):
    TRENDING_STRONG = "trending_strong"
    TRENDING_WEAK = "trending_weak"
    MEAN_REVERTING = "mean_reverting"
    RANDOM_WALK = "random_walk"


# Strategy groups that map to each regime
REGIME_STRATEGIES: dict[Regime, list[str]] = {
    Regime.TRENDING_STRONG: [
        "trend_ema", "supertrend", "turtle", "triple_momentum",
    ],
    Regime.TRENDING_WEAK: [
        "trend_ema", "supertrend", "squeeze_breakout", "macd_crossover",
    ],
    Regime.MEAN_REVERTING: [
        "mean_reversion_bb", "rsi_divergence", "vwap_bounce",
    ],
    Regime.RANDOM_WALK: [
        "grid_ladder",
    ],
}

# Allocation weight per regime (how much capital the active strategies get)
REGIME_ALLOCATION: dict[Regime, float] = {
    Regime.TRENDING_STRONG: 0.80,
    Regime.TRENDING_WEAK: 0.50,
    Regime.MEAN_REVERTING: 0.80,
    Regime.RANDOM_WALK: 1.00,  # 100% in cash/grid
}


@dataclass
class RegimeState:
    """Result of a regime classification for a single symbol."""

    regime: Regime
    hurst: float
    adx: float
    confidence: float  # 0.0–1.0 based on how firmly in the zone
    active_strategies: list[str]
    allocation_weight: float

    def __repr__(self) -> str:
        return (
            f"<Regime {self.regime.value} H={self.hurst:.3f} "
            f"ADX={self.adx:.1f} conf={self.confidence:.2f}>"
        )


# ---------------------------------------------------------------------------
# Hurst Exponent (Rescaled Range method)
# ---------------------------------------------------------------------------

def compute_hurst(series: pd.Series, window: int = 100) -> float:
    """
    Compute the Hurst Exponent using the Rescaled Range (R/S) method.

    H > 0.5 → trending / persistent (momentum works)
    H = 0.5 → random walk
    H < 0.5 → mean-reverting (reversion strategies work)

    Args:
        series: Price series (close prices, at least ``window`` long).
        window: Number of bars for computation (default 100).

    Returns:
        Hurst exponent as a float, or 0.5 on failure.
    """
    ts = series.dropna().values[-window:]
    if len(ts) < 20:
        logger.warning("Insufficient data for Hurst (%d bars)", len(ts))
        return 0.5  # assume random walk when data is scarce

    # Log-returns
    returns = np.diff(np.log(ts))
    if len(returns) < 10:
        return 0.5

    # Divide into sub-series of different sizes
    max_k = min(len(returns) // 2, 50)
    sizes = []
    rs_values = []

    for size in range(10, max_k + 1, 2):
        n_chunks = len(returns) // size
        if n_chunks < 1:
            continue

        rs_chunk = []
        for i in range(n_chunks):
            chunk = returns[i * size : (i + 1) * size]
            mean_chunk = np.mean(chunk)
            deviate = np.cumsum(chunk - mean_chunk)
            r = np.max(deviate) - np.min(deviate)
            s = np.std(chunk, ddof=1)
            if s > 1e-12:
                rs_chunk.append(r / s)

        if rs_chunk:
            sizes.append(size)
            rs_values.append(np.mean(rs_chunk))

    if len(sizes) < 3:
        return 0.5

    # Linear regression of log(R/S) on log(size) → slope = Hurst exponent
    log_sizes = np.log(sizes)
    log_rs = np.log(rs_values)

    try:
        coeffs = np.polyfit(log_sizes, log_rs, 1)
        hurst = float(coeffs[0])
    except (np.linalg.LinAlgError, ValueError):
        return 0.5

    # Clamp to [0, 1]
    return float(np.clip(hurst, 0.0, 1.0))


# ---------------------------------------------------------------------------
# ADX (Average Directional Index)
# ---------------------------------------------------------------------------

def compute_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> float:
    """
    Compute the Average Directional Index (ADX).

    ADX > 25 → strong trend
    ADX < 20 → weak / no trend

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: Smoothing period (default 14).

    Returns:
        Latest ADX value (0–100 scale), or 0.0 on insufficient data.
    """
    if len(close) < period + 1:
        return 0.0

    # True Range
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm = pd.Series(plus_dm, index=close.index)
    minus_dm = pd.Series(minus_dm, index=close.index)

    # Smoothed using Wilder's method (EMA with alpha=1/period)
    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    smooth_plus = plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    smooth_minus = minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    # Directional Indicators
    plus_di = 100 * smooth_plus / atr
    minus_di = 100 * smooth_minus / atr

    # DX and ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    latest = adx.dropna()
    if latest.empty:
        return 0.0
    return float(latest.iloc[-1])


# ---------------------------------------------------------------------------
# Regime classifier
# ---------------------------------------------------------------------------

def classify_regime(
    df: pd.DataFrame,
    hurst_window: int = 100,
    adx_period: int = 14,
) -> RegimeState:
    """
    Classify the current market regime for a symbol.

    Uses the latest ``hurst_window`` bars of close data for the Hurst
    Exponent and the full DataFrame for ADX.

    Args:
        df: OHLCV DataFrame (must contain 'high', 'low', 'close' columns).
        hurst_window: Window for Hurst Exponent (default 100).
        adx_period: Period for ADX (default 14).

    Returns:
        RegimeState with the detected regime and supporting metrics.
    """
    hurst = compute_hurst(df["close"], window=hurst_window)
    adx = compute_adx(df["high"], df["low"], df["close"], period=adx_period)

    # Classify using the research-defined thresholds
    if hurst > 0.60 and adx > 25:
        regime = Regime.TRENDING_STRONG
        # Confidence: how far into the zone (normalised)
        confidence = min(1.0, (hurst - 0.60) / 0.15 * 0.5 + (adx - 25) / 25 * 0.5)
    elif hurst > 0.55 and adx > 20:
        regime = Regime.TRENDING_WEAK
        confidence = min(1.0, (hurst - 0.55) / 0.10 * 0.5 + (adx - 20) / 10 * 0.5)
    elif hurst < 0.45 and adx < 20:
        regime = Regime.MEAN_REVERTING
        confidence = min(1.0, (0.45 - hurst) / 0.15 * 0.5 + (20 - adx) / 20 * 0.5)
    else:
        regime = Regime.RANDOM_WALK
        # In the ambiguous zone → low confidence
        confidence = max(0.0, 1.0 - abs(hurst - 0.50) / 0.10)

    state = RegimeState(
        regime=regime,
        hurst=hurst,
        adx=adx,
        confidence=confidence,
        active_strategies=REGIME_STRATEGIES[regime],
        allocation_weight=REGIME_ALLOCATION[regime],
    )

    logger.info(
        "Regime detected: %s  (H=%.3f, ADX=%.1f, conf=%.2f)",
        regime.value, hurst, adx, confidence,
    )
    return state
