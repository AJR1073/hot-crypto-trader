"""
Tests for core/execution.py — idempotent order state machine.
"""

from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from core.execution import (
    Executor,
    ManagedOrder,
    OrderStatus,
    OrderSide,
    OrderType,
    generate_client_order_id,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@dataclass
class MockSignal:
    action: str = "HOLD"
    confidence: float = 0.8
    risk_r: float = 1.5
    extra: dict = field(default_factory=dict)


@dataclass
class MockPosition:
    side: str = "LONG"
    size: float = 0.01
    entry_price: float = 50000.0


class MockPortfolio:
    """Minimal mock of Portfolio for paper mode testing."""

    def __init__(self):
        self._positions = {}
        self._equity = 10000.0

    def open_long(self, symbol, size, price, stop=None, tp=None, strategy=None):
        self._positions[symbol] = MockPosition(side="LONG", size=size, entry_price=price)
        fees = size * price * 0.001
        slippage = price * 0.0005
        return price + slippage, fees, slippage

    def open_short(self, symbol, size, price, stop=None, tp=None, strategy=None):
        self._positions[symbol] = MockPosition(side="SHORT", size=size, entry_price=price)
        fees = size * price * 0.001
        return price - price * 0.0005, fees, price * 0.0005

    def close_long(self, symbol, price):
        pos = self._positions.pop(symbol, None)
        if not pos:
            raise ValueError(f"No position for {symbol}")
        pnl = (price - pos.entry_price) * pos.size
        return price, pnl, 0.001, 0.0

    def close_short(self, symbol, price):
        pos = self._positions.pop(symbol, None)
        if not pos:
            raise ValueError(f"No position for {symbol}")
        pnl = (pos.entry_price - price) * pos.size
        return price, pnl, 0.001, 0.0

    def get_position(self, symbol):
        return self._positions.get(symbol)

    def get_equity(self, prices=None):
        return self._equity


# ---------------------------------------------------------------------------
# clientOrderId tests
# ---------------------------------------------------------------------------

class TestClientOrderId:
    def test_format(self):
        cid = generate_client_order_id("squeeze_breakout", "BTC/USDT")
        assert cid.startswith("HOT_")
        parts = cid.split("_")
        assert len(parts) >= 4

    def test_uniqueness(self):
        ids = {generate_client_order_id("trend", "ETH/USDT") for _ in range(100)}
        assert len(ids) == 100, "Generated IDs should be unique"


# ---------------------------------------------------------------------------
# Paper mode execution
# ---------------------------------------------------------------------------

class TestPaperExecution:
    def test_open_long_paper(self):
        portfolio = MockPortfolio()
        risk_mgr = MagicMock()
        risk_mgr.evaluate_trade.return_value = MagicMock(
            approved=True, position_size=0.01, reason="OK"
        )
        risk_mgr.register_trade_open = MagicMock()

        executor = Executor(mode="paper", portfolio=portfolio, risk_manager=risk_mgr)

        signal = MockSignal(
            action="OPEN_LONG",
            extra={"stop": 49000, "tp": 52000, "atr": 500},
        )
        candle = {"close": 50000, "open": 49900, "high": 50100, "low": 49800, "volume": 100}

        result = executor.execute_signal("BTC/USDT", signal, candle, "squeeze_breakout")

        assert result is not None
        assert result["action"] == "FILLED"
        assert result["symbol"] == "BTC/USDT"
        assert result["qty"] > 0
        assert len(executor.orders) == 1

    def test_hold_signal_returns_none(self):
        executor = Executor(mode="paper", portfolio=MockPortfolio())
        signal = MockSignal(action="HOLD")
        candle = {"close": 100}
        result = executor.execute_signal("BTC/USDT", signal, candle, "test")
        assert result is None

    def test_close_long_paper(self):
        portfolio = MockPortfolio()
        portfolio._positions["BTC/USDT"] = MockPosition(
            side="LONG", size=0.01, entry_price=50000
        )

        executor = Executor(mode="paper", portfolio=portfolio)
        signal = MockSignal(action="CLOSE_LONG", extra={"reason": "TP hit"})
        candle = {"close": 51000}

        result = executor.execute_signal("BTC/USDT", signal, candle, "test")
        assert result is not None
        assert result["action"] == "CLOSED"
        assert result["pnl"] > 0

    def test_circuit_breaker_blocks_open(self):
        portfolio = MockPortfolio()
        cb = MagicMock()
        cb.check.return_value = (False, "Portfolio kill switch")

        executor = Executor(mode="paper", portfolio=portfolio, circuit_breaker=cb)
        signal = MockSignal(
            action="OPEN_LONG",
            extra={"stop": 49000, "tp": 52000, "atr": 500},
        )
        candle = {"close": 50000}
        result = executor.execute_signal("BTC/USDT", signal, candle, "test")
        assert result["action"] == "REJECTED"


# ---------------------------------------------------------------------------
# Order state machine
# ---------------------------------------------------------------------------

class TestOrderStateMachine:
    def test_pending_to_filled(self):
        order = ManagedOrder(
            client_order_id="HOT_TEST_001",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=0.01,
            price=50000.0,
            strategy="test",
        )
        assert order.status == OrderStatus.PENDING
        assert not order.is_terminal

        order.status = OrderStatus.SUBMITTED
        assert not order.is_terminal

        order.status = OrderStatus.FILLED
        order.filled_qty = 0.01
        assert order.is_terminal
        assert order.remaining_qty == 0.0

    def test_partial_fill_tracking(self):
        order = ManagedOrder(
            client_order_id="HOT_TEST_002",
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=1.0,
            price=3000.0,
            strategy="test",
        )
        order.filled_qty = 0.6
        order.status = OrderStatus.PARTIAL
        assert order.remaining_qty == pytest.approx(0.4, abs=0.01)
        assert not order.is_terminal

    def test_to_dict(self):
        order = ManagedOrder(
            client_order_id="HOT_TEST_003",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=0.5,
            price=None,
            strategy="trend",
        )
        d = order.to_dict()
        assert d["symbol"] == "BTC/USDT"
        assert d["side"] == "buy"
        assert d["type"] == "market"


# ---------------------------------------------------------------------------
# Executor status
# ---------------------------------------------------------------------------

class TestExecutorStatus:
    def test_status_empty(self):
        executor = Executor(mode="paper")
        status = executor.get_status()
        assert status["total_orders"] == 0
        assert status["mode"] == "paper"

    def test_status_after_trades(self):
        portfolio = MockPortfolio()
        risk_mgr = MagicMock()
        risk_mgr.evaluate_trade.return_value = MagicMock(
            approved=True, position_size=0.01, reason="OK"
        )
        risk_mgr.register_trade_open = MagicMock()

        executor = Executor(mode="paper", portfolio=portfolio, risk_manager=risk_mgr)
        signal = MockSignal(
            action="OPEN_LONG",
            extra={"stop": 49000, "tp": 52000, "atr": 500},
        )
        candle = {"close": 50000}
        executor.execute_signal("BTC/USDT", signal, candle, "test")

        status = executor.get_status()
        assert status["total_orders"] == 1
        assert status["filled"] == 1
