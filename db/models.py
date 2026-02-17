"""
SQLAlchemy models for HOT-Crypto database.

Tables:
- OHLCV: Candle data storage with upsert support
- BacktestRun: Backtest metadata and summary stats
- BacktestTrade: Individual trades from backtests
- PaperRun/Event/Trade: Paper trading records
- LiveOrder: Live order state tracking with idempotency
- CircuitBreakerState: Persistent circuit breaker trips
- TaxLedger: IRS-ready trade records
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base


class OHLCV(Base):
    """
    OHLCV candle data model.
    
    Stores historical price data with unique constraint on
    (exchange, symbol, timeframe, ts) to prevent duplicates.
    Uses SQLite ON CONFLICT for upsert semantics.
    """
    __tablename__ = "ohlcv"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exchange = Column(String(50), nullable=False)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    ts = Column(DateTime, nullable=False)  # Candle timestamp (UTC)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("exchange", "symbol", "timeframe", "ts", name="uq_ohlcv"),
        Index("ix_ohlcv_lookup", "exchange", "symbol", "timeframe", "ts"),
    )

    def __repr__(self) -> str:
        return f"<OHLCV {self.symbol} {self.timeframe} {self.ts}>"

    @classmethod
    def upsert_stmt(cls, values: list[dict]):
        """
        Create SQLite INSERT ... ON CONFLICT DO UPDATE statement.
        
        Args:
            values: List of dicts with ohlcv data
            
        Returns:
            SQLAlchemy insert statement with on_conflict_do_update
        """
        from sqlalchemy.dialects.sqlite import insert
        
        stmt = insert(cls).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["exchange", "symbol", "timeframe", "ts"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            }
        )
        return stmt


class BacktestRun(Base):
    """
    Backtest run metadata and summary statistics.
    """
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    exchange = Column(String(50), nullable=False)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    strategy_name = Column(String(50), nullable=False)
    initial_cash = Column(Float, nullable=False)
    final_equity = Column(Float)
    max_drawdown_pct = Column(Float)
    sharpe_ratio = Column(Float)
    trades_count = Column(Integer)
    stats_json = Column(Text)  # Raw stats JSON from Backtesting.py

    # Relationship to trades
    trades = relationship("BacktestTrade", back_populates="backtest_run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<BacktestRun {self.id} {self.strategy_name} {self.symbol}>"


class BacktestTrade(Base):
    """
    Individual trade record from a backtest.
    """
    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id = Column(Integer, ForeignKey("backtest_runs.id"), nullable=False)
    symbol = Column(String(20), nullable=False)
    strategy_name = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)  # LONG or SHORT
    size = Column(Float, nullable=False)
    entry_ts = Column(DateTime, nullable=False)
    exit_ts = Column(DateTime)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    pnl = Column(Float)
    pnl_pct = Column(Float)
    max_dd_pct = Column(Float)

    # Relationship to run
    backtest_run = relationship("BacktestRun", back_populates="trades")

    def __repr__(self) -> str:
        return f"<BacktestTrade {self.id} {self.side} {self.symbol}>"


# =============================================================================
# Paper Trading Models
# =============================================================================


class PaperRun(Base):
    """
    Paper trading run session.
    
    Tracks a paper trading session with its configuration and status.
    """
    __tablename__ = "paper_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at = Column(DateTime)
    symbols = Column(Text, nullable=False)  # JSON list of symbols
    timeframe = Column(String(10), nullable=False)
    initial_cash = Column(Float, nullable=False)
    final_equity = Column(Float)
    status = Column(String(20), default="running")  # running, stopped, error

    # Relationships
    events = relationship("PaperEvent", back_populates="run", cascade="all, delete-orphan")
    trades = relationship("PaperTrade", back_populates="run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<PaperRun {self.id} {self.status} {self.symbols}>"


class PaperEvent(Base):
    """
    Paper trading event log.
    
    Records all events during paper trading: signals, rejections, fills, etc.
    """
    __tablename__ = "paper_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("paper_runs.id"), nullable=False)
    ts = Column(DateTime, default=datetime.utcnow, nullable=False)
    level = Column(String(10), nullable=False)  # INFO, WARN, ERROR
    symbol = Column(String(20))
    strategy = Column(String(50))
    event_type = Column(String(50), nullable=False)  # SIGNAL, REJECT, FILL, etc.
    message = Column(Text)
    json_blob = Column(Text)  # JSON for extra data

    # Relationship
    run = relationship("PaperRun", back_populates="events")

    def __repr__(self) -> str:
        return f"<PaperEvent {self.id} {self.event_type} {self.symbol}>"


class PaperTrade(Base):
    """
    Paper trading simulated trade.
    
    Records simulated fills with slippage and commission.
    """
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("paper_runs.id"), nullable=False)
    ts = Column(DateTime, default=datetime.utcnow, nullable=False)
    symbol = Column(String(20), nullable=False)
    strategy = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)  # LONG, SHORT, CLOSE_LONG, CLOSE_SHORT
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fill_price = Column(Float, nullable=False)  # Price after slippage
    fees = Column(Float, default=0.0)
    slippage = Column(Float, default=0.0)
    reason = Column(Text)  # Why this trade was taken
    position_id = Column(Integer)  # Links related trades

    # Relationship
    run = relationship("PaperRun", back_populates="trades")

    def __repr__(self) -> str:
        return f"<PaperTrade {self.id} {self.side} {self.symbol} @ {self.fill_price}>"


# =============================================================================
# Live Trading Models
# =============================================================================


class LiveOrder(Base):
    """
    Tracks all live orders through the state machine.

    States: pending → submitted → filled | partial | cancelled | orphaned | error
    Uses client_order_id for idempotent reconciliation.
    """
    __tablename__ = "live_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_order_id = Column(String(100), unique=True, nullable=False)
    exchange_order_id = Column(String(100))
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # buy, sell
    order_type = Column(String(10), nullable=False)  # limit, market
    qty = Column(Float, nullable=False)
    filled_qty = Column(Float, default=0.0)
    price = Column(Float)  # Requested price (None for market)
    avg_fill_price = Column(Float)
    status = Column(String(20), nullable=False, default="pending")
    strategy = Column(String(50), nullable=False)
    fees = Column(Float, default=0.0)
    error_message = Column(Text)
    chase_attempts = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    submitted_at = Column(DateTime)
    filled_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_live_orders_status", "status"),
        Index("ix_live_orders_symbol", "symbol", "status"),
    )

    def __repr__(self) -> str:
        return f"<LiveOrder {self.client_order_id} {self.side} {self.symbol} [{self.status}]>"


class CircuitBreakerState(Base):
    """
    Persists circuit breaker trips across restarts.

    Active trips are loaded on startup to restore safety state.
    """
    __tablename__ = "circuit_breaker_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    breaker_type = Column(String(20), nullable=False)  # asset, portfolio, consecutive, flash
    symbol = Column(String(20))  # NULL for portfolio-level breakers
    triggered_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    reason = Column(Text, nullable=False)

    __table_args__ = (
        Index("ix_cb_state_expires", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<CircuitBreakerState {self.breaker_type} {self.symbol} expires={self.expires_at}>"


class TaxLedger(Base):
    """
    IRS-ready trade records for Form 8949 / Schedule D.

    Every closed trade creates one ledger entry with cost basis,
    proceeds, gain/loss, and wash-sale flags.
    """
    __tablename__ = "tax_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    acquired_date = Column(DateTime, nullable=False)
    disposed_date = Column(DateTime, nullable=False)
    qty = Column(Float, nullable=False)
    cost_basis = Column(Float, nullable=False)  # Total cost including fees
    proceeds = Column(Float, nullable=False)  # Total proceeds after fees
    gain_loss = Column(Float, nullable=False)
    fees_total = Column(Float, default=0.0)
    holding_period = Column(String(10))  # "short" or "long"
    wash_sale_flag = Column(String(5), default="N")  # "Y" or "N"
    wash_sale_adjustment = Column(Float, default=0.0)
    strategy = Column(String(50))
    notes = Column(Text)

    __table_args__ = (
        Index("ix_tax_ledger_symbol", "symbol", "disposed_date"),
    )

    def __repr__(self) -> str:
        return f"<TaxLedger {self.symbol} {self.disposed_date} PnL=${self.gain_loss:.2f}>"

