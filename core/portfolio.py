"""
Portfolio: Paper trading portfolio tracker.

Manages cash, positions, and equity calculations for the paper trading simulator.
Simulates order execution with slippage and commission.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents an open position."""
    id: int
    symbol: str
    side: str  # "LONG" or "SHORT"
    size: float
    entry_price: float
    stop: Optional[float] = None
    tp: Optional[float] = None
    entry_time: Optional[datetime] = None
    strategy: Optional[str] = None


class Portfolio:
    """
    Paper trading portfolio tracker.
    
    Manages cash balance, open positions, and calculates current equity
    based on mark-to-market prices. Simulates execution with slippage.
    """

    def __init__(
        self, 
        initial_cash: float = 10000.0,
        commission: float = 0.0005,
        slippage_bps: float = 2.0,
    ):
        """
        Initialize portfolio with starting cash.

        Args:
            initial_cash: Starting capital in quote currency (e.g., USDT)
            commission: Commission rate (e.g., 0.0005 = 0.05%)
            slippage_bps: Slippage in basis points (e.g., 2 = 0.02%)
        """
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage_bps = slippage_bps
        self.positions: dict[str, Position] = {}
        self._next_position_id = 1
        self.trade_history: list[dict] = []

    def _apply_slippage(self, price: float, side: str) -> float:
        """
        Apply slippage to execution price.
        
        Args:
            price: Intended execution price
            side: "BUY" or "SELL"
            
        Returns:
            Adjusted price with slippage
        """
        slippage_pct = self.slippage_bps / 10000.0
        if side == "BUY":
            return price * (1 + slippage_pct)  # Pay more
        else:
            return price * (1 - slippage_pct)  # Receive less

    def _calculate_fees(self, notional: float) -> float:
        """Calculate commission fees for a trade."""
        return notional * self.commission

    def get_equity(self, current_prices: dict[str, float]) -> float:
        """
        Calculate total equity (cash + unrealized position values).

        Args:
            current_prices: Dict of symbol -> current price

        Returns:
            Total portfolio equity
        """
        equity = self.cash
        
        for symbol, pos in self.positions.items():
            price = current_prices.get(symbol, pos.entry_price)
            
            if pos.side == "LONG":
                # Long position value = size * (current - entry)
                unrealized_pnl = pos.size * (price - pos.entry_price)
            else:
                # Short position value = size * (entry - current)
                unrealized_pnl = pos.size * (pos.entry_price - price)
            
            equity += unrealized_pnl
        
        return equity

    def has_position(self, symbol: str) -> bool:
        """Check if there's an open position for a symbol."""
        return symbol in self.positions

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get the current position for a symbol."""
        return self.positions.get(symbol)

    def open_long(
        self,
        symbol: str,
        size: float,
        price: float,
        stop: Optional[float] = None,
        tp: Optional[float] = None,
        strategy: Optional[str] = None,
    ) -> tuple[float, float, float]:
        """
        Open a long position.
        
        Args:
            symbol: Trading pair
            size: Position size in units
            price: Intended entry price
            stop: Stop loss price
            tp: Take profit price
            strategy: Strategy that generated the signal
            
        Returns:
            Tuple of (fill_price, fees, slippage)
        """
        if symbol in self.positions:
            raise ValueError(f"Position already exists for {symbol}")
        
        # Apply slippage
        fill_price = self._apply_slippage(price, "BUY")
        slippage = fill_price - price
        
        # Calculate cost and fees
        notional = size * fill_price
        fees = self._calculate_fees(notional)
        total_cost = notional + fees
        
        if total_cost > self.cash:
            raise ValueError(f"Insufficient cash: need ${total_cost:.2f}, have ${self.cash:.2f}")
        
        # Deduct from cash
        self.cash -= total_cost
        
        # Create position
        position_id = self._next_position_id
        self._next_position_id += 1
        
        self.positions[symbol] = Position(
            id=position_id,
            symbol=symbol,
            side="LONG",
            size=size,
            entry_price=fill_price,
            stop=stop,
            tp=tp,
            entry_time=datetime.utcnow(),
            strategy=strategy,
        )
        
        logger.info(f"Opened LONG {size:.6f} {symbol} @ ${fill_price:.2f} (fees: ${fees:.4f})")
        
        return fill_price, fees, slippage

    def close_long(self, symbol: str, price: float) -> tuple[float, float, float, float]:
        """
        Close a long position and return PnL.
        
        Args:
            symbol: Trading pair
            price: Intended exit price
            
        Returns:
            Tuple of (fill_price, pnl, fees, slippage)
        """
        if symbol not in self.positions:
            raise ValueError(f"No position exists for {symbol}")
        
        pos = self.positions[symbol]
        if pos.side != "LONG":
            raise ValueError(f"Position for {symbol} is not LONG")
        
        # Apply slippage (selling)
        fill_price = self._apply_slippage(price, "SELL")
        slippage = price - fill_price
        
        # Calculate proceeds
        notional = pos.size * fill_price
        fees = self._calculate_fees(notional)
        proceeds = notional - fees
        
        # Calculate PnL
        entry_cost = pos.size * pos.entry_price
        pnl = proceeds - entry_cost
        
        # Add to cash
        self.cash += proceeds
        
        # Record trade
        self.trade_history.append({
            "position_id": pos.id,
            "symbol": symbol,
            "side": "LONG",
            "entry_price": pos.entry_price,
            "exit_price": fill_price,
            "size": pos.size,
            "pnl": pnl,
            "fees": fees,
            "strategy": pos.strategy,
        })
        
        # Remove position
        del self.positions[symbol]
        
        logger.info(f"Closed LONG {pos.size:.6f} {symbol} @ ${fill_price:.2f} (PnL: ${pnl:.2f})")
        
        return fill_price, pnl, fees, slippage

    def open_short(
        self,
        symbol: str,
        size: float,
        price: float,
        stop: Optional[float] = None,
        tp: Optional[float] = None,
        strategy: Optional[str] = None,
    ) -> tuple[float, float, float]:
        """
        Open a short position.
        
        Args:
            symbol: Trading pair
            size: Position size in units
            price: Intended entry price
            stop: Stop loss price
            tp: Take profit price
            strategy: Strategy that generated the signal
            
        Returns:
            Tuple of (fill_price, fees, slippage)
        """
        if symbol in self.positions:
            raise ValueError(f"Position already exists for {symbol}")
        
        # Apply slippage (selling to open short)
        fill_price = self._apply_slippage(price, "SELL")
        slippage = price - fill_price
        
        # For shorts, we receive cash (margin not simulated in simple model)
        notional = size * fill_price
        fees = self._calculate_fees(notional)
        
        # Deduct fees from cash (margin requirement simplified)
        self.cash -= fees
        
        # Create position
        position_id = self._next_position_id
        self._next_position_id += 1
        
        self.positions[symbol] = Position(
            id=position_id,
            symbol=symbol,
            side="SHORT",
            size=size,
            entry_price=fill_price,
            stop=stop,
            tp=tp,
            entry_time=datetime.utcnow(),
            strategy=strategy,
        )
        
        logger.info(f"Opened SHORT {size:.6f} {symbol} @ ${fill_price:.2f} (fees: ${fees:.4f})")
        
        return fill_price, fees, slippage

    def close_short(self, symbol: str, price: float) -> tuple[float, float, float, float]:
        """
        Close a short position and return PnL.
        
        Args:
            symbol: Trading pair
            price: Intended exit price
            
        Returns:
            Tuple of (fill_price, pnl, fees, slippage)
        """
        if symbol not in self.positions:
            raise ValueError(f"No position exists for {symbol}")
        
        pos = self.positions[symbol]
        if pos.side != "SHORT":
            raise ValueError(f"Position for {symbol} is not SHORT")
        
        # Apply slippage (buying to close)
        fill_price = self._apply_slippage(price, "BUY")
        slippage = fill_price - price
        
        # Calculate cost to close
        notional = pos.size * fill_price
        fees = self._calculate_fees(notional)
        
        # Calculate PnL (for short: profit when price goes down)
        entry_proceeds = pos.size * pos.entry_price
        exit_cost = notional + fees
        pnl = entry_proceeds - exit_cost
        
        # Add PnL to cash
        self.cash += pnl
        
        # Record trade
        self.trade_history.append({
            "position_id": pos.id,
            "symbol": symbol,
            "side": "SHORT",
            "entry_price": pos.entry_price,
            "exit_price": fill_price,
            "size": pos.size,
            "pnl": pnl,
            "fees": fees,
            "strategy": pos.strategy,
        })
        
        # Remove position
        del self.positions[symbol]
        
        logger.info(f"Closed SHORT {pos.size:.6f} {symbol} @ ${fill_price:.2f} (PnL: ${pnl:.2f})")
        
        return fill_price, pnl, fees, slippage

    def check_stops_and_tps(self, current_prices: dict[str, float]) -> list[dict]:
        """
        Check if any positions hit stop or take profit.
        
        Args:
            current_prices: Dict of symbol -> current price
            
        Returns:
            List of positions that should be closed
        """
        to_close = []
        
        for symbol, pos in list(self.positions.items()):
            price = current_prices.get(symbol)
            if price is None:
                continue
            
            if pos.side == "LONG":
                if pos.stop and price <= pos.stop:
                    to_close.append({"symbol": symbol, "reason": "stop_loss", "price": price})
                elif pos.tp and price >= pos.tp:
                    to_close.append({"symbol": symbol, "reason": "take_profit", "price": price})
            else:  # SHORT
                if pos.stop and price >= pos.stop:
                    to_close.append({"symbol": symbol, "reason": "stop_loss", "price": price})
                elif pos.tp and price <= pos.tp:
                    to_close.append({"symbol": symbol, "reason": "take_profit", "price": price})
        
        return to_close

    def get_status(self, current_prices: dict[str, float]) -> dict:
        """Get current portfolio status."""
        equity = self.get_equity(current_prices)
        return {
            "cash": self.cash,
            "equity": equity,
            "initial_cash": self.initial_cash,
            "return_pct": (equity - self.initial_cash) / self.initial_cash * 100,
            "open_positions": len(self.positions),
            "total_trades": len(self.trade_history),
        }
