"""
Tests for core/circuit_breaker.py — all four breaker types.
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from core.circuit_breaker import CircuitBreaker, BreakerTrip


class TestAssetLevelBreaker:
    def test_no_trip_within_threshold(self):
        cb = CircuitBreaker(asset_drop_pct=0.15, flash_crash_pct=0.99)
        # Record prices: 100 → 90 (10% drop, under 15%)
        cb.record_price("BTC/USDT", 100.0)
        allowed, reason = cb.check("BTC/USDT", 90.0)
        assert allowed, f"10% drop should be under 15% threshold: {reason}"

    def test_trip_at_threshold(self):
        cb = CircuitBreaker(asset_drop_pct=0.15, flash_crash_pct=0.99)
        cb.record_price("BTC/USDT", 100.0)
        allowed, reason = cb.check("BTC/USDT", 84.0)  # 16% drop
        assert not allowed
        assert "15%" in reason or "asset" in reason.lower()

    def test_trip_blocks_subsequent_checks(self):
        cb = CircuitBreaker(asset_drop_pct=0.15, flash_crash_pct=0.99)
        cb.record_price("BTC/USDT", 100.0)
        cb.check("BTC/USDT", 84.0)  # triggers trip
        # Even at a normal price, should still be blocked
        allowed, reason = cb.check("BTC/USDT", 95.0)
        assert not allowed
        assert "Circuit breaker active" in reason


class TestPortfolioKillSwitch:
    def test_no_kill_within_threshold(self):
        cb = CircuitBreaker(portfolio_kill_pct=0.10)
        cb.reset_daily(10000.0)
        allowed, reason = cb.check("BTC/USDT", 100.0, portfolio_value=9500)
        assert allowed, f"5% drawdown should be OK: {reason}"

    def test_kill_switch_triggers(self):
        cb = CircuitBreaker(portfolio_kill_pct=0.10)
        cb.reset_daily(10000.0)
        allowed, reason = cb.check("BTC/USDT", 100.0, portfolio_value=8900)
        assert not allowed
        assert "kill switch" in reason.lower() or "portfolio" in reason.lower()

    def test_kill_switch_blocks_all_symbols(self):
        cb = CircuitBreaker(portfolio_kill_pct=0.10)
        cb.reset_daily(10000.0)
        cb.check("BTC/USDT", 100.0, portfolio_value=8900)  # triggers
        # Even a different symbol should be blocked
        allowed, reason = cb.check("ETH/USDT", 3000.0, portfolio_value=8900)
        assert not allowed


class TestConsecutiveLossBreaker:
    def test_no_trip_below_limit(self):
        cb = CircuitBreaker(consecutive_loss_limit=3)
        cb.register_trade_result(-10.0)
        cb.register_trade_result(-15.0)
        allowed, reason = cb.check("BTC/USDT", 100.0)
        assert allowed, "2 losses should be under 3-loss limit"

    def test_trip_at_limit(self):
        cb = CircuitBreaker(consecutive_loss_limit=3, consecutive_cooldown_minutes=30)
        cb.register_trade_result(-10.0)
        cb.register_trade_result(-15.0)
        cb.register_trade_result(-20.0)  # 3rd loss
        allowed, reason = cb.check("BTC/USDT", 100.0)
        assert not allowed
        assert "consecutive" in reason.lower()

    def test_win_resets_counter(self):
        cb = CircuitBreaker(consecutive_loss_limit=3)
        cb.register_trade_result(-10.0)
        cb.register_trade_result(-15.0)
        cb.register_trade_result(50.0)  # win resets
        cb.register_trade_result(-10.0)
        allowed, reason = cb.check("BTC/USDT", 100.0)
        assert allowed


class TestFlashCrashDetector:
    def test_no_trip_for_normal_move(self):
        cb = CircuitBreaker(flash_crash_pct=0.05, flash_crash_window_seconds=60, asset_drop_pct=0.99)
        cb.record_price("BTC/USDT", 100.0)
        allowed, reason = cb.check("BTC/USDT", 97.0)  # 3% move
        assert allowed

    def test_trip_on_flash_crash(self):
        cb = CircuitBreaker(flash_crash_pct=0.05, flash_crash_window_seconds=60, asset_drop_pct=0.99)
        cb.record_price("BTC/USDT", 100.0)
        allowed, reason = cb.check("BTC/USDT", 94.0)  # 6% drop
        assert not allowed
        assert "flash" in reason.lower()


class TestBreakerTrip:
    def test_trip_is_active(self):
        trip = BreakerTrip(
            breaker_type="test",
            symbol="BTC/USDT",
            triggered_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            reason="test trip",
        )
        assert trip.is_active

    def test_trip_expired(self):
        trip = BreakerTrip(
            breaker_type="test",
            symbol=None,
            triggered_at=datetime.now(timezone.utc) - timedelta(hours=2),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            reason="old trip",
        )
        assert not trip.is_active


class TestBreakerStatus:
    def test_get_status(self):
        cb = CircuitBreaker()
        status = cb.get_status()
        assert "active_trips" in status
        assert "consecutive_losses" in status

    def test_get_active_trips_empty(self):
        cb = CircuitBreaker()
        assert len(cb.get_active_trips()) == 0
