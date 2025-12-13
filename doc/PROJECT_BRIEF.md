You are an expert quantitative developer and trading systems architect.

Goal
Build a modular crypto trading engine called **HOT-Crypto**. It must:
- Use Python 3.11+.
- Use **ccxt** for exchange access (starting with Binance.US).
- Use **Backtesting.py** for historical backtests of multiple strategies.
- Store historical OHLCV data and backtest results in a local SQL database (SQLite by default).
- Support multiple strategies via a clean interface, with:
  - A **Backtesting** version for offline tests.
  - A **Live** version for a paper-trading engine.
- Provide a simple **paper live trading loop** (no real money initially) with risk management and a portfolio simulator.
- Be designed so that a future LLM meta-controller can change strategy weights and risk params but NOT directly place trades.
L
High-level architecture
Create a repo structure like:

  hot-crypto/
    README.md
    requirements.txt
    .env.example
    config/
      settings.yaml            # exchange, risk, db config
      strategies.yaml          # which strategies are enabled + params
      markets.yaml             # which symbols/timeframes
    core/
      __init__.py
      exchange_client.py       # ccxt wrapper for Binance.US
      data_source.py           # abstract DataSource
      ccxt_data_source.py      # DataSource using ccxt
      sql_data_source.py       # DataSource using DB
      backtester.py            # single-strategy backtest runners
      multi_backtester.py      # multi-strategy comparison runner
      portfolio.py             # paper portfolio tracking
      risk_manager.py          # position sizing + risk limits
      execution.py             # turns signals into (paper) trades
      backtest_persistence.py  # save backtest runs/trades into DB
      utils.py                 # logging/time helpers
    strategies/
      __init__.py
      base.py                  # BaseStrategy + StrategySignal
      trend_ema.py             # EMA trend-following strategy
      mean_reversion_bb.py     # Bollinger mean-reversion strategy
      squeeze_breakout.py      # volatility squeeze breakout strategy
      grid_ladder.py           # simple ladder/grid strategy
    db/
      __init__.py
      base.py
      models.py                # OHLCV, BacktestRun, BacktestTrade
      init_db.py               # DB init (create tables)
    llm/
      __init__.py
      meta_controller.py       # (stub) for future LLM orchestration
      journaler.py             # (stub) for future daily summaries
    scripts/
      fetch_ohlcv_to_db.py     # load OHLCV from exchange into DB
      run_backtest.py          # CLI for backtests
      run_live.py              # CLI for paper live trading
      run_paper.py             # alias / future extension
    tests/
      ...                      # basic tests for strategies, backtester, DB

Core concepts and requirements

1) Dependencies
Create a requirements.txt (or pyproject) including at minimum:
- backtesting
- ccxt
- pandas
- numpy
- sqlalchemy
- python-dotenv
- pyyaml

2) ExchangeClient (core/exchange_client.py)
- Thin wrapper around ccxt for Binance.US.
- __init__(exchange_name="binanceus", api_key=None, api_secret=None, sandbox=False):
  - Use env vars EXCHANGE_API_KEY, EXCHANGE_API_SECRET when args are None.
  - enableRateLimit = True.
  - If sandbox is true and supported, set_sandbox_mode(True).
- Methods:
  - fetch_ohlcv(symbol, timeframe="4h", limit=500, since=None) -> pandas.DataFrame
    - Return df indexed by timestamp (UTC) with columns: open, high, low, close, volume.
  - get_balance(asset="USDT") -> float
  - create_order(symbol, side, order_type, amount, price=None, params=None)
    - Support "market" and "limit".
  - cancel_order(order_id, symbol)
  - get_open_orders(symbol=None) -> list[dict]
  - now() -> datetime.utcnow()

3) DB schema (db/models.py) and init (db/init_db.py)
Use SQLAlchemy with a default SQLite DB at HOT_CRYPTO_DB_URL (default "sqlite:///data/hot_crypto.db").

Tables:
- OHLCV:
  - id, exchange, symbol, timeframe, ts, open, high, low, close, volume
  - Unique(exchange, symbol, timeframe, ts)
- BacktestRun:
  - id, created_at, exchange, symbol, timeframe, strategy_name
  - initial_cash, final_equity, max_drawdown_pct, sharpe_ratio, trades_count
  - stats_json (raw stats from Backtesting.py)
- BacktestTrade:
  - id, backtest_run_id (FK -> BacktestRun.id)
  - symbol, strategy_name
  - side ('LONG'/'SHORT'), size
  - entry_ts, exit_ts
  - entry_price, exit_price
  - pnl, pnl_pct, max_dd_pct

init_db.py:
- get_db_url() reads HOT_CRYPTO_DB_URL with default sqlite path.
- init_db() creates engine, ensures directory exists, Base.metadata.create_all().

4) DataSource abstraction (core/data_source.py, core/sql_data_source.py, core/ccxt_data_source.py)
- DataSource ABC with:
  - get_ohlcv(symbol: str, timeframe: str, limit: int = 1000) -> pandas.DataFrame
- SQLDataSource:
  - Uses SQLAlchemy to query ohlcv table and return OHLCV.
- CCXTDataSource:
  - Wraps ExchangeClient.fetch_ohlcv.

5) Strategy interface (strategies/base.py)
- StrategySignal dataclass:
  - symbol: str
  - action: str  # "OPEN_LONG", "CLOSE_LONG", "OPEN_SHORT", "CLOSE_SHORT", "HOLD"
  - risk_r: float = 1.0
  - extra: dict | None = None  # e.g. stop, tp, atr, etc.
- BaseStrategy:
  - __init__(config: dict)
  - self.config, self.state (dict)
  - on_bar(self, symbol: str, candle: dict) -> StrategySignal
    - candle has time, open, high, low, close, volume.
  - Live strategies will use self.state[symbol]["df"] (pandas DataFrame of recent candles).

6) Implement these 4 strategies (both Backtesting.py and Live versions)
Use helper functions for EMA, ATR, and Bollinger Bands so they’re shared.

a) Trend EMA (trend_ema.py)
- TrendEmaBacktest (Backtesting.Strategy)
  - Indicators: EMA(20), EMA(50), ATR(14).
  - LONG-only:
    - If flat and EMA20 > EMA50 and close > EMA20:
      - risk_per_share = ATR * atr_stop_mult (e.g. 1.5)
      - risk_amount = equity * risk_per_trade (e.g. 1%)
      - size = floor(risk_amount / risk_per_share)
      - stop = entry - risk_per_share
      - tp = entry + rr_ratio * (entry - stop)
- TrendEmaLive(BaseStrategy)
  - Same logic, but uses df in self.state[symbol]["df"] and returns StrategySignal with extra["stop"] and extra["rr_ratio"].

b) Mean Reversion Bollinger (mean_reversion_bb.py)
- MeanReversionBBBacktest:
  - Indicators: SMA(20), STD(20), Bollinger bands (±2*STD), ATR(14).
  - LONG:
    - If flat and close < lower band: open long, stop below low or close - 2*ATR, TP at midline MA.
  - SHORT:
    - If flat and close > upper band: open short, stop above high, TP at midline MA.
- MeanReversionBBLive:
  - Same logic in on_bar, returning StrategySignal.

c) Squeeze Breakout (squeeze_breakout.py)
- SqueezeBreakoutBacktest:
  - Indicators: Bollinger MA/Upper/Lower, Bandwidth = (Upper-Lower)/MA, ATR(14).
  - in_squeeze when Bandwidth < bandwidth_thresh.
  - If flat and in_squeeze:
    - If close > upper: long breakout with ATR-based stop + rr_ratio TP.
    - If close < lower: short breakout similarly.
- SqueezeBreakoutLive:
  - Same logic, returning StrategySignal.

d) Grid Ladder (grid_ladder.py)
- GridLadderBacktest:
  - Indicators: SMA(50), ATR(14).
  - For i in 1..levels:
    - buy_level_i = MA - i*step_atr_mult*ATR
    - If flat at that level and bar low <= buy_level_i <= bar high: open a small long, TP at MA.
    - When close >= MA, close that level’s position.
- GridLadderLive:
  - Maintain per-level state in self.state[symbol]["levels"] and emit OPEN_LONG/CLOSE_LONG signals per level.

7) Backtesting runners (core/backtester.py, core/multi_backtester.py)
- prepare_ohlcv_for_backtesting(df) -> rename to Open,High,Low,Close,Volume.
- Single-strategy runner, e.g. run_trend_ema_backtest(symbol, timeframe, limit, cash, commission, use_sql=False, db_url=None, persist=False, strategy_name="TREND_EMA").
  - Use DataSource (SQLDataSource or CCXTDataSource).
  - Build Backtest, run, print stats.
  - Extract trades DataFrame (inspect Backtesting.py stats to get the correct key).
  - If persist=True, call backtest_persistence.save_backtest_to_db().

- Multi-strategy runner (core/multi_backtester.py):
  - Given symbols + timeframe, run all 4 strategies (TREND_EMA, MR_BB, SQZ_BO, GRID_LR).
  - Return a pandas DataFrame with: symbol, strategy, final_equity, max_drawdown, sharpe, trades_count.
  - Optionally persist all runs.

8) Persistence (core/backtest_persistence.py)
- Implement save_backtest_to_db(stats, trades_df, exchange, symbol, timeframe, strategy_name, initial_cash, db_url=None).
- Introspect stats keys and the trades DataFrame columns from Backtesting.py to map them correctly:
  - final_equity, max_drawdown_pct, sharpe_ratio, trades_count.
  - For each trade: side, size, entry_ts, exit_ts, entry_price, exit_price, pnl, pnl_pct, max_dd_pct.
- Use SQLAlchemy Session with get_db_url().

9) Paper live trading engine
- Portfolio (core/portfolio.py):
  - Track cash and per-symbol positions (side, size, entry_price, stop, tp).
  - get_equity(current_prices: dict) -> float.
  - open_long/close_long (and stubs for shorts).
- RiskManager (core/risk_manager.py):
  - default_risk_per_trade, max_daily_loss_pct.
  - compute_position_size(equity, atr_value, atr_stop_mult, risk_r=1.0) -> int.
  - can_open_new_trade(equity) -> bool based on daily PnL and max_daily_loss_pct.
  - register_trade_pnl(pnl, equity_before).
- Executor (core/execution.py):
  - execute_signal(symbol, signal, latest_candle, strategy_name):
    - If live=False (paper mode), use Portfolio only.
    - For OPEN_LONG/CLOSE_LONG, open/close positions and register PnL with RiskManager.
- scripts/run_live.py:
  - Read config/settings.yaml and config/strategies.yaml.
  - Instantiate ExchangeClient, Portfolio, RiskManager, Executor (live=False), and active strategies.
  - For each symbol:
    - Fetch a rolling OHLCV window, keep in strategy.state[symbol]["df"].
  - Main loop:
    - Periodically refetch last N candles.
    - Detect new closed bar (new timestamp).
    - Update df, build candle dict.
    - For each enabled strategy, call on_bar(symbol, candle).
    - Pass non-HOLD signals into Executor.

10) Config files
- config/settings.yaml:
  - exchange.name, exchange.sandbox
  - db.url (optional override)
  - risk.default_risk_per_trade, risk.max_daily_loss_pct
  - backtest.default_cash, backtest.commission_pct
- config/strategies.yaml:
  - entries for trend_ema, mean_reversion_bb, squeeze_breakout, grid_ladder
  - each has enabled: true/false, symbols, timeframe, params.
- config/markets.yaml:
  - list of symbol/timeframe pairs.

11) Scripts
- scripts/fetch_ohlcv_to_db.py:
  - CLI args: --exchange, --symbol, --timeframe, --limit.
  - Use ExchangeClient to fetch OHLCV.
  - Upsert into ohlcv with INSERT ... ON CONFLICT DO UPDATE (SQLite style).
- scripts/run_backtest.py:
  - CLI: symbol, timeframe, strategy, --all, --use-sql, --persist, --db-url.
  - For --all, run multi_backtester over BTC/USDT and ETH/USDT and print table.
- scripts/run_live.py:
  - CLI: optional overrides, otherwise use config.

Development process (important)
Work in PHASES, and at the end of each phase:
- Show me the directory tree.
- Show me key files changed.
- Show me how to run tests or commands to verify.

Phases:
1) Skeleton project: folders, config stubs, requirements, README.
2) DB models + init_db + fetch_ohlcv_to_db (verify DB fills with candles).
3) DataSource abstraction + ExchangeClient + single-strategy TrendEma backtest from SQL and ccxt.
4) Implement the 3 other strategies and multi_backtester.
5) Implement backtest_persistence and wire persistence into all backtest runners.
6) Implement paper Portfolio, RiskManager, Executor, and run_live paper loop for at least TREND_EMA and MR_BB.
7) Clean up, add a few basic tests, and update README with usage examples.

Always:
- Keep API keys and DB URLs in env/.env, never hardcode secrets.
- Favor clarity, docstrings, and comments over clever one-liners.
- Make sure the project can run from the command line with the documented commands.
