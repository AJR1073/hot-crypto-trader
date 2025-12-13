"""
Paper trading persistence: Save paper runs, events, and trades to database.

Provides functions to:
- Create and manage paper trading sessions
- Log events during paper trading
- Record simulated trades
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from db.init_db import get_engine
from db.models import PaperRun, PaperEvent, PaperTrade

logger = logging.getLogger(__name__)


def create_paper_run(
    symbols: list[str],
    timeframe: str,
    initial_cash: float,
    db_url: Optional[str] = None,
) -> int:
    """
    Create a new paper trading run.

    Args:
        symbols: List of trading pairs
        timeframe: Candle timeframe
        initial_cash: Starting capital
        db_url: Database URL override

    Returns:
        The ID of the created PaperRun
    """
    engine = get_engine(db_url)
    
    with Session(engine) as session:
        run = PaperRun(
            symbols=json.dumps(symbols),
            timeframe=timeframe,
            initial_cash=initial_cash,
            status="running",
        )
        session.add(run)
        session.commit()
        run_id = run.id
        logger.info(f"Created paper run #{run_id}")
    
    return run_id


def update_paper_run(
    run_id: int,
    status: Optional[str] = None,
    final_equity: Optional[float] = None,
    db_url: Optional[str] = None,
) -> None:
    """Update a paper run's status or final equity."""
    engine = get_engine(db_url)
    
    with Session(engine) as session:
        run = session.get(PaperRun, run_id)
        if run:
            if status:
                run.status = status
            if final_equity is not None:
                run.final_equity = final_equity
            if status in ("stopped", "error"):
                run.ended_at = datetime.utcnow()
            session.commit()


def log_event(
    run_id: int,
    event_type: str,
    message: str,
    level: str = "INFO",
    symbol: Optional[str] = None,
    strategy: Optional[str] = None,
    extra: Optional[dict] = None,
    db_url: Optional[str] = None,
) -> int:
    """
    Log an event during paper trading.

    Args:
        run_id: Paper run ID
        event_type: Type of event (SIGNAL, REJECT, FILL, etc.)
        message: Human-readable message
        level: Log level (INFO, WARN, ERROR)
        symbol: Trading pair
        strategy: Strategy name
        extra: Additional data as dict
        db_url: Database URL override

    Returns:
        The event ID
    """
    engine = get_engine(db_url)
    
    with Session(engine) as session:
        event = PaperEvent(
            run_id=run_id,
            level=level,
            symbol=symbol,
            strategy=strategy,
            event_type=event_type,
            message=message,
            json_blob=json.dumps(extra) if extra else None,
        )
        session.add(event)
        session.commit()
        event_id = event.id
    
    # Also log to console
    log_msg = f"[{event_type}] {symbol or ''} {strategy or ''}: {message}"
    if level == "ERROR":
        logger.error(log_msg)
    elif level == "WARN":
        logger.warning(log_msg)
    else:
        logger.info(log_msg)
    
    return event_id


def log_trade(
    run_id: int,
    symbol: str,
    strategy: str,
    side: str,
    qty: float,
    price: float,
    fill_price: float,
    fees: float = 0.0,
    slippage: float = 0.0,
    reason: Optional[str] = None,
    position_id: Optional[int] = None,
    db_url: Optional[str] = None,
) -> int:
    """
    Log a simulated trade.

    Args:
        run_id: Paper run ID
        symbol: Trading pair
        strategy: Strategy name
        side: Trade side (LONG, SHORT, CLOSE_LONG, CLOSE_SHORT)
        qty: Quantity
        price: Intended price
        fill_price: Actual fill price after slippage
        fees: Commission fees
        slippage: Slippage amount
        reason: Why this trade was taken
        position_id: Links related entry/exit trades
        db_url: Database URL override

    Returns:
        The trade ID
    """
    engine = get_engine(db_url)
    
    with Session(engine) as session:
        trade = PaperTrade(
            run_id=run_id,
            symbol=symbol,
            strategy=strategy,
            side=side,
            qty=qty,
            price=price,
            fill_price=fill_price,
            fees=fees,
            slippage=slippage,
            reason=reason,
            position_id=position_id,
        )
        session.add(trade)
        session.commit()
        trade_id = trade.id
    
    logger.info(f"Paper trade #{trade_id}: {side} {qty:.6f} {symbol} @ {fill_price:.2f} (fees: ${fees:.4f})")
    
    return trade_id


def get_run_trades(run_id: int, db_url: Optional[str] = None) -> list[dict]:
    """Get all trades for a paper run."""
    engine = get_engine(db_url)
    
    with Session(engine) as session:
        trades = session.query(PaperTrade).filter(PaperTrade.run_id == run_id).all()
        return [
            {
                "id": t.id,
                "ts": t.ts,
                "symbol": t.symbol,
                "strategy": t.strategy,
                "side": t.side,
                "qty": t.qty,
                "price": t.price,
                "fill_price": t.fill_price,
                "fees": t.fees,
            }
            for t in trades
        ]
