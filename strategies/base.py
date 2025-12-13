"""
Base strategy components: StrategySignal and BaseStrategy.

Provides the common interface and data structures used by all
trading strategies in the system.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StrategySignal:
    """
    Signal emitted by a strategy on each bar.
    
    Attributes:
        symbol: Trading pair the signal is for
        action: One of OPEN_LONG, CLOSE_LONG, OPEN_SHORT, CLOSE_SHORT, HOLD
        risk_r: Risk multiplier (1.0 = default risk per trade)
        extra: Additional data like stop, tp, atr values
    """
    symbol: str
    action: str  # OPEN_LONG, CLOSE_LONG, OPEN_SHORT, CLOSE_SHORT, HOLD
    risk_r: float = 1.0
    extra: Optional[dict] = field(default_factory=dict)


class BaseStrategy:
    """
    Base class for live trading strategies.
    
    Strategies maintain state and emit signals on each bar.
    Each strategy should implement on_bar() to process new candles.
    """

    def __init__(self, config: dict):
        """
        Initialize strategy with configuration.

        Args:
            config: Strategy-specific parameters
        """
        self.config = config
        self.state: dict = {}  # Per-symbol state, e.g., {"BTC/USDT": {"df": ...}}

    def on_bar(self, symbol: str, candle: dict) -> StrategySignal:
        """
        Process a new candle and return a signal.

        Args:
            symbol: Trading pair
            candle: Dict with keys: time, open, high, low, close, volume

        Returns:
            StrategySignal indicating the recommended action
        """
        raise NotImplementedError("Subclasses must implement on_bar()")

    def init_symbol(self, symbol: str) -> None:
        """
        Initialize state for a new symbol.

        Args:
            symbol: Trading pair to initialize
        """
        if symbol not in self.state:
            self.state[symbol] = {"df": None, "position": None}
