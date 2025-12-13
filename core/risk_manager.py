"""
RiskManager: Position sizing and risk limit enforcement.

Implements risk management rules including:
- Position sizing based on ATR and risk percentage
- Daily loss limits
- Maximum open positions
- Total drawdown limits
- Cooldown after losses
- ATR filter for volatility
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class RiskDecision:
    """Result of a risk check."""
    
    def __init__(self, approved: bool, reason: str = "", position_size: float = 0.0):
        self.approved = approved
        self.reason = reason
        self.position_size = position_size
    
    def __repr__(self) -> str:
        status = "APPROVED" if self.approved else "REJECTED"
        return f"<RiskDecision {status}: {self.reason}>"


class RiskManager:
    """
    Risk manager for position sizing and loss limits.
    
    Enforces risk rules to prevent excessive losses and ensure
    consistent position sizing across strategies.
    """

    def __init__(
        self,
        initial_equity: float = 10000.0,
        risk_per_trade: float = 0.005,
        max_open_positions: int = 2,
        max_daily_loss_pct: float = 0.02,
        max_total_drawdown_pct: float = 0.10,
        cooldown_minutes_after_loss: int = 240,
        min_atr_pct_filter: float = 0.003,
        spread_guard_bps: float = 10.0,
    ):
        """
        Initialize risk manager.

        Args:
            initial_equity: Starting account equity
            risk_per_trade: Risk as fraction of equity per trade (e.g., 0.005 = 0.5%)
            max_open_positions: Maximum concurrent open positions
            max_daily_loss_pct: Maximum daily loss before stopping (e.g., 0.02 = 2%)
            max_total_drawdown_pct: Maximum total drawdown from peak (e.g., 0.10 = 10%)
            cooldown_minutes_after_loss: Minutes to wait after a loss
            min_atr_pct_filter: Minimum ATR as % of price (skip low volatility)
            spread_guard_bps: Maximum spread in basis points
        """
        self.initial_equity = initial_equity
        self.risk_per_trade = risk_per_trade
        self.max_open_positions = max_open_positions
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_total_drawdown_pct = max_total_drawdown_pct
        self.cooldown_minutes = cooldown_minutes_after_loss
        self.min_atr_pct_filter = min_atr_pct_filter
        self.spread_guard_bps = spread_guard_bps
        
        # State tracking
        self.current_equity = initial_equity
        self.peak_equity = initial_equity
        self.daily_starting_equity = initial_equity
        self.daily_pnl = 0.0
        self.open_positions = 0
        self.last_loss_time: Optional[datetime] = None
        self.consecutive_losses = 0
        self.last_reset_date: Optional[datetime] = None
        
    def update_equity(self, equity: float) -> None:
        """Update current equity and peak."""
        self.current_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity
    
    def reset_daily(self, equity: float) -> None:
        """Reset daily tracking (call at start of each UTC day)."""
        self.daily_pnl = 0.0
        self.daily_starting_equity = equity
        self.last_reset_date = datetime.utcnow().date()
        logger.info(f"Daily reset: equity=${equity:.2f}")
    
    def check_daily_reset(self) -> None:
        """Check if we need to reset daily tracking."""
        today = datetime.utcnow().date()
        if self.last_reset_date != today:
            self.reset_daily(self.current_equity)
    
    def compute_position_size(
        self,
        price: float,
        atr_value: float,
        atr_stop_mult: float = 1.5,
    ) -> Tuple[float, float, float]:
        """
        Compute position size based on risk parameters.

        Args:
            price: Current asset price
            atr_value: Current ATR value
            atr_stop_mult: Multiplier for ATR-based stop distance

        Returns:
            Tuple of (position_size_units, stop_price, take_profit_price)
        """
        # Risk per trade in dollars
        risk_dollars = self.current_equity * self.risk_per_trade
        
        # Stop distance
        stop_distance = atr_value * atr_stop_mult
        stop_price = price - stop_distance
        
        # Position size: risk_dollars / stop_distance
        if stop_distance > 0:
            position_units = risk_dollars / stop_distance
        else:
            position_units = 0.0
        
        # Take profit at 2:1 RR
        tp_price = price + (stop_distance * 2)
        
        return position_units, stop_price, tp_price
    
    def evaluate_trade(
        self,
        symbol: str,
        price: float,
        atr_value: float,
        atr_stop_mult: float = 1.5,
        spread_bps: Optional[float] = None,
    ) -> RiskDecision:
        """
        Evaluate whether a trade is allowed and compute position size.

        Args:
            symbol: Trading pair
            price: Current price
            atr_value: Current ATR value
            atr_stop_mult: ATR multiplier for stop
            spread_bps: Current spread in basis points (optional)

        Returns:
            RiskDecision with approval status and position size
        """
        self.check_daily_reset()
        
        # Check daily loss limit
        daily_loss_pct = abs(self.daily_pnl) / self.daily_starting_equity if self.daily_starting_equity > 0 else 0
        if self.daily_pnl < 0 and daily_loss_pct >= self.max_daily_loss_pct:
            return RiskDecision(
                approved=False,
                reason=f"Daily loss limit reached: {daily_loss_pct*100:.2f}% >= {self.max_daily_loss_pct*100:.1f}%"
            )
        
        # Check total drawdown
        drawdown_pct = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity > 0 else 0
        if drawdown_pct >= self.max_total_drawdown_pct:
            return RiskDecision(
                approved=False,
                reason=f"Max drawdown reached: {drawdown_pct*100:.2f}% >= {self.max_total_drawdown_pct*100:.1f}%"
            )
        
        # Check max open positions
        if self.open_positions >= self.max_open_positions:
            return RiskDecision(
                approved=False,
                reason=f"Max positions reached: {self.open_positions} >= {self.max_open_positions}"
            )
        
        # Check cooldown after loss
        if self.last_loss_time:
            cooldown_end = self.last_loss_time + timedelta(minutes=self.cooldown_minutes)
            if datetime.utcnow() < cooldown_end:
                remaining = (cooldown_end - datetime.utcnow()).total_seconds() / 60
                return RiskDecision(
                    approved=False,
                    reason=f"Cooldown active: {remaining:.0f} minutes remaining after loss"
                )
        
        # Check ATR filter (volatility too low)
        atr_pct = atr_value / price if price > 0 else 0
        if atr_pct < self.min_atr_pct_filter:
            return RiskDecision(
                approved=False,
                reason=f"ATR too low: {atr_pct*100:.3f}% < {self.min_atr_pct_filter*100:.2f}%"
            )
        
        # Check spread guard
        if spread_bps is not None and spread_bps > self.spread_guard_bps:
            return RiskDecision(
                approved=False,
                reason=f"Spread too wide: {spread_bps:.1f} bps > {self.spread_guard_bps:.1f} bps"
            )
        
        # Compute position size
        position_size, stop_price, tp_price = self.compute_position_size(
            price=price,
            atr_value=atr_value,
            atr_stop_mult=atr_stop_mult,
        )
        
        # Check if position size is meaningful
        if position_size <= 0:
            return RiskDecision(
                approved=False,
                reason="Position size calculated as zero or negative"
            )
        
        # Cap position size at 50% of equity
        max_position_value = self.current_equity * 0.5
        max_units = max_position_value / price if price > 0 else 0
        position_size = min(position_size, max_units)
        
        return RiskDecision(
            approved=True,
            reason=f"Trade approved: {position_size:.6f} units, stop=${stop_price:.2f}",
            position_size=position_size,
        )
    
    def register_trade_open(self) -> None:
        """Register that a new position was opened."""
        self.open_positions += 1
        logger.debug(f"Position opened. Open positions: {self.open_positions}")
    
    def register_trade_close(self, pnl: float) -> None:
        """
        Register a completed trade's PnL.

        Args:
            pnl: Profit/loss from the trade
        """
        self.open_positions = max(0, self.open_positions - 1)
        self.daily_pnl += pnl
        self.current_equity += pnl
        
        if pnl >= 0:
            self.consecutive_losses = 0
            self.last_loss_time = None
        else:
            self.consecutive_losses += 1
            self.last_loss_time = datetime.utcnow()
        
        # Update peak
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        
        logger.debug(f"Trade closed. PnL: ${pnl:.2f}, Daily PnL: ${self.daily_pnl:.2f}, "
                    f"Equity: ${self.current_equity:.2f}")
    
    def get_status(self) -> dict:
        """Get current risk status."""
        drawdown_pct = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity > 0 else 0
        daily_loss_pct = abs(self.daily_pnl) / self.daily_starting_equity if self.daily_starting_equity > 0 else 0
        
        return {
            "current_equity": self.current_equity,
            "peak_equity": self.peak_equity,
            "daily_pnl": self.daily_pnl,
            "daily_loss_pct": daily_loss_pct if self.daily_pnl < 0 else 0,
            "drawdown_pct": drawdown_pct,
            "open_positions": self.open_positions,
            "consecutive_losses": self.consecutive_losses,
            "cooldown_active": self.last_loss_time is not None and 
                              datetime.utcnow() < self.last_loss_time + timedelta(minutes=self.cooldown_minutes),
        }
