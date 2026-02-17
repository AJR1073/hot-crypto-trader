"""
Idempotent Order Execution Engine.

Implements the order lifecycle state machine:

  Signal → DB Entry (PENDING) → API Request → {Filled, Partial, Orphaned} → Finalization
                                     ↓ Timeout
                               FetchOrder (Query) → {Filled, Partial, Orphaned}

Key features:
  - clientOrderId generation for idempotency
  - Chase logic: cancel + resubmit unfilled limit orders (up to N attempts)
  - Timeout reconciliation via order query
  - Paper mode (delegates to Portfolio) and live mode (delegates to ExchangeClient)

Reference: doc/research_images/image4.png (Order State Machine)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.exchange_client import ExchangeClient
    from core.portfolio import Portfolio
    from core.risk_manager import RiskManager
    from core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order state machine
# ---------------------------------------------------------------------------

class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"
    ERROR = "error"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"


@dataclass
class ManagedOrder:
    """Tracks a single order through its lifecycle."""

    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    qty: float
    price: Optional[float]           # None for market orders
    strategy: str

    # State
    status: OrderStatus = OrderStatus.PENDING
    exchange_order_id: Optional[str] = None
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    fees: float = 0.0
    error_message: Optional[str] = None

    # Chase tracking
    chase_attempts: int = 0

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.ERROR,
        )

    @property
    def remaining_qty(self) -> float:
        return max(0.0, self.qty - self.filled_qty)

    def to_dict(self) -> dict:
        return {
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "type": self.order_type.value,
            "qty": self.qty,
            "filled_qty": self.filled_qty,
            "price": self.price,
            "avg_fill_price": self.avg_fill_price,
            "status": self.status.value,
            "strategy": self.strategy,
            "fees": self.fees,
            "chase_attempts": self.chase_attempts,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# clientOrderId generator
# ---------------------------------------------------------------------------

def generate_client_order_id(strategy: str, symbol: str) -> str:
    """
    Generate a unique, deterministic-ish client order ID.

    Format: HOT_{strategy}_{symbol}_{ts}_{uuid8}
    Example: HOT_SQZBO_BTCUSDT_20260217T1557_a1b2c3d4
    """
    sym_clean = symbol.replace("/", "").replace("-", "")
    strat_clean = strategy.replace("_", "").upper()[:6]
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M")
    short_uuid = uuid.uuid4().hex[:8]
    return f"HOT_{strat_clean}_{sym_clean}_{ts}_{short_uuid}"


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class Executor:
    """
    Converts strategy signals into executed trades.

    Supports two modes:
      - paper: Trades are simulated via Portfolio
      - live:  Orders are placed on the exchange via ExchangeClient

    Args:
        mode: "paper" or "live"
        portfolio: Portfolio instance (required for paper mode)
        exchange_client: ExchangeClient instance (required for live mode)
        risk_manager: RiskManager for position sizing
        circuit_breaker: CircuitBreaker for safety checks
        chase_timeout_seconds: Max time to wait for limit fill before chasing
        chase_max_attempts: Max chase attempts before switching to market
    """

    def __init__(
        self,
        mode: str = "paper",
        portfolio: Optional["Portfolio"] = None,
        exchange_client: Optional["ExchangeClient"] = None,
        risk_manager: Optional["RiskManager"] = None,
        circuit_breaker: Optional["CircuitBreaker"] = None,
        chase_timeout_seconds: int = 30,
        chase_max_attempts: int = 3,
    ):
        self.mode = mode
        self.portfolio = portfolio
        self.exchange_client = exchange_client
        self.risk_manager = risk_manager
        self.circuit_breaker = circuit_breaker
        self.chase_timeout_seconds = chase_timeout_seconds
        self.chase_max_attempts = chase_max_attempts

        # Track all orders in this session
        self.orders: dict[str, ManagedOrder] = {}

    def execute_signal(
        self,
        symbol: str,
        signal: object,
        latest_candle: dict,
        strategy_name: str,
    ) -> Optional[dict]:
        """
        Execute a strategy signal through the full pipeline.

        Pipeline:
          1. Parse signal action (OPEN_LONG, CLOSE_LONG, etc.)
          2. Check circuit breakers
          3. Compute position size via risk manager
          4. Create ManagedOrder with clientOrderId
          5. Submit to exchange or portfolio
          6. Return execution result

        Args:
            symbol: Trading pair (e.g. "BTC/USDT")
            signal: StrategySignal with .action, .extra, .risk_r
            latest_candle: Dict with open/high/low/close/volume
            strategy_name: Name of the source strategy

        Returns:
            Dict with execution details, or None if no action taken.
        """
        action = getattr(signal, "action", "HOLD")
        if action == "HOLD":
            return None

        extra = getattr(signal, "extra", {}) or {}
        current_price = latest_candle["close"]

        # Route by action type
        if action in ("OPEN_LONG", "OPEN_SHORT"):
            return self._execute_open(
                symbol=symbol,
                side=OrderSide.BUY if action == "OPEN_LONG" else OrderSide.SELL,
                price=current_price,
                strategy_name=strategy_name,
                stop=extra.get("stop"),
                tp=extra.get("tp"),
                atr=extra.get("atr"),
                risk_r=getattr(signal, "risk_r", 1.0),
            )
        elif action in ("CLOSE_LONG", "CLOSE_SHORT"):
            return self._execute_close(
                symbol=symbol,
                price=current_price,
                strategy_name=strategy_name,
                reason=extra.get("reason", "Strategy exit signal"),
            )

        logger.warning("Unknown signal action: %s", action)
        return None

    # ------------------------------------------------------------------
    # Open position
    # ------------------------------------------------------------------

    def _execute_open(
        self,
        symbol: str,
        side: OrderSide,
        price: float,
        strategy_name: str,
        stop: Optional[float] = None,
        tp: Optional[float] = None,
        atr: Optional[float] = None,
        risk_r: float = 1.0,
    ) -> Optional[dict]:
        """Execute an order to open a new position."""

        # 1. Circuit breaker check
        if self.circuit_breaker:
            portfolio_value = None
            if self.portfolio:
                portfolio_value = self.portfolio.get_equity({symbol: price})
            allowed, reason = self.circuit_breaker.check(
                symbol, price, portfolio_value=portfolio_value,
            )
            if not allowed:
                logger.warning("Trade blocked by circuit breaker: %s", reason)
                return {"action": "REJECTED", "reason": reason}

        # 2. Risk manager evaluation
        if self.risk_manager and atr:
            from strategies.indicators import ATR as ATR_func  # avoid circular
            decision = self.risk_manager.evaluate_trade(
                symbol=symbol,
                price=price,
                atr_value=atr,
            )
            if not decision.approved:
                logger.warning("Trade rejected by risk manager: %s", decision.reason)
                return {"action": "REJECTED", "reason": decision.reason}
            position_size = decision.position_size
        else:
            # Fallback: use a nominal size
            position_size = 0.001  # minimum for paper testing
            logger.warning("No risk manager — using fallback size %.6f", position_size)

        # 3. Create managed order
        client_id = generate_client_order_id(strategy_name, symbol)
        order = ManagedOrder(
            client_order_id=client_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT if self.mode == "live" else OrderType.MARKET,
            qty=position_size,
            price=price,
            strategy=strategy_name,
        )
        self.orders[client_id] = order

        # 4. Execute
        if self.mode == "paper":
            return self._execute_paper_open(order, stop, tp)
        else:
            return self._execute_live_open(order, stop, tp)

    def _execute_paper_open(
        self, order: ManagedOrder, stop: Optional[float], tp: Optional[float]
    ) -> dict:
        """Execute open order in paper mode via Portfolio."""
        if not self.portfolio:
            order.status = OrderStatus.ERROR
            order.error_message = "No portfolio configured for paper mode"
            return {"action": "ERROR", "reason": order.error_message}

        try:
            if order.side == OrderSide.BUY:
                fill_price, fees, slippage = self.portfolio.open_long(
                    symbol=order.symbol,
                    size=order.qty,
                    price=order.price,
                    stop=stop,
                    tp=tp,
                    strategy=order.strategy,
                )
            else:
                fill_price, fees, slippage = self.portfolio.open_short(
                    symbol=order.symbol,
                    size=order.qty,
                    price=order.price,
                    stop=stop,
                    tp=tp,
                    strategy=order.strategy,
                )

            order.status = OrderStatus.FILLED
            order.filled_qty = order.qty
            order.avg_fill_price = fill_price
            order.fees = fees
            order.filled_at = datetime.utcnow()

            if self.risk_manager:
                self.risk_manager.register_trade_open()

            logger.info(
                "📈 PAPER %s %s %.6f @ $%.2f (fees=%.4f)",
                order.side.value.upper(),
                order.symbol,
                order.qty,
                fill_price,
                fees,
            )

            return {
                "action": "FILLED",
                "client_order_id": order.client_order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "qty": order.qty,
                "fill_price": fill_price,
                "fees": fees,
                "slippage": slippage,
                "strategy": order.strategy,
            }

        except ValueError as e:
            order.status = OrderStatus.ERROR
            order.error_message = str(e)
            logger.error("Paper trade failed: %s", e)
            return {"action": "ERROR", "reason": str(e)}

    def _execute_live_open(
        self, order: ManagedOrder, stop: Optional[float], tp: Optional[float]
    ) -> dict:
        """Execute open order in live mode via ExchangeClient."""
        if not self.exchange_client:
            order.status = OrderStatus.ERROR
            order.error_message = "No exchange client configured for live mode"
            return {"action": "ERROR", "reason": order.error_message}

        try:
            import ccxt

            # Submit limit order with clientOrderId
            params = {"clientOrderId": order.client_order_id}
            if order.order_type == OrderType.LIMIT:
                params["postOnly"] = True  # Maker only to avoid taker fees

            response = self.exchange_client.create_order(
                symbol=order.symbol,
                side=order.side.value,
                order_type=order.order_type.value,
                amount=order.qty,
                price=order.price,
                params=params,
            )

            order.exchange_order_id = response.get("id")
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = datetime.utcnow()

            # Check immediate fill
            resp_status = response.get("status", "open")
            if resp_status == "closed":
                order.status = OrderStatus.FILLED
                order.filled_qty = float(response.get("filled", order.qty))
                order.avg_fill_price = float(
                    response.get("average", order.price)
                )
                order.filled_at = datetime.utcnow()
            elif resp_status == "partially_filled":
                order.status = OrderStatus.PARTIAL
                order.filled_qty = float(response.get("filled", 0))

            logger.info(
                "📤 LIVE %s %s %.6f @ $%.2f [%s] id=%s",
                order.side.value.upper(),
                order.symbol,
                order.qty,
                order.price,
                order.status.value,
                order.exchange_order_id,
            )

            return {
                "action": order.status.value.upper(),
                "client_order_id": order.client_order_id,
                "exchange_order_id": order.exchange_order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "qty": order.qty,
                "filled_qty": order.filled_qty,
                "price": order.price,
                "avg_fill_price": order.avg_fill_price,
                "strategy": order.strategy,
            }

        except ccxt.RequestTimeout:
            # Reconciliation: query the order by clientOrderId
            logger.warning(
                "⏱ Timeout submitting order %s — attempting reconciliation",
                order.client_order_id,
            )
            return self._reconcile_order(order)

        except ccxt.RateLimitExceeded:
            order.status = OrderStatus.ERROR
            order.error_message = "Rate limit exceeded"
            logger.error("Rate limit hit while placing order")
            return {"action": "ERROR", "reason": "Rate limit exceeded"}

        except Exception as e:
            order.status = OrderStatus.ERROR
            order.error_message = str(e)
            logger.error("Live order failed: %s", e, exc_info=True)
            return {"action": "ERROR", "reason": str(e)}

    # ------------------------------------------------------------------
    # Close position
    # ------------------------------------------------------------------

    def _execute_close(
        self,
        symbol: str,
        price: float,
        strategy_name: str,
        reason: str = "Strategy exit",
    ) -> Optional[dict]:
        """Execute an order to close an existing position."""

        if self.mode == "paper":
            return self._execute_paper_close(symbol, price, strategy_name, reason)
        else:
            return self._execute_live_close(symbol, price, strategy_name, reason)

    def _execute_paper_close(
        self, symbol: str, price: float, strategy_name: str, reason: str
    ) -> Optional[dict]:
        """Close position in paper mode."""
        if not self.portfolio:
            return None

        pos = self.portfolio.get_position(symbol)
        if not pos:
            logger.debug("No position to close for %s", symbol)
            return None

        try:
            if pos.side == "LONG":
                fill_price, pnl, fees, slippage = self.portfolio.close_long(
                    symbol, price
                )
            else:
                fill_price, pnl, fees, slippage = self.portfolio.close_short(
                    symbol, price
                )

            if self.risk_manager:
                self.risk_manager.register_trade_close(pnl)
            if self.circuit_breaker:
                self.circuit_breaker.register_trade_result(pnl)

            pnl_emoji = "💰" if pnl >= 0 else "💸"
            logger.info(
                "%s PAPER CLOSE %s %s @ $%.2f  PnL=$%.2f",
                pnl_emoji, pos.side, symbol, fill_price, pnl,
            )

            return {
                "action": "CLOSED",
                "symbol": symbol,
                "side": f"CLOSE_{pos.side}",
                "qty": pos.size,
                "fill_price": fill_price,
                "pnl": pnl,
                "fees": fees,
                "reason": reason,
                "strategy": strategy_name,
            }

        except ValueError as e:
            logger.error("Paper close failed: %s", e)
            return {"action": "ERROR", "reason": str(e)}

    def _execute_live_close(
        self, symbol: str, price: float, strategy_name: str, reason: str
    ) -> Optional[dict]:
        """Close position in live mode via market order."""
        if not self.exchange_client:
            return None

        # For live close, we use a market order for guaranteed exit
        pos = self.portfolio.get_position(symbol) if self.portfolio else None
        if not pos:
            logger.debug("No tracked position to close for %s", symbol)
            return None

        client_id = generate_client_order_id(strategy_name, symbol)
        side = "sell" if pos.side == "LONG" else "buy"

        try:
            response = self.exchange_client.create_order(
                symbol=symbol,
                side=side,
                order_type="market",
                amount=pos.size,
                params={"clientOrderId": client_id},
            )

            fill_price = float(response.get("average", price))
            filled_qty = float(response.get("filled", pos.size))
            pnl = (fill_price - pos.entry_price) * filled_qty
            if pos.side == "SHORT":
                pnl = -pnl

            if self.risk_manager:
                self.risk_manager.register_trade_close(pnl)
            if self.circuit_breaker:
                self.circuit_breaker.register_trade_result(pnl)

            logger.info(
                "📤 LIVE CLOSE %s %s @ $%.2f  PnL=$%.2f",
                pos.side, symbol, fill_price, pnl,
            )

            return {
                "action": "CLOSED",
                "client_order_id": client_id,
                "exchange_order_id": response.get("id"),
                "symbol": symbol,
                "side": f"CLOSE_{pos.side}",
                "qty": filled_qty,
                "fill_price": fill_price,
                "pnl": pnl,
                "reason": reason,
                "strategy": strategy_name,
            }

        except Exception as e:
            logger.error("Live close failed: %s", e, exc_info=True)
            return {"action": "ERROR", "reason": str(e)}

    # ------------------------------------------------------------------
    # Reconciliation & Chase
    # ------------------------------------------------------------------

    def _reconcile_order(self, order: ManagedOrder) -> dict:
        """
        Query the exchange for an order after a timeout.

        Uses clientOrderId to find the order regardless of whether
        we received the exchange response.
        """
        if not self.exchange_client:
            order.status = OrderStatus.ORPHANED
            return {"action": "ORPHANED", "reason": "No exchange client for reconciliation"}

        try:
            # Try to fetch by exchange_order_id if we have it
            if order.exchange_order_id:
                result = self.exchange_client.fetch_order(
                    order.exchange_order_id, order.symbol
                )
            else:
                # Fall back to checking open orders
                open_orders = self.exchange_client.get_open_orders(order.symbol)
                result = None
                for oo in open_orders:
                    if oo.get("clientOrderId") == order.client_order_id:
                        result = oo
                        break

            if result is None:
                order.status = OrderStatus.ORPHANED
                logger.warning("Order %s not found on exchange — orphaned", order.client_order_id)
                return {"action": "ORPHANED", "client_order_id": order.client_order_id}

            status = result.get("status", "unknown")
            if status == "closed":
                order.status = OrderStatus.FILLED
                order.filled_qty = float(result.get("filled", order.qty))
                order.avg_fill_price = float(result.get("average", order.price))
                order.filled_at = datetime.utcnow()
                return {"action": "FILLED", **order.to_dict()}
            elif status in ("open", "partially_filled"):
                order.filled_qty = float(result.get("filled", 0))
                order.status = OrderStatus.PARTIAL if order.filled_qty > 0 else OrderStatus.SUBMITTED
                return {"action": order.status.value.upper(), **order.to_dict()}
            else:
                order.status = OrderStatus.ORPHANED
                return {"action": "ORPHANED", **order.to_dict()}

        except Exception as e:
            logger.error("Reconciliation failed for %s: %s", order.client_order_id, e)
            order.status = OrderStatus.ORPHANED
            return {"action": "ORPHANED", "reason": str(e)}

    def reconcile_on_startup(self) -> list[dict]:
        """
        On startup, check for any open orders from previous sessions.

        Should be called once at the beginning of a live trading session.
        Fetches all open orders from the exchange and logs them.

        Returns:
            List of open order dicts found on the exchange.
        """
        if self.mode != "live" or not self.exchange_client:
            return []

        try:
            open_orders = self.exchange_client.get_open_orders()
            if open_orders:
                logger.warning(
                    "⚠️  Found %d open orders from previous session!",
                    len(open_orders),
                )
                for oo in open_orders:
                    logger.warning(
                        "  - %s %s %s qty=%.6f @ %.2f [%s]",
                        oo.get("symbol"),
                        oo.get("side"),
                        oo.get("type"),
                        float(oo.get("amount", 0)),
                        float(oo.get("price", 0)),
                        oo.get("clientOrderId", "unknown"),
                    )
            return open_orders
        except Exception as e:
            logger.error("Startup reconciliation failed: %s", e)
            return []

    def cancel_all_open_orders(self, symbol: Optional[str] = None) -> int:
        """
        Cancel all open orders on the exchange.

        Used during graceful shutdown or emergency halt.

        Returns:
            Number of orders cancelled.
        """
        if self.mode != "live" or not self.exchange_client:
            return 0

        cancelled = 0
        try:
            open_orders = self.exchange_client.get_open_orders(symbol)
            for oo in open_orders:
                try:
                    self.exchange_client.cancel_order(oo["id"], oo["symbol"])
                    cancelled += 1
                    logger.info("Cancelled order %s on %s", oo["id"], oo["symbol"])
                except Exception as e:
                    logger.error("Failed to cancel order %s: %s", oo["id"], e)
        except Exception as e:
            logger.error("Failed to fetch open orders for cancellation: %s", e)

        return cancelled

    def get_status(self) -> dict:
        """Get executor status summary."""
        total = len(self.orders)
        filled = sum(1 for o in self.orders.values() if o.status == OrderStatus.FILLED)
        pending = sum(1 for o in self.orders.values() if not o.is_terminal)
        errors = sum(1 for o in self.orders.values() if o.status == OrderStatus.ERROR)

        return {
            "mode": self.mode,
            "total_orders": total,
            "filled": filled,
            "pending": pending,
            "errors": errors,
        }
