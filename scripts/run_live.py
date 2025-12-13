#!/usr/bin/env python3
"""
Paper trading live loop for HOT-Crypto.

Runs enabled strategies on latest candle data, simulates trades
with risk management, and logs everything to the database.

Usage:
    # Run once (single cycle)
    python scripts/run_live.py --paper --use-sql --symbols BTC/USDT,ETH/USDT --once

    # Continuous loop
    python scripts/run_live.py --paper --use-sql --symbols BTC/USDT,ETH/USDT

    # With CCXT refresh
    python scripts/run_live.py --paper --use-sql --refresh-from-ccxt --once
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.utils import setup_logging
from core.sql_data_source import SQLDataSource
from core.exchange_client import ExchangeClient
from core.portfolio import Portfolio
from core.risk_manager import RiskManager
from core.paper_persistence import create_paper_run, update_paper_run, log_event, log_trade
from strategies.squeeze_breakout import SqueezeBreakoutLive
from strategies.indicators import SMA, STD, ATR

logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
running = True


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global running
    logger.info("Shutdown signal received...")
    running = False


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_strategies_config(strategies_path: str) -> dict:
    """Load strategies configuration."""
    with open(strategies_path, "r") as f:
        return yaml.safe_load(f)


def get_enabled_strategies(strategies_config: dict) -> list[tuple[str, dict]]:
    """Get list of enabled strategies with their configs."""
    enabled = []
    for name, config in strategies_config.items():
        if config.get("enabled", False):
            enabled.append((name, config))
    return enabled


def refresh_ohlcv_from_ccxt(
    symbol: str,
    timeframe: str,
    limit: int = 50,
    db_url: str = None,
) -> None:
    """Fetch latest candles from CCXT and upsert to database."""
    from db.models import OHLCV
    from db.init_db import get_engine
    from sqlalchemy.orm import Session
    
    logger.info(f"Refreshing {limit} candles for {symbol} from CCXT...")
    
    client = ExchangeClient()
    df = client.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    
    engine = get_engine(db_url)
    
    records = []
    for ts, row in df.iterrows():
        records.append({
            "exchange": "binanceus",
            "symbol": symbol,
            "timeframe": timeframe,
            "ts": ts.to_pydatetime(),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
        })
    
    if records:
        with Session(engine) as session:
            stmt = OHLCV.upsert_stmt(records)
            session.execute(stmt)
            session.commit()
        logger.info(f"Upserted {len(records)} candles for {symbol}")


def run_paper_trading_cycle(
    symbols: list[str],
    timeframe: str,
    portfolio: Portfolio,
    risk_manager: RiskManager,
    run_id: int,
    lookback_bars: int = 500,
    db_url: str = None,
    strategies_config: dict = None,
) -> None:
    """
    Run a single paper trading cycle.
    
    For each symbol:
    1. Load OHLCV data from SQL
    2. Get the latest closed bar
    3. Run each enabled strategy
    4. Execute signals through risk manager and portfolio
    """
    data_source = SQLDataSource(db_url=db_url)
    
    # Get enabled strategies
    enabled_strategies = get_enabled_strategies(strategies_config) if strategies_config else []
    
    if not enabled_strategies:
        logger.warning("No strategies enabled!")
        log_event(run_id, "NO_STRATEGIES", "No strategies are enabled", level="WARN")
        return
    
    # Current prices for equity calculation
    current_prices = {}
    
    for symbol in symbols:
        logger.info(f"\n{'='*40}")
        logger.info(f"Processing {symbol}")
        logger.info(f"{'='*40}")
        
        try:
            # Load OHLCV data
            df = data_source.get_ohlcv(symbol=symbol, timeframe=timeframe, limit=lookback_bars)
            
            if df.empty:
                logger.warning(f"No data for {symbol}")
                log_event(run_id, "NO_DATA", f"No OHLCV data for {symbol}", symbol=symbol, level="WARN")
                continue
            
            # Get the last fully closed bar (second to last, since last might be incomplete)
            latest_bar = df.iloc[-1]
            bar_time = df.index[-1]
            current_price = latest_bar["close"]
            current_prices[symbol] = current_price
            
            logger.info(f"Latest bar: {bar_time}, Close: ${current_price:.2f}")
            
            # Check for stop/TP hits first
            to_close = portfolio.check_stops_and_tps({symbol: current_price})
            for close_order in to_close:
                if close_order["symbol"] == symbol:
                    pos = portfolio.get_position(symbol)
                    if pos:
                        if pos.side == "LONG":
                            fill_price, pnl, fees, slippage = portfolio.close_long(symbol, close_order["price"])
                        else:
                            fill_price, pnl, fees, slippage = portfolio.close_short(symbol, close_order["price"])
                        
                        risk_manager.register_trade_close(pnl)
                        
                        log_trade(
                            run_id=run_id,
                            symbol=symbol,
                            strategy=pos.strategy or "SQZ_BO",
                            side=f"CLOSE_{pos.side}",
                            qty=pos.size,
                            price=close_order["price"],
                            fill_price=fill_price,
                            fees=fees,
                            slippage=slippage,
                            reason=close_order["reason"],
                            position_id=pos.id,
                        )
                        
                        log_event(
                            run_id=run_id,
                            event_type="CLOSE",
                            message=f"Closed {pos.side} by {close_order['reason']}: PnL ${pnl:.2f}",
                            symbol=symbol,
                            strategy=pos.strategy,
                            extra={"pnl": pnl, "reason": close_order["reason"]},
                        )
            
            # Run each enabled strategy
            for strategy_name, strategy_config in enabled_strategies:
                # Only run if symbol is in strategy's symbols list
                strategy_symbols = strategy_config.get("symbols", [])
                if symbol not in strategy_symbols:
                    continue
                
                logger.debug(f"Running {strategy_name} on {symbol}")
                
                # Initialize strategy based on name
                if strategy_name == "squeeze_breakout":
                    params = strategy_config.get("params", {})
                    strategy = SqueezeBreakoutLive(params)
                    
                    # Set up strategy state with DataFrame
                    strategy.init_symbol(symbol)
                    strategy.state[symbol]["df"] = df
                    
                    # Create candle dict for on_bar
                    candle = {
                        "open": latest_bar["open"],
                        "high": latest_bar["high"],
                        "low": latest_bar["low"],
                        "close": latest_bar["close"],
                        "volume": latest_bar["volume"],
                    }
                    
                    # Get signal
                    signal = strategy.on_bar(symbol, candle)
                    
                    logger.info(f"  {strategy_name} signal: {signal.action}")
                    
                    if signal.action == "HOLD":
                        log_event(
                            run_id=run_id,
                            event_type="HOLD",
                            message="No signal",
                            symbol=symbol,
                            strategy="SQZ_BO",
                        )
                        continue
                    
                    # Process signal
                    if signal.action == "OPEN_LONG":
                        # Check risk approval
                        atr = ATR(df["high"], df["low"], df["close"], 14).iloc[-1]
                        
                        decision = risk_manager.evaluate_trade(
                            symbol=symbol,
                            price=current_price,
                            atr_value=atr,
                            atr_stop_mult=params.get("atr_stop_mult", 1.5),
                        )
                        
                        if not decision.approved:
                            logger.warning(f"  Trade REJECTED: {decision.reason}")
                            log_event(
                                run_id=run_id,
                                event_type="REJECT",
                                message=decision.reason,
                                level="WARN",
                                symbol=symbol,
                                strategy="SQZ_BO",
                            )
                            continue
                        
                        # Execute trade
                        stop = signal.extra.get("stop") if signal.extra else None
                        tp = signal.extra.get("tp") if signal.extra else None
                        
                        try:
                            fill_price, fees, slippage = portfolio.open_long(
                                symbol=symbol,
                                size=decision.position_size,
                                price=current_price,
                                stop=stop,
                                tp=tp,
                                strategy="SQZ_BO",
                            )
                            
                            risk_manager.register_trade_open()
                            
                            log_trade(
                                run_id=run_id,
                                symbol=symbol,
                                strategy="SQZ_BO",
                                side="LONG",
                                qty=decision.position_size,
                                price=current_price,
                                fill_price=fill_price,
                                fees=fees,
                                slippage=slippage,
                                reason="Squeeze breakout LONG signal",
                            )
                            
                            log_event(
                                run_id=run_id,
                                event_type="FILL",
                                message=f"Opened LONG {decision.position_size:.6f} @ ${fill_price:.2f}",
                                symbol=symbol,
                                strategy="SQZ_BO",
                                extra={"size": decision.position_size, "stop": stop, "tp": tp},
                            )
                            
                        except ValueError as e:
                            logger.error(f"  Trade execution failed: {e}")
                            log_event(
                                run_id=run_id,
                                event_type="ERROR",
                                message=str(e),
                                level="ERROR",
                                symbol=symbol,
                                strategy="SQZ_BO",
                            )
                    
                    elif signal.action == "OPEN_SHORT":
                        # Similar to OPEN_LONG but for shorts
                        atr = ATR(df["high"], df["low"], df["close"], 14).iloc[-1]
                        
                        decision = risk_manager.evaluate_trade(
                            symbol=symbol,
                            price=current_price,
                            atr_value=atr,
                        )
                        
                        if not decision.approved:
                            logger.warning(f"  Trade REJECTED: {decision.reason}")
                            log_event(run_id, "REJECT", decision.reason, level="WARN", symbol=symbol, strategy="SQZ_BO")
                            continue
                        
                        stop = signal.extra.get("stop") if signal.extra else None
                        tp = signal.extra.get("tp") if signal.extra else None
                        
                        try:
                            fill_price, fees, slippage = portfolio.open_short(
                                symbol=symbol,
                                size=decision.position_size,
                                price=current_price,
                                stop=stop,
                                tp=tp,
                                strategy="SQZ_BO",
                            )
                            
                            risk_manager.register_trade_open()
                            
                            log_trade(run_id, symbol, "SQZ_BO", "SHORT", decision.position_size,
                                     current_price, fill_price, fees, slippage, "Squeeze breakout SHORT signal")
                            
                            log_event(run_id, "FILL", f"Opened SHORT {decision.position_size:.6f} @ ${fill_price:.2f}",
                                     symbol=symbol, strategy="SQZ_BO")
                            
                        except ValueError as e:
                            log_event(run_id, "ERROR", str(e), level="ERROR", symbol=symbol, strategy="SQZ_BO")
                    
                    elif signal.action in ("CLOSE_LONG", "CLOSE_SHORT"):
                        pos = portfolio.get_position(symbol)
                        if pos:
                            if pos.side == "LONG":
                                fill_price, pnl, fees, slippage = portfolio.close_long(symbol, current_price)
                            else:
                                fill_price, pnl, fees, slippage = portfolio.close_short(symbol, current_price)
                            
                            risk_manager.register_trade_close(pnl)
                            
                            reason = signal.extra.get("reason", "Strategy exit") if signal.extra else "Strategy exit"
                            log_trade(run_id, symbol, "SQZ_BO", signal.action, pos.size,
                                     current_price, fill_price, fees, slippage, reason, pos.id)
                            
                            log_event(run_id, "CLOSE", f"Closed position: PnL ${pnl:.2f}",
                                     symbol=symbol, strategy="SQZ_BO", extra={"pnl": pnl})
                
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}", exc_info=True)
            log_event(run_id, "ERROR", str(e), level="ERROR", symbol=symbol)
    
    # Log portfolio status
    equity = portfolio.get_equity(current_prices)
    risk_manager.update_equity(equity)
    
    status = portfolio.get_status(current_prices)
    risk_status = risk_manager.get_status()
    
    logger.info(f"\n{'='*40}")
    logger.info("PORTFOLIO STATUS")
    logger.info(f"  Equity: ${equity:,.2f}")
    logger.info(f"  Cash: ${status['cash']:,.2f}")
    logger.info(f"  Return: {status['return_pct']:.2f}%")
    logger.info(f"  Open Positions: {status['open_positions']}")
    logger.info(f"  Daily PnL: ${risk_status['daily_pnl']:.2f}")
    logger.info(f"  Drawdown: {risk_status['drawdown_pct']*100:.2f}%")
    logger.info(f"{'='*40}")


def main():
    global running
    
    parser = argparse.ArgumentParser(
        description="Run paper trading simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument("--config", default="config/live.yaml", help="Live config file")
    parser.add_argument("--strategies", default="config/strategies.yaml", help="Strategies config file")
    parser.add_argument("--timeframe", default=None, help="Timeframe override")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbols override")
    parser.add_argument("--use-sql", action="store_true", default=True, help="Use SQL data source")
    parser.add_argument("--refresh-from-ccxt", action="store_true", help="Refresh data from CCXT before each cycle")
    parser.add_argument("--paper", action="store_true", default=True, help="Paper trading mode (no real orders)")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--sleep-seconds", type=int, default=None, help="Sleep between cycles")
    parser.add_argument("--dry-run", action="store_true", help="Print config and exit")
    
    args = parser.parse_args()
    logger = setup_logging()
    
    # Set up graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Load configs
    try:
        config = load_config(args.config)
        strategies_config = load_strategies_config(args.strategies)
    except FileNotFoundError as e:
        logger.error(f"Config file not found: {e}")
        sys.exit(1)
    
    # Override from args
    symbols = args.symbols.split(",") if args.symbols else config.get("symbols", ["BTC/USDT", "ETH/USDT"])
    timeframe = args.timeframe or config.get("timeframe", "4h")
    sleep_seconds = args.sleep_seconds or config.get("loop", {}).get("sleep_seconds", 60)
    initial_cash = config.get("initial_cash", 10000)
    commission = config.get("commission", 0.0005)
    slippage_bps = config.get("slippage_bps", 2)
    db_url = config.get("db_url")
    lookback_bars = config.get("loop", {}).get("lookback_bars", 500)
    refresh_bars = config.get("loop", {}).get("refresh_bars_from_ccxt", 50)
    
    risk_config = config.get("risk", {})
    
    if args.dry_run:
        logger.info("DRY RUN - Configuration:")
        logger.info(f"  Symbols: {symbols}")
        logger.info(f"  Timeframe: {timeframe}")
        logger.info(f"  Initial Cash: ${initial_cash}")
        logger.info(f"  Paper Mode: {args.paper}")
        logger.info(f"  Enabled Strategies: {[name for name, cfg in strategies_config.items() if cfg.get('enabled')]}")
        return
    
    logger.info("=" * 60)
    logger.info("HOT-Crypto Paper Trading")
    logger.info("=" * 60)
    logger.info(f"Symbols: {symbols}")
    logger.info(f"Timeframe: {timeframe}")
    logger.info(f"Initial Cash: ${initial_cash:,.2f}")
    logger.info(f"Paper Mode: {args.paper}")
    logger.info(f"Single Cycle: {args.once}")
    logger.info("=" * 60)
    
    # Initialize components
    portfolio = Portfolio(
        initial_cash=initial_cash,
        commission=commission,
        slippage_bps=slippage_bps,
    )
    
    risk_manager = RiskManager(
        initial_equity=initial_cash,
        risk_per_trade=risk_config.get("risk_per_trade", 0.005),
        max_open_positions=risk_config.get("max_open_positions", 2),
        max_daily_loss_pct=risk_config.get("max_daily_loss_pct", 0.02),
        max_total_drawdown_pct=risk_config.get("max_total_drawdown_pct", 0.10),
        cooldown_minutes_after_loss=risk_config.get("cooldown_minutes_after_loss", 240),
        min_atr_pct_filter=risk_config.get("min_atr_pct_filter", 0.003),
        spread_guard_bps=risk_config.get("spread_guard_bps", 10),
    )
    
    # Create paper run record
    run_id = create_paper_run(
        symbols=symbols,
        timeframe=timeframe,
        initial_cash=initial_cash,
    )
    
    logger.info(f"Created paper run #{run_id}")
    log_event(run_id, "START", f"Paper trading started with {symbols}")
    
    try:
        cycle = 0
        while running:
            cycle += 1
            logger.info(f"\n{'#'*60}")
            logger.info(f"CYCLE {cycle} - {datetime.utcnow().isoformat()}")
            logger.info(f"{'#'*60}")
            
            # Refresh from CCXT if requested
            if args.refresh_from_ccxt:
                for symbol in symbols:
                    try:
                        refresh_ohlcv_from_ccxt(symbol, timeframe, refresh_bars, db_url)
                    except Exception as e:
                        logger.error(f"Failed to refresh {symbol}: {e}")
            
            # Run trading cycle
            run_paper_trading_cycle(
                symbols=symbols,
                timeframe=timeframe,
                portfolio=portfolio,
                risk_manager=risk_manager,
                run_id=run_id,
                lookback_bars=lookback_bars,
                db_url=db_url,
                strategies_config=strategies_config,
            )
            
            if args.once:
                logger.info("Single cycle complete. Exiting.")
                break
            
            logger.info(f"Sleeping {sleep_seconds} seconds...")
            for _ in range(sleep_seconds):
                if not running:
                    break
                time.sleep(1)
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        update_paper_run(run_id, status="error")
        log_event(run_id, "ERROR", str(e), level="ERROR")
        raise
    
    finally:
        # Finalize run
        final_equity = portfolio.get_equity({})  # Approximate with no prices
        update_paper_run(run_id, status="stopped", final_equity=final_equity)
        log_event(run_id, "STOP", f"Paper trading stopped. Final equity: ${final_equity:,.2f}")
        
        logger.info(f"\nPaper run #{run_id} completed.")
        logger.info(f"Final equity: ${final_equity:,.2f}")


if __name__ == "__main__":
    main()
