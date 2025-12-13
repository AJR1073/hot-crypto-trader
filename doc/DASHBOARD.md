# HOT-Crypto Dashboard Guide

## Overview

The dashboard provides a visual control room for inspecting backtest results.

## Installation

```bash
pip install -r requirements.txt
```

Or just the dashboard dependencies:
```bash
pip install streamlit>=1.32 plotly>=5.0
```

## Usage

```bash
streamlit run dashboard_streamlit.py
```

Then open http://localhost:8501 in your browser.

## Required Database Tables

| Table | Description |
|-------|-------------|
| `ohlcv` | Historical candle data |
| `backtest_runs` | Backtest metadata and summary stats |
| `backtest_trades` | Individual trades from backtests |

## Features

### Sidebar
- **Database Path**: Change database location
- **Filters**: Symbol, Strategy, Timeframe
- **Reload Data**: Refresh from database

### Runs Table
- All backtest runs sorted by return
- Columns: ID, symbol, strategy, timeframe, cash, equity, return%, drawdown%, Sharpe, trades

### Run Details
- Metrics cards: cash, equity, return, drawdown, Sharpe, trade count
- Trades table
- Plotly equity curve chart
- Plotly PnL distribution histogram

### Run Backtest
- Configure and run new backtests from the UI
- Supports single strategy or all strategies mode
- Auto-persists results to database

## Troubleshooting

**"No backtest runs found"**
```bash
python scripts/run_backtest.py --all --use-sql --persist
```

**Database not found**
```bash
python -m db.init_db
```

**Missing columns error**
The dashboard handles missing columns gracefully. Update your database schema if needed.
