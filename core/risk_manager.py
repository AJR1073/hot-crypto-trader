"""
RiskManager: Position sizing and risk limit enforcement.

Implements risk management rules including:
- Half-Kelly position sizing with rolling trade history
- Volatility targeting (annualized target)
- Correlation guard for portfolio diversification
- Position sizing based on ATR and risk percentage
- Daily loss limits
- Maximum open positions
- Total drawdown limits
- Cooldown after losses
- ATR filter for volatility

Reference: doc/Crypto Algo Trading System Research.md (Section 3)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import numpy as np

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
        # --- New: Half-Kelly & Volatility ---
        kelly_lookback: int = 50,
        kelly_fraction: float = 0.5,
        target_annual_vol: float = 0.15,
        correlation_threshold: float = 0.80,
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
            kelly_lookback: Number of recent trades for Kelly computation
            kelly_fraction: Kelly fraction (0.5 = Half-Kelly)
            target_annual_vol: Annualized volatility target (0.15 = 15%)
            correlation_threshold: Max pairwise correlation before reducing
        """
        self.initial_equity = initial_equity
        self.risk_per_trade = risk_per_trade
        self.max_open_positions = max_open_positions
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_total_drawdown_pct = max_total_drawdown_pct
        self.cooldown_minutes = cooldown_minutes_after_loss
        self.min_atr_pct_filter = min_atr_pct_filter
        self.spread_guard_bps = spread_guard_bps

        # Half-Kelly parameters
        self.kelly_lookback = kelly_lookback
        self.kelly_fraction = kelly_fraction
        self.target_annual_vol = target_annual_vol
        self.correlation_threshold = correlation_threshold

        # State tracking
        self.current_equity = initial_equity
        self.peak_equity = initial_equity
        self.daily_starting_equity = initial_equity
        self.daily_pnl = 0.0
        self.open_positions = 0
        self.last_loss_time: Optional[datetime] = None
        self.consecutive_losses = 0
        self.last_reset_date: Optional[datetime] = None

        # Trade history for rolling Kelly computation
        self.trade_history: list[dict] = []  # [{pnl, pnl_pct, symbol, ts}]
        
    def update_equity(self, equity: float) -> None:
        """Update current equity and peak."""
        self.current_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity
    
    def reset_daily(self, equity: float) -> None:
        """Reset daily tracking (call at start of each UTC day)."""
        self.daily_pnl = 0.0
        self.daily_starting_equity = equity
        self.last_reset_date = datetime.now(timezone.utc).date()
        logger.info(f"Daily reset: equity=${equity:.2f}")
    
    def check_daily_reset(self) -> None:
        """Check if we need to reset daily tracking."""
        today = datetime.now(timezone.utc).date()
        if self.last_reset_date != today:
            self.reset_daily(self.current_equity)
    
    def compute_position_size(
        self,
        price: float,
        atr_value: float,
        atr_stop_mult: float = 1.5,
        realized_vol: Optional[float] = None,
    ) -> Tuple[float, float, float]:
        """
        Compute position size using layered approach:
          1. Base: ATR risk-based sizing (existing)
          2. Half-Kelly overlay: scale by Kelly fraction if enough history
          3. Volatility targeting: scale by target_vol / realized_vol
          4. Cap at risk_per_trade ceiling

        Args:
            price: Current asset price
            atr_value: Current ATR value
            atr_stop_mult: Multiplier for ATR-based stop distance
            realized_vol: Realized annualized volatility (optional)

        Returns:
            Tuple of (position_size_units, stop_price, take_profit_price)
        """
        # --- Layer 1: ATR-based risk sizing ---
        risk_dollars = self.current_equity * self.risk_per_trade
        stop_distance = atr_value * atr_stop_mult
        stop_price = price - stop_distance

        if stop_distance > 0:
            position_units = risk_dollars / stop_distance
        else:
            position_units = 0.0

        tp_price = price + (stop_distance * 2)

        # --- Layer 2: Half-Kelly overlay ---
        kelly_f = self._compute_kelly_fraction()
        if kelly_f is not None:
            # Kelly modulates the base size
            position_units *= kelly_f / self.risk_per_trade if self.risk_per_trade > 0 else 1.0
            # But never exceed the base risk_per_trade allocation
            max_from_risk = risk_dollars / stop_distance if stop_distance > 0 else position_units
            position_units = min(position_units, max_from_risk * 2.0)  # cap at 2x base
            logger.debug("Kelly fraction: %.4f → adjusted position: %.6f", kelly_f, position_units)

        # --- Layer 3: Volatility targeting ---
        if realized_vol and realized_vol > 0 and self.target_annual_vol > 0:
            vol_scalar = self.target_annual_vol / realized_vol
            vol_scalar = np.clip(vol_scalar, 0.25, 2.0)  # clamp extremes
            position_units *= vol_scalar
            logger.debug("Vol scalar: %.2f (target=%.1f%%, realized=%.1f%%)",
                         vol_scalar, self.target_annual_vol * 100, realized_vol * 100)

        return position_units, stop_price, tp_price

    def _compute_kelly_fraction(self) -> Optional[float]:
        """
        Compute Half-Kelly fraction from rolling trade history.

        Formula: f* = kelly_fraction × (W × avg_win - (1-W) × avg_loss) / avg_win
        where W = win_rate.

        Returns:
            Kelly-adjusted fraction, or None if insufficient history.
        """
        recent = self.trade_history[-self.kelly_lookback:]
        if len(recent) < 10:  # need minimum 10 trades
            return None

        wins = [t["pnl"] for t in recent if t["pnl"] > 0]
        losses = [abs(t["pnl"]) for t in recent if t["pnl"] < 0]

        if not wins or not losses:
            return None

        win_rate = len(wins) / len(recent)
        avg_win = np.mean(wins)
        avg_loss = np.mean(losses)

        if avg_win <= 0:
            return None

        # Kelly formula
        kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        half_kelly = self.kelly_fraction * kelly

        # Clamp to [0, risk_per_trade]
        half_kelly = float(np.clip(half_kelly, 0.0, self.risk_per_trade * 2))

        logger.info(
            "Kelly: W=%.1f%% avg_win=$%.2f avg_loss=$%.2f → f*=%.4f → half_kelly=%.4f",
            win_rate * 100, avg_win, avg_loss, kelly, half_kelly,
        )
        return half_kelly

    def compute_correlation_guard(
        self, price_series: dict[str, list[float]]
    ) -> float:
        """
        Check pairwise correlation among open positions.

        If max pairwise correlation exceeds threshold, returns a
        scaling factor < 1.0 to reduce new position sizes.

        Args:
            price_series: Dict of {symbol: [recent_prices]} for open positions

        Returns:
            Scaling factor (1.0 = no reduction, 0.5 = halved due to correlation)
        """
        symbols = list(price_series.keys())
        if len(symbols) < 2:
            return 1.0

        # Compute returns
        returns = {}
        for sym, prices in price_series.items():
            arr = np.array(prices)
            if len(arr) < 10:
                continue
            rets = np.diff(np.log(arr))
            returns[sym] = rets

        if len(returns) < 2:
            return 1.0

        # Compute pairwise correlations
        syms = list(returns.keys())
        max_corr = 0.0
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                min_len = min(len(returns[syms[i]]), len(returns[syms[j]]))
                if min_len < 5:
                    continue
                corr = np.corrcoef(
                    returns[syms[i]][-min_len:],
                    returns[syms[j]][-min_len:],
                )[0, 1]
                if not np.isnan(corr):
                    max_corr = max(max_corr, abs(corr))

        if max_corr > self.correlation_threshold:
            # Linearly reduce from 1.0 at threshold to 0.5 at correlation=1.0
            scale = 1.0 - 0.5 * (max_corr - self.correlation_threshold) / (
                1.0 - self.correlation_threshold
            )
            logger.warning(
                "⚠️ Correlation guard: max=%.2f > %.2f → scale=%.2f",
                max_corr, self.correlation_threshold, scale,
            )
            return max(0.25, scale)

        return 1.0
    
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
            if datetime.now(timezone.utc) < cooldown_end:
                remaining = (cooldown_end - datetime.now(timezone.utc)).total_seconds() / 60
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

    def register_trade_close(
        self, pnl: float, symbol: str = "UNKNOWN", pnl_pct: Optional[float] = None
    ) -> None:
        """
        Register a completed trade's PnL and update trade history for Kelly.

        Args:
            pnl: Profit/loss from the trade in dollars
            symbol: Symbol that was traded
            pnl_pct: PnL as a percentage of the position (optional)
        """
        self.open_positions = max(0, self.open_positions - 1)
        self.daily_pnl += pnl
        self.current_equity += pnl

        # Record for Kelly computation
        self.trade_history.append({
            "pnl": pnl,
            "pnl_pct": pnl_pct or (pnl / self.current_equity if self.current_equity > 0 else 0),
            "symbol": symbol,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        # Keep only the rolling window
        if len(self.trade_history) > self.kelly_lookback * 2:
            self.trade_history = self.trade_history[-self.kelly_lookback:]

        if pnl >= 0:
            self.consecutive_losses = 0
            self.last_loss_time = None
        else:
            self.consecutive_losses += 1
            self.last_loss_time = datetime.now(timezone.utc)

        # Update peak
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

        logger.debug(f"Trade closed. PnL: ${pnl:.2f}, Daily PnL: ${self.daily_pnl:.2f}, "
                    f"Equity: ${self.current_equity:.2f}, "
                    f"Kelly trades: {len(self.trade_history)}")
    
    def get_status(self) -> dict:
        """Get current risk status including Kelly metrics."""
        drawdown_pct = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity > 0 else 0
        daily_loss_pct = abs(self.daily_pnl) / self.daily_starting_equity if self.daily_starting_equity > 0 else 0

        kelly_f = self._compute_kelly_fraction()

        return {
            "current_equity": self.current_equity,
            "peak_equity": self.peak_equity,
            "daily_pnl": self.daily_pnl,
            "daily_loss_pct": daily_loss_pct if self.daily_pnl < 0 else 0,
            "drawdown_pct": drawdown_pct,
            "open_positions": self.open_positions,
            "consecutive_losses": self.consecutive_losses,
            "cooldown_active": self.last_loss_time is not None and
                              datetime.now(timezone.utc) < self.last_loss_time + timedelta(minutes=self.cooldown_minutes),
            "kelly_fraction": kelly_f,
            "trade_history_count": len(self.trade_history),
        }
