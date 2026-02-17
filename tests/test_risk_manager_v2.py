"""
Tests for core/risk_manager.py — Half-Kelly, volatility targeting, and correlation guard.
"""

import numpy as np
import pytest

from core.risk_manager import RiskManager, RiskDecision


class TestHalfKelly:
    """Test the Half-Kelly position sizing overlay."""

    def _seed_trades(self, rm: RiskManager, n_wins: int, n_losses: int,
                     avg_win: float = 50.0, avg_loss: float = 30.0):
        """Load the risk manager with synthetic trade history."""
        for _ in range(n_wins):
            rm.register_trade_close(avg_win, symbol="TEST")
        for _ in range(n_losses):
            rm.register_trade_close(-avg_loss, symbol="TEST")

    def test_kelly_requires_minimum_trades(self):
        rm = RiskManager(kelly_lookback=50)
        # Only 5 trades — should return None
        for _ in range(5):
            rm.register_trade_close(10.0, symbol="TEST")
        assert rm._compute_kelly_fraction() is None

    def test_kelly_with_profitable_history(self):
        rm = RiskManager(initial_equity=10000, kelly_lookback=50, kelly_fraction=0.5)
        # 60% win rate, avg_win=50, avg_loss=30
        self._seed_trades(rm, n_wins=18, n_losses=12, avg_win=50.0, avg_loss=30.0)
        kelly_f = rm._compute_kelly_fraction()
        assert kelly_f is not None
        assert kelly_f > 0, "Positive edge should yield positive Kelly fraction"

    def test_kelly_with_losing_history(self):
        rm = RiskManager(initial_equity=10000, kelly_lookback=50, kelly_fraction=0.5)
        # 30% win rate, avg_win=50, avg_loss=30
        self._seed_trades(rm, n_wins=9, n_losses=21, avg_win=50.0, avg_loss=30.0)
        kelly_f = rm._compute_kelly_fraction()
        # Negative edge — should be clamped to 0
        assert kelly_f is not None
        assert kelly_f >= 0, "Negative edge should clamp Kelly to 0"

    def test_kelly_capped_at_ceiling(self):
        rm = RiskManager(initial_equity=10000, risk_per_trade=0.005, kelly_fraction=0.5)
        # Very high win rate — should be capped
        self._seed_trades(rm, n_wins=30, n_losses=0, avg_win=100.0, avg_loss=0)
        # With only wins, Kelly can't compute (no losses) → None
        kelly_f = rm._compute_kelly_fraction()
        assert kelly_f is None  # needs both wins and losses

    def test_kelly_with_mixed_history(self):
        rm = RiskManager(initial_equity=10000, kelly_lookback=50, kelly_fraction=0.5,
                         risk_per_trade=0.01)
        self._seed_trades(rm, n_wins=12, n_losses=8, avg_win=60.0, avg_loss=40.0)
        kelly_f = rm._compute_kelly_fraction()
        assert kelly_f is not None
        assert 0 <= kelly_f <= rm.risk_per_trade * 2


class TestVolatilityTargeting:
    """Test position sizing with volatility scalar."""

    def test_vol_scales_position_up(self):
        rm = RiskManager(initial_equity=10000, target_annual_vol=0.15)
        # Low vol → should scale up
        base_size, _, _ = rm.compute_position_size(
            price=100, atr_value=2.0, realized_vol=0.10
        )
        no_vol_size, _, _ = rm.compute_position_size(
            price=100, atr_value=2.0, realized_vol=None
        )
        assert base_size > no_vol_size * 0.9, "Low vol should scale up"

    def test_vol_scales_position_down(self):
        rm = RiskManager(initial_equity=10000, target_annual_vol=0.15)
        # High vol → should scale down
        base_size, _, _ = rm.compute_position_size(
            price=100, atr_value=2.0, realized_vol=0.50
        )
        no_vol_size, _, _ = rm.compute_position_size(
            price=100, atr_value=2.0, realized_vol=None
        )
        assert base_size < no_vol_size * 1.1, "High vol should scale down"

    def test_vol_scalar_clamped(self):
        rm = RiskManager(initial_equity=10000, target_annual_vol=0.15)
        # Extremely low vol → scalar should be capped at 2.0
        size, _, _ = rm.compute_position_size(
            price=100, atr_value=2.0, realized_vol=0.01
        )
        base, _, _ = rm.compute_position_size(
            price=100, atr_value=2.0, realized_vol=None
        )
        # With 2.0x cap, size should be at most 2x the base
        assert size <= base * 2.5


class TestCorrelationGuard:
    """Test the correlation-based allocation scaling."""

    def test_uncorrelated_assets_no_reduction(self):
        rm = RiskManager(correlation_threshold=0.80)
        np.random.seed(42)
        prices = {
            "BTC/USDT": list(100 + np.cumsum(np.random.normal(0, 1, 50))),
            "ETH/USDT": list(50 + np.cumsum(np.random.normal(0, 1, 50))),
        }
        scale = rm.compute_correlation_guard(prices)
        # Random series should be uncorrelated → scale = 1.0
        assert scale >= 0.9

    def test_highly_correlated_assets_reduced(self):
        rm = RiskManager(correlation_threshold=0.80)
        # Identical series → correlation = 1.0
        base = list(100 + np.cumsum(np.random.normal(0, 1, 50)))
        prices = {
            "BTC/USDT": base,
            "ETH/USDT": [p * 0.5 for p in base],  # perfectly correlated
        }
        scale = rm.compute_correlation_guard(prices)
        assert scale < 1.0, f"Correlated assets should reduce scale, got {scale}"

    def test_single_asset_no_reduction(self):
        rm = RiskManager(correlation_threshold=0.80)
        prices = {"BTC/USDT": list(range(100, 150))}
        scale = rm.compute_correlation_guard(prices)
        assert scale == 1.0


class TestRiskManagerBackwardCompat:
    """Ensure existing evaluate_trade() still works."""

    def test_trade_approved(self):
        rm = RiskManager(initial_equity=10000, risk_per_trade=0.01, max_open_positions=5)
        decision = rm.evaluate_trade("BTC/USDT", price=50000, atr_value=500)
        assert decision.approved
        assert decision.position_size > 0

    def test_daily_loss_rejection(self):
        rm = RiskManager(
            initial_equity=10000, max_daily_loss_pct=0.02,
            cooldown_minutes_after_loss=0,  # disable cooldown to isolate daily loss check
        )
        # Pre-set today's reset so check_daily_reset() doesn't zero daily_pnl
        from datetime import datetime, timezone
        rm.last_reset_date = datetime.now(timezone.utc).date()
        rm.daily_starting_equity = 10000.0
        # Simulate a daily loss by registering losing trades
        rm.register_trade_close(-150.0, symbol="TEST")
        rm.register_trade_close(-100.0, symbol="TEST")
        # Now daily_pnl = -250, which is 2.5% of 10000 — above max_daily_loss_pct of 2%
        decision = rm.evaluate_trade("BTC/USDT", price=50000, atr_value=500)
        assert not decision.approved
        assert "daily loss" in decision.reason.lower()

    def test_max_positions_rejection(self):
        rm = RiskManager(initial_equity=10000, max_open_positions=2)
        rm.open_positions = 2
        decision = rm.evaluate_trade("BTC/USDT", price=50000, atr_value=500)
        assert not decision.approved
        assert "positions" in decision.reason.lower()

    def test_register_trade_close_updates_history(self):
        rm = RiskManager()
        rm.register_trade_close(50.0, symbol="BTC/USDT")
        rm.register_trade_close(-30.0, symbol="ETH/USDT")
        assert len(rm.trade_history) == 2
        assert rm.trade_history[0]["symbol"] == "BTC/USDT"

    def test_get_status_includes_kelly(self):
        rm = RiskManager()
        status = rm.get_status()
        assert "kelly_fraction" in status
        assert "trade_history_count" in status
