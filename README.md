# 🔥 HOT-Crypto Trading Engine

A modular Python-based cryptocurrency trading engine with:
- **4 backtesting strategies** (Trend EMA, Mean Reversion BB, Squeeze Breakout, Grid Ladder)
- **Paper trading** with risk management and portfolio simulation
- **Streamlit dashboard** for visualizing backtest results
- **SQLite persistence** for OHLCV data, backtests, and paper trades

## Quick Start

```bash
# Clone and install
git clone <repo-url>
cd hot-crypto-trader
pip install -r requirements.txt

# Initialize database
python -m db.init_db

# Fetch historical data
python scripts/fetch_ohlcv_to_db.py --symbol BTC/USDT --timeframe 4h --limit 500
python scripts/fetch_ohlcv_to_db.py --symbol ETH/USDT --timeframe 4h --limit 500

# Run backtests
python scripts/run_backtest.py --all --use-sql --persist

# Launch dashboard
streamlit run dashboard_streamlit.py

# Paper trading
python scripts/run_live.py --paper --use-sql --symbols BTC/USDT,ETH/USDT --once
```

## Project Structure

```
hot-crypto-trader/
├── config/
│   ├── live.yaml         # Paper trading config
│   ├── strategies.yaml   # Strategy parameters
│   ├── settings.yaml     # General settings
│   └── markets.yaml      # Market symbols
├── core/
│   ├── backtester.py     # Backtesting engine
│   ├── multi_backtester.py # Multi-strategy runner
│   ├── portfolio.py      # Paper portfolio with slippage
│   ├── risk_manager.py   # Position sizing and limits
│   ├── exchange_client.py # CCXT wrapper
│   ├── data_source.py    # Data source ABC
│   ├── sql_data_source.py
│   ├── ccxt_data_source.py
│   └── paper_persistence.py
├── db/
│   ├── models.py         # SQLAlchemy models
│   ├── persistence.py    # Backtest persistence
│   └── init_db.py        # Database initialization
├── strategies/
│   ├── trend_ema.py      # EMA crossover strategy
│   ├── mean_reversion_bb.py # Bollinger mean reversion
│   ├── squeeze_breakout.py  # Volatility squeeze
│   ├── grid_ladder.py    # Grid/DCA trading
│   └── indicators.py     # Shared indicator functions
├── scripts/
│   ├── run_backtest.py   # Backtest CLI
│   ├── run_live.py       # Paper trading loop
│   ├── fetch_ohlcv_to_db.py
│   └── dashboard.py
├── dashboard_streamlit.py # Enhanced Plotly dashboard
├── requirements.txt
└── data/
    └── hot_crypto.db     # SQLite database
```

## Strategies

| Strategy | Description | Entry | Exit |
|----------|-------------|-------|------|
| **TREND_EMA** | EMA crossover trend following | EMA(20) > EMA(50) | EMA cross or ATR stop |
| **MR_BB** | Bollinger Bands mean reversion | Close < Lower BB | Price reaches SMA(20) |
| **SQZ_BO** | Squeeze breakout (best performer) | Breakout after squeeze | Price < midline |
| **GRID_LR** | Grid/DCA ladder below SMA | 5 levels below SMA(50) | Price >= SMA |
| **SUPERTREND** | ATR-based trend follower | Close > SuperTrend line | Close < SuperTrend line |

## Backtest Commands

```bash
# Single strategy
python scripts/run_backtest.py --symbol BTC/USDT --timeframe 4h --strategy SQZ_BO --use-sql --persist

# All strategies comparison
python scripts/run_backtest.py --all --timeframe 4h --use-sql --persist

# Custom symbols and cash
python scripts/run_backtest.py --all --symbols BTC/USDT,ETH/USDT,SOL/USDT --cash 50000 --use-sql
```

## Paper Trading

Paper trading simulates live trading without real orders:

```bash
# Single cycle (debug)
python scripts/run_live.py --paper --use-sql --symbols BTC/USDT,ETH/USDT --once

# Continuous loop
python scripts/run_live.py --paper --use-sql --symbols BTC/USDT,ETH/USDT

# With CCXT refresh
python scripts/run_live.py --paper --use-sql --refresh-from-ccxt
```

### Risk Controls

| Parameter | Default | Description |
|-----------|---------|-------------|
| `risk_per_trade` | 0.5% | Account risk per trade |
| `max_open_positions` | 2 | Max concurrent positions |
| `max_daily_loss_pct` | 2% | Daily loss limit |
| `max_total_drawdown_pct` | 10% | Max drawdown from peak |
| `cooldown_minutes_after_loss` | 240 | Wait time after loss |

## Timeframe Recommendations (Optimized)
- **1h (Hourly)**: Best for **MR_BB** (Mean Reversion).
- **4h (4-Hour)**: Best for **SQZ_BO** (Squeeze Breakout).
- **1d (Daily)**: Best for **TREND_EMA** and **SUPERTREND**.

## Dashboard

```bash
# Enhanced dashboard with Plotly
streamlit run dashboard_streamlit.py
```

Features:
- Filter by symbol, strategy, timeframe
- **"All" Timeframe**: Run backtests across 1h, 4h, and 1d simultaneously
- Metrics cards (return, drawdown, Sharpe)
- Interactive equity curve charts
- PnL distribution histograms
- Run backtests from UI

## Database Tables

| Table | Description |
|-------|-------------|
| `ohlcv` | OHLCV candle data |
| `backtest_runs` | Backtest metadata and stats |
| `backtest_trades` | Individual backtest trades |
| `paper_runs` | Paper trading sessions |
| `paper_events` | Paper trading event log |
| `paper_trades` | Simulated paper trades |

## Environment Variables

Create a `.env` file:

```env
EXCHANGE_API_KEY=your_api_key
EXCHANGE_API_SECRET=your_secret
HOT_CRYPTO_DB_URL=sqlite:///data/hot_crypto.db
LOG_LEVEL=INFO
```

## Development

```bash
# Run tests
pytest

# Format code
black .
isort .
```

## License

MIT
