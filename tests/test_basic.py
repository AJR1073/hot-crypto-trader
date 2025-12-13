"""
Basic tests for HOT-Crypto trading engine.
"""

import pytest


class TestStrategySignal:
    """Tests for StrategySignal dataclass."""

    def test_signal_creation(self):
        """Test creating a basic signal."""
        from strategies.base import StrategySignal
        
        signal = StrategySignal(
            symbol="BTC/USDT",
            action="OPEN_LONG",
            risk_r=1.0,
        )
        
        assert signal.symbol == "BTC/USDT"
        assert signal.action == "OPEN_LONG"
        assert signal.risk_r == 1.0
        assert signal.extra == {}

    def test_signal_with_extra(self):
        """Test signal with extra data."""
        from strategies.base import StrategySignal
        
        signal = StrategySignal(
            symbol="ETH/USDT",
            action="OPEN_LONG",
            extra={"stop": 2800.0, "tp": 3200.0},
        )
        
        assert signal.extra["stop"] == 2800.0
        assert signal.extra["tp"] == 3200.0


class TestDatabaseInit:
    """Tests for database initialization."""

    def test_get_db_url_default(self):
        """Test default database URL."""
        from db.init_db import get_db_url
        
        # Without env var or argument, should return default
        url = get_db_url()
        assert "sqlite" in url

    def test_get_db_url_explicit(self):
        """Test explicit database URL."""
        from db.init_db import get_db_url
        
        url = get_db_url("sqlite:///custom.db")
        assert url == "sqlite:///custom.db"


class TestBaseStrategy:
    """Tests for BaseStrategy class."""

    def test_init_symbol(self):
        """Test symbol initialization."""
        from strategies.base import BaseStrategy
        
        class TestStrategy(BaseStrategy):
            def on_bar(self, symbol, candle):
                pass
        
        strategy = TestStrategy({})
        strategy.init_symbol("BTC/USDT")
        
        assert "BTC/USDT" in strategy.state
        assert strategy.state["BTC/USDT"]["df"] is None
