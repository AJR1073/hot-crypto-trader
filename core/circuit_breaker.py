"""
Production-Grade Circuit Breakers for live trading.

Implements four independent safety mechanisms:
  1. Asset-level breaker   — halts trading on a symbol that drops >15% in 1h
  2. Portfolio-level kill   — freezes ALL trading if portfolio down >10% intraday
  3. Consecutive loss       — pauses after N consecutive losing trades
  4. Flash crash detector   — halts if price moves >5% in <60 seconds

All breaker states can be persisted to DB for restart recovery.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BreakerTrip:
    """Record of a triggered circuit breaker."""

    breaker_type: str  # "asset", "portfolio", "consecutive", "flash"
    symbol: Optional[str]
    triggered_at: datetime
    expires_at: datetime
    reason: str

    @property
    def is_active(self) -> bool:
        return datetime.now(timezone.utc) < self.expires_at


class CircuitBreaker:
    """
    Composite circuit breaker that evaluates all safety checks.

    Usage::

        cb = CircuitBreaker()
        allowed, reason = cb.check("BTC/USDT", 42000.0, portfolio_value=9500, initial_value=10000)
        if not allowed:
            logger.warning("Trade blocked: %s", reason)
    """

    def __init__(
        self,
        asset_drop_pct: float = 0.15,
        asset_window_seconds: int = 3600,
        portfolio_kill_pct: float = 0.10,
        consecutive_loss_limit: int = 3,
        consecutive_cooldown_minutes: int = 30,
        flash_crash_pct: float = 0.05,
        flash_crash_window_seconds: int = 60,
    ):
        """
        Args:
            asset_drop_pct: Max drop allowed for a single asset in the window.
            asset_window_seconds: Window for asset-level checks (default 1h).
            portfolio_kill_pct: Max intraday drawdown before kill switch.
            consecutive_loss_limit: How many consecutive losses trigger pause.
            consecutive_cooldown_minutes: Cooldown after consecutive losses.
            flash_crash_pct: Max price move in flash window.
            flash_crash_window_seconds: Flash crash time window.
        """
        self.asset_drop_pct = asset_drop_pct
        self.asset_window_seconds = asset_window_seconds
        self.portfolio_kill_pct = portfolio_kill_pct
        self.consecutive_loss_limit = consecutive_loss_limit
        self.consecutive_cooldown_minutes = consecutive_cooldown_minutes
        self.flash_crash_pct = flash_crash_pct
        self.flash_crash_window_seconds = flash_crash_window_seconds

        # Price history per symbol: list of (timestamp, price)
        self._price_history: dict[str, list[tuple[float, float]]] = defaultdict(list)

        # Consecutive loss tracking per symbol (None = per-portfolio)
        self._consecutive_losses: int = 0

        # Active trips
        self._trips: list[BreakerTrip] = []

        # Start-of-day portfolio value (set via reset_daily)
        self._sod_portfolio_value: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset_daily(self, portfolio_value: float) -> None:
        """Reset daily tracking. Call at start of each trading day."""
        self._sod_portfolio_value = portfolio_value
        # Purge expired trips
        self._trips = [t for t in self._trips if t.is_active]
        logger.info("Circuit breakers reset. SOD portfolio: $%.2f", portfolio_value)

    def record_price(self, symbol: str, price: float) -> None:
        """Record a price tick for a symbol (for asset/flash checks)."""
        now = time.time()
        self._price_history[symbol].append((now, price))
        # Prune old entries (keep last 2 hours)
        cutoff = now - 7200
        self._price_history[symbol] = [
            (t, p) for t, p in self._price_history[symbol] if t > cutoff
        ]

    def register_trade_result(self, pnl: float) -> None:
        """Register a trade result for consecutive-loss tracking."""
        if pnl < 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.consecutive_loss_limit:
                self._trip_consecutive()
        else:
            self._consecutive_losses = 0

    def check(
        self,
        symbol: str,
        current_price: float,
        portfolio_value: Optional[float] = None,
        initial_value: Optional[float] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Run all circuit breaker checks.

        Args:
            symbol: Trading pair to check.
            current_price: Current price of the symbol.
            portfolio_value: Current total portfolio value.
            initial_value: Start-of-day portfolio value (overrides stored).

        Returns:
            (allowed, reason) — allowed=True if trading is OK.
        """
        # Record price tick
        self.record_price(symbol, current_price)

        # Check active trips first
        for trip in self._trips:
            if trip.is_active:
                if trip.symbol is None or trip.symbol == symbol:
                    return False, f"Circuit breaker active: {trip.reason} (expires {trip.expires_at.isoformat()})"

        # 1. Asset-level drop check
        ok, reason = self._check_asset_drop(symbol, current_price)
        if not ok:
            return False, reason

        # 2. Flash crash check
        ok, reason = self._check_flash_crash(symbol, current_price)
        if not ok:
            return False, reason

        # 3. Portfolio-level kill switch
        sod = initial_value or self._sod_portfolio_value
        if sod and portfolio_value is not None:
            ok, reason = self._check_portfolio_kill(portfolio_value, sod)
            if not ok:
                return False, reason

        return True, None

    def get_active_trips(self) -> list[BreakerTrip]:
        """Return all currently active breaker trips."""
        return [t for t in self._trips if t.is_active]

    def get_status(self) -> dict:
        """Get a summary of circuit breaker state."""
        active = self.get_active_trips()
        return {
            "active_trips": len(active),
            "consecutive_losses": self._consecutive_losses,
            "trips": [
                {
                    "type": t.breaker_type,
                    "symbol": t.symbol,
                    "reason": t.reason,
                    "expires": t.expires_at.isoformat(),
                }
                for t in active
            ],
        }

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _check_asset_drop(
        self, symbol: str, current_price: float
    ) -> tuple[bool, Optional[str]]:
        """Check if a single asset has dropped too far in the window."""
        history = self._price_history.get(symbol, [])
        if not history:
            return True, None

        cutoff = time.time() - self.asset_window_seconds
        window_prices = [p for t, p in history if t > cutoff]
        if not window_prices:
            return True, None

        window_high = max(window_prices)
        if window_high <= 0:
            return True, None

        drop = (window_high - current_price) / window_high
        if drop >= self.asset_drop_pct:
            reason = (
                f"Asset {symbol} dropped {drop:.1%} in "
                f"{self.asset_window_seconds}s (limit {self.asset_drop_pct:.0%})"
            )
            self._trip_asset(symbol, reason)
            return False, reason

        return True, None

    def _check_flash_crash(
        self, symbol: str, current_price: float
    ) -> tuple[bool, Optional[str]]:
        """Check for abnormally fast price movement."""
        history = self._price_history.get(symbol, [])
        if len(history) < 2:
            return True, None

        cutoff = time.time() - self.flash_crash_window_seconds
        recent = [p for t, p in history if t > cutoff]
        if len(recent) < 2:
            return True, None

        # Check max absolute move within the flash window
        earliest_in_window = recent[0]
        if earliest_in_window <= 0:
            return True, None

        move = abs(current_price - earliest_in_window) / earliest_in_window
        if move >= self.flash_crash_pct:
            reason = (
                f"Flash crash detected on {symbol}: {move:.1%} move in "
                f"{self.flash_crash_window_seconds}s (limit {self.flash_crash_pct:.0%})"
            )
            self._trip_flash(symbol, reason)
            return False, reason

        return True, None

    def _check_portfolio_kill(
        self, current_value: float, sod_value: float
    ) -> tuple[bool, Optional[str]]:
        """Check if the portfolio has breached intraday drawdown."""
        if sod_value <= 0:
            return True, None

        drawdown = (sod_value - current_value) / sod_value
        if drawdown >= self.portfolio_kill_pct:
            reason = (
                f"Portfolio kill switch: down {drawdown:.1%} intraday "
                f"(limit {self.portfolio_kill_pct:.0%})"
            )
            self._trip_portfolio(reason)
            return False, reason

        return True, None

    # ------------------------------------------------------------------
    # Trip handlers
    # ------------------------------------------------------------------

    def _trip_asset(self, symbol: str, reason: str) -> None:
        now = datetime.now(timezone.utc)
        trip = BreakerTrip(
            breaker_type="asset",
            symbol=symbol,
            triggered_at=now,
            expires_at=now + timedelta(hours=1),
            reason=reason,
        )
        self._trips.append(trip)
        logger.critical("🚨 CIRCUIT BREAKER [asset]: %s", reason)

    def _trip_portfolio(self, reason: str) -> None:
        now = datetime.now(timezone.utc)
        trip = BreakerTrip(
            breaker_type="portfolio",
            symbol=None,  # affects all symbols
            triggered_at=now,
            expires_at=now + timedelta(hours=24),  # rest of day
            reason=reason,
        )
        self._trips.append(trip)
        logger.critical("🚨 CIRCUIT BREAKER [portfolio]: %s", reason)

    def _trip_consecutive(self) -> None:
        now = datetime.now(timezone.utc)
        reason = f"{self._consecutive_losses} consecutive losing trades"
        trip = BreakerTrip(
            breaker_type="consecutive",
            symbol=None,
            triggered_at=now,
            expires_at=now + timedelta(minutes=self.consecutive_cooldown_minutes),
            reason=reason,
        )
        self._trips.append(trip)
        logger.critical("🚨 CIRCUIT BREAKER [consecutive]: %s", reason)

    def _trip_flash(self, symbol: str, reason: str) -> None:
        now = datetime.now(timezone.utc)
        trip = BreakerTrip(
            breaker_type="flash",
            symbol=symbol,
            triggered_at=now,
            expires_at=now + timedelta(minutes=15),
            reason=reason,
        )
        self._trips.append(trip)
        logger.critical("🚨 CIRCUIT BREAKER [flash]: %s", reason)
