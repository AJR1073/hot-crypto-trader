# 🔥 HOT-Crypto Trading Engine

A modular Python-based cryptocurrency algo trading engine built for **Kraken** exchange, featuring:
- **11 backtesting strategies** with regime-aware ensemble aggregation
- **Paper & live trading** with multi-layered risk management
- **Circuit breakers** (asset-level, portfolio kill switch, flash crash detector)
- **Half-Kelly position sizing** with volatility targeting
- **Streamlit dashboard** for backtesting and monitoring
- **SQLite persistence** for OHLCV data, backtests, and paper trades

## Quick Start

```bash
# Clone and install
git clone <repo-url>
cd hot-crypto-trader
pip install -r requirements.txt

# Initialize database
python -m db.init_db

# Fetch Kraken data
python scripts/fetch_ohlcv_to_db.py --symbol BTC/USD --timeframe 4h --limit 500
python scripts/fetch_ohlcv_to_db.py --symbol ETH/USD --timeframe 4h --limit 500

# Run backtests
python scripts/run_backtest.py --all --use-sql --persist

# Launch dashboard
streamlit run dashboard_streamlit.py

# Paper trading (single cycle)
python scripts/run_live.py --paper --use-sql --once

# Continuous paper trading with live data refresh
python scripts/run_live.py --paper --use-sql --refresh-from-ccxt
```

## Project Structure

```
hot-crypto-trader/
├── config/
│   ├── live.yaml              # Live/paper trading config
│   ├── strategies.yaml        # Strategy parameters & enabled flags
│   ├── strategies_1m.yaml     # 1-minute scalp strategies
│   ├── settings.yaml          # General settings
│   └── markets.yaml           # Monitored symbol/timeframe pairs
├── core/
│   ├── backtester.py          # Backtesting engine
│   ├── multi_backtester.py    # Multi-strategy runner
│   ├── portfolio.py           # Paper portfolio with slippage
│   ├── risk_manager.py        # Half-Kelly sizing, vol targeting, correlation guard
│   ├── exchange_client.py     # CCXT wrapper for Kraken
│   ├── execution.py           # Idempotent order state machine
│   ├── circuit_breaker.py     # Multi-layer circuit breakers
│   ├── rate_limiter.py        # Token-bucket API rate limiter
│   ├── regime_detector.py     # Market regime classification (Hurst, ADX)
│   ├── ensemble.py            # Regime-aware signal aggregation
│   ├── scanner.py             # Market scanner for movers
│   ├── moonshot.py            # Low-cap gem detector
│   ├── data_source.py         # Data source ABC
│   ├── sql_data_source.py     # SQLite data source
│   ├── ccxt_data_source.py    # Live CCXT data source
│   └── paper_persistence.py   # Paper trade logging
├── db/
│   ├── models.py              # SQLAlchemy models (LiveOrder, CircuitBreakerState, TaxLedger)
│   ├── persistence.py         # Backtest persistence
│   └── init_db.py             # Database initialization
├── strategies/
│   ├── squeeze_breakout.py    # Bollinger squeeze breakout
│   ├── mean_reversion_bb.py   # Bollinger mean reversion
│   ├── trend_ema.py           # EMA crossover
│   ├── supertrend.py          # ATR-based trend follower
│   ├── turtle.py              # Donchian channel breakout
│   ├── triple_momentum.py     # RSI + MACD + Stochastic
│   ├── volatility_hunter.py   # Extreme BB + RSI for small-caps
│   ├── grid_ladder.py         # Grid/DCA trading
│   ├── rsi_divergence.py      # RSI divergence detection
│   ├── macd_crossover.py      # MACD signal crossover
│   ├── ichimoku.py            # Ichimoku cloud strategy
│   ├── vwap_bounce.py         # VWAP bounce strategy
│   ├── dual_thrust.py         # Range breakout
│   └── indicators.py          # Shared indicator library
├── scripts/
│   ├── run_backtest.py        # Backtest CLI
│   ├── run_live.py            # Paper/live trading loop
│   ├── fetch_ohlcv_to_db.py   # OHLCV data fetcher
│   ├── test_scanner.py        # Scanner testing
│   └── scan_moonshots.py      # Moonshot scanner
├── tests/
│   ├── test_regime_detector.py
│   ├── test_circuit_breaker.py
│   ├── test_risk_manager_v2.py
│   ├── test_ensemble.py
│   ├── test_execution.py
│   └── test_basic.py
├── doc/
│   ├── ARCHITECTURE.md        # System architecture
│   ├── STRATEGIES.md          # Strategy documentation
│   ├── LIVE_TRADING.md        # Live trading guide
│   ├── PROJECT_BRIEF.md       # Project brief
│   └── DASHBOARD.md           # Dashboard guide
├── dashboard_streamlit.py     # Streamlit dashboard
├── requirements.txt
└── data/
    └── hot_crypto.db          # SQLite database
```

## Strategies

| Strategy | Type | Timeframe | Description |
|----------|------|-----------|-------------|
| **Squeeze Breakout** | Momentum | 4h | Bollinger squeeze → breakout detection |
| **Mean Reversion BB** | Mean Reversion | 4h | Buy at lower BB, sell at SMA |
| **Trend EMA** | Trend | 1d | EMA(20)/EMA(50) crossover |
| **SuperTrend** | Trend | 1d | ATR-based dynamic support/resistance |
| **Turtle** | Breakout | 1d | Donchian channel breakout (20/10) |
| **Triple Momentum** | Momentum | 4h | RSI + MACD + Stochastic consensus |
| **Volatility Hunter** | Mean Reversion | 4h | Extreme BB + RSI for volatile coins |
| **Grid Ladder** | DCA | 4h | Grid levels below SMA(50) |
| **RSI Divergence** | Divergence | 4h | Price/RSI divergence detection |
| **MACD Crossover** | Momentum | 4h | MACD signal line crossover |
| **Ichimoku** | Trend | 1d | Ichimoku cloud strategy |

## Risk Management

| Layer | Description |
|-------|-------------|
| **Half-Kelly Sizing** | Position size based on Kelly criterion (capped at 5%) |
| **Volatility Targeting** | Scale positions to 15% annualized volatility |
| **Correlation Guard** | Reduce exposure when assets are correlated |
| **Circuit Breakers** | Asset-level, portfolio kill switch, consecutive loss, flash crash |
| **Daily Loss Limit** | 2% max daily portfolio loss |
| **Max Drawdown** | 10% max drawdown from equity peak |
| **Cooldown Period** | 4-hour cooldown after losses |

## Exchange: Kraken

- **Pairs**: BTC/USD, ETH/USD (native USD, not stablecoins)
- **Fees**: Maker 0.16%, Taker 0.26%
- **Rate Limits**: 15 req/sec private, 1 req/sec matching
- **Account Type**: Supports business/LLC accounts (IRA-LLC compatible)

## Environment Variables

```env
EXCHANGE_API_KEY=your_kraken_api_key
EXCHANGE_API_SECRET=your_kraken_api_secret
HOT_CRYPTO_DB_URL=sqlite:///data/hot_crypto.db  # Optional override
LOG_LEVEL=INFO
```

## Testing

```bash
# Run all tests (56 passing)
pytest

# Specific test suites
pytest tests/test_regime_detector.py -v
pytest tests/test_circuit_breaker.py -v
pytest tests/test_risk_manager_v2.py -v
pytest tests/test_ensemble.py -v
```

## Documentation

- [Architecture](doc/ARCHITECTURE.md) — System design and data flow
- [Strategies](doc/STRATEGIES.md) — Detailed strategy documentation
- [Live Trading Guide](doc/LIVE_TRADING.md) — Setup and deployment guide

## License

MIT
