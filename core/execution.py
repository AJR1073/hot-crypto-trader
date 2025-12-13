"""
Execution: Signal to trade execution engine.

Converts strategy signals into portfolio/order operations,
supporting both paper trading and live execution modes.
"""

from typing import Optional

from .portfolio import Portfolio
from .risk_manager import RiskManager


class Executor:
    """
    Signal executor that converts strategy signals into trades.
    
    In paper mode, updates Portfolio directly.
    In live mode, would place orders via ExchangeClient.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        risk_manager: RiskManager,
        live: bool = False,
        exchange_client: Optional[object] = None,
    ):
        """
        Initialize the executor.

        Args:
            portfolio: Portfolio instance for tracking positions
            risk_manager: RiskManager for position sizing
            live: If True, place real orders (future feature)
            exchange_client: ExchangeClient for live trading
        """
        self.portfolio = portfolio
        self.risk_manager = risk_manager
        self.live = live
        self.exchange_client = exchange_client

    def execute_signal(
        self,
        symbol: str,
        signal: object,
        latest_candle: dict,
        strategy_name: str,
    ) -> Optional[dict]:
        """
        Execute a strategy signal.

        Args:
            symbol: Trading pair
            signal: StrategySignal from a strategy
            latest_candle: Most recent candle data
            strategy_name: Name of the strategy for logging

        Returns:
            Dict with execution details, or None if no action taken
        """
        # TODO: Implement in Phase 6
        raise NotImplementedError("Will be implemented in Phase 6")
