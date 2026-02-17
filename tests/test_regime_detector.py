"""
Tests for core/regime_detector.py — Hurst Exponent and regime classification.
"""

import numpy as np
import pandas as pd
import pytest

from core.regime_detector import (
    Regime,
    RegimeState,
    compute_hurst,
    compute_adx,
    classify_regime,
)


# ---------------------------------------------------------------------------
# Synthetic data generators
# ---------------------------------------------------------------------------

def _trending_series(n: int = 200, drift: float = 0.002) -> pd.Series:
    """Generate an upward-trending price series (Hurst should be > 0.5)."""
    np.random.seed(42)
    returns = drift + np.random.normal(0, 0.005, n)
    prices = 100 * np.exp(np.cumsum(returns))
    return pd.Series(prices)


def _mean_reverting_series(n: int = 200, mean: float = 100) -> pd.Series:
    """Generate a mean-reverting series (Hurst should be < 0.5)."""
    np.random.seed(42)
    prices = [mean]
    for _ in range(n - 1):
        # Ornstein-Uhlenbeck: pull back toward mean
        reversion = 0.1 * (mean - prices[-1])
        noise = np.random.normal(0, 0.5)
        prices.append(prices[-1] + reversion + noise)
    return pd.Series(prices)


def _random_walk_series(n: int = 200) -> pd.Series:
    """Generate a pure random walk (Hurst ≈ 0.5)."""
    np.random.seed(42)
    returns = np.random.normal(0, 0.01, n)
    prices = 100 * np.exp(np.cumsum(returns))
    return pd.Series(prices)


def _make_ohlcv(close_series: pd.Series) -> pd.DataFrame:
    """Convert a close series into a full OHLCV DataFrame."""
    spread = close_series * 0.005
    return pd.DataFrame({
        "open": close_series - spread * 0.5,
        "high": close_series + spread,
        "low": close_series - spread,
        "close": close_series,
        "volume": np.random.randint(1000, 10000, len(close_series)),
    })


# ---------------------------------------------------------------------------
# Hurst Exponent tests
# ---------------------------------------------------------------------------

class TestHurstExponent:
    def test_trending_series_hurst_above_half(self):
        series = _trending_series(200, drift=0.003)
        h = compute_hurst(series, window=100)
        assert h > 0.5, f"Trending series should have H > 0.5, got {h:.3f}"

    def test_mean_reverting_series_hurst_below_half(self):
        series = _mean_reverting_series(200)
        h = compute_hurst(series, window=100)
        assert h < 0.55, f"Mean-reverting series should have H < 0.55, got {h:.3f}"

    def test_insufficient_data_returns_half(self):
        series = pd.Series([100, 101, 102])
        h = compute_hurst(series, window=100)
        assert h == 0.5, "Insufficient data should return 0.5"

    def test_flat_series(self):
        series = pd.Series([100.0] * 200)
        h = compute_hurst(series, window=100)
        # Flat series has 0 variance — should gracefully return 0.5
        assert 0.0 <= h <= 1.0

    def test_output_clamped_to_0_1(self):
        series = _trending_series(200)
        h = compute_hurst(series, window=100)
        assert 0.0 <= h <= 1.0


# ---------------------------------------------------------------------------
# ADX tests
# ---------------------------------------------------------------------------

class TestADX:
    def test_trending_market_high_adx(self):
        df = _make_ohlcv(_trending_series(200, drift=0.005))
        adx = compute_adx(df["high"], df["low"], df["close"], period=14)
        # Strong trend should yield ADX > 20
        assert adx > 15, f"Strong trend should have ADX > 15, got {adx:.1f}"

    def test_insufficient_data(self):
        df = _make_ohlcv(pd.Series([100, 101, 102]))
        adx = compute_adx(df["high"], df["low"], df["close"], period=14)
        assert adx == 0.0

    def test_adx_returns_positive(self):
        df = _make_ohlcv(_random_walk_series(200))
        adx = compute_adx(df["high"], df["low"], df["close"], period=14)
        assert adx >= 0.0


# ---------------------------------------------------------------------------
# Regime classification tests
# ---------------------------------------------------------------------------

class TestRegimeClassification:
    def test_trending_regime(self):
        df = _make_ohlcv(_trending_series(200, drift=0.005))
        state = classify_regime(df, hurst_window=100, adx_period=14)
        assert isinstance(state, RegimeState)
        assert state.regime in (Regime.TRENDING_STRONG, Regime.TRENDING_WEAK)

    def test_mean_reverting_regime(self):
        df = _make_ohlcv(_mean_reverting_series(200))
        state = classify_regime(df, hurst_window=100, adx_period=14)
        # Mean-reverting with low ADX
        assert state.hurst < 0.55

    def test_regime_state_has_strategies(self):
        df = _make_ohlcv(_trending_series(200, drift=0.005))
        state = classify_regime(df)
        assert len(state.active_strategies) > 0

    def test_regime_state_allocation_positive(self):
        df = _make_ohlcv(_random_walk_series(200))
        state = classify_regime(df)
        assert 0.0 < state.allocation_weight <= 1.0

    def test_regime_state_confidence_bounded(self):
        df = _make_ohlcv(_trending_series(200))
        state = classify_regime(df)
        assert 0.0 <= state.confidence <= 1.0
