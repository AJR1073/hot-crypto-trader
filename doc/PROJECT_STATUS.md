# HOT-Crypto Trading Engine — Project Status

> **Last Updated**: February 17, 2026
> **Exchange**: Kraken (switched from Binance.US)
> **Account Type**: IRA-LLC
> **Status**: Paper trading operational, live trading pending API key setup

## Current State

### What's Built & Working

**Core Trading Pipeline** (end-to-end verified):
```
Kraken OHLCV → SQLite → Regime Detection → Strategy Ensemble → Risk Manager → Circuit Breakers → Execution Engine → Portfolio
```

**Phase 1 — Core Infrastructure** ✅
- `core/regime_detector.py` — Hurst exponent + ADX market regime classification (TRENDING_STRONG, TRENDING_WEAK, MEAN_REVERTING, RANDOM_WALK)
- `core/circuit_breaker.py` — 4-layer protection: asset-level (15% drop), portfolio kill switch (10% equity loss), consecutive loss (3), flash crash (20%)
- `core/rate_limiter.py` — Token-bucket limiter, 900 req/min for Kraken private API
- `core/execution.py` — Idempotent order state machine with `clientOrderId`, paper & live modes
- `core/exchange_client.py` — CCXT wrapper for Kraken with min order size validation
- `db/models.py` — SQLAlchemy models: LiveOrder, CircuitBreakerState, TaxLedger

**Phase 2 — Advanced Risk & Signals** ✅
- `core/risk_manager.py` — Half-Kelly position sizing, 15% volatility targeting, correlation guard
- `core/ensemble.py` — Regime-aware signal aggregation with 2-of-3 consensus rule

**11 Trading Strategies** (7 enabled, 4 disabled):
| Strategy | Type | Timeframe | Status | Notes |
|----------|------|-----------|--------|-------|
| Squeeze Breakout | Momentum | 4h | ✅ Enabled | Primary strategy |
| Mean Reversion BB | Mean Reversion | 4h | ✅ Enabled | +25.45% on AXS |
| SuperTrend | Trend | 1d | ✅ Enabled | ATR-based |
| Turtle | Breakout | 1d | ✅ Enabled | +8.20% backtest |
| Triple Momentum | Momentum | 4h | ✅ Enabled | RSI+MACD+Stoch |
| Volatility Hunter | Mean Reversion | 4h | ✅ Enabled | FET +18%, JUP +14% |
| Mean Reversion Scalp | Scalp | 1m | ✅ Enabled | BTC only |
| Trend EMA | Trend | 1d | Disabled | |
| Grid Ladder | DCA | 4h | Disabled | |
| RSI Divergence | Divergence | 4h | Disabled | |
| MACD Crossover | Momentum | 4h | Disabled | |

**Testing**: 56/56 unit tests passing
- `test_regime_detector.py` — 13 tests
- `test_circuit_breaker.py` — 15 tests
- `test_risk_manager_v2.py` — 16 tests
- `test_ensemble.py` — 12 tests

**Data**: 1,000 real Kraken candles loaded (500 BTC/USD + 500 ETH/USD, Nov 2025 – Feb 2026)

**Paper Trading**: Single cycle verified — all strategies processed, signals generated, portfolio tracking working.

### Exchange Configuration

| Setting | Value |
|---------|-------|
| Exchange | Kraken (via CCXT) |
| Pairs | BTC/USD, ETH/USD (native USD, not stablecoins) |
| Maker fee | 0.16% |
| Taker fee | 0.26% |
| Rate limit | 15 req/sec private API |
| Min order | ~$10 notional |
| Account | IRA-LLC business account |

### Risk Parameters (Current Config)

| Parameter | Value |
|-----------|-------|
| Initial capital | $10,000 |
| Risk per trade | 0.5% ($50) |
| Max open positions | 2 |
| Max daily loss | 2% ($200) |
| Max drawdown | 10% ($1,000) |
| Cooldown after loss | 4 hours |
| Position sizing | Half-Kelly with vol targeting |

## What's NOT Built Yet

### Phase 3 — Monitoring & Real-Time (Next)
- [ ] **Telegram Notifications** — Trade alerts, circuit breaker trips, daily PnL summaries
- [ ] **WebSocket Data Streams** — Replace polling with Kraken WebSocket for real-time orderbook/ticker
- [ ] **Enhanced Dashboard** — Real-time portfolio monitoring, position tracking

### Phase 4 — Compliance & Scaling
- [ ] **UBIT Tracking** — Unrelated Business Income Tax logging for IRA-LLC
- [ ] **Tax Report Generation** — CSV/PDF reports from tax_ledger table
- [ ] **Wash Sale Avoidance** — Logic for non-IRA accounts
- [ ] **Sharpe-Based Capital Scaling** — Dynamic allocation based on rolling Sharpe ratio
- [ ] **Drawdown Recovery** — Reduced position sizes during drawdown periods

### Known Issues / Tech Debt
- `test_execution.py` needs mock portfolio fixture alignment (not blocking)
- `datetime.utcnow()` deprecation warnings (Python 3.12+ recommends `datetime.now(UTC)`)
- Dashboard still references some hardcoded defaults that could be config-driven

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Exchange API | CCXT ≥ 4.0.0 |
| Database | SQLite (via SQLAlchemy) |
| Dashboard | Streamlit + Plotly |
| Testing | pytest |
| Data | Pandas, NumPy |
| Config | YAML |

## Key Files for Context

| File | Purpose |
|------|---------|
| `config/live.yaml` | All runtime configuration |
| `config/strategies.yaml` | Strategy parameters and enable flags |
| `core/risk_manager.py` | Position sizing and risk controls |
| `core/ensemble.py` | Signal aggregation logic |
| `core/circuit_breaker.py` | Trading safety systems |
| `core/execution.py` | Order management state machine |
| `scripts/run_live.py` | Main trading loop entry point |
| `doc/ARCHITECTURE.md` | System architecture and data flow |
| `doc/STRATEGIES.md` | Detailed strategy documentation |
| `doc/LIVE_TRADING.md` | Setup and deployment guide |

## IRA-LLC Compliance Considerations

1. **UBIT Risk**: Active algo trading may trigger Unrelated Business Income Tax — tax advisor consultation needed
2. **Prohibited Transactions**: All trades flow through LLC, never personal accounts
3. **Wash Sales**: Not applicable within IRA, but relevant for any non-IRA trading
4. **Stablecoin Risk**: Eliminated by using Kraken's native USD pairs
5. **Record Keeping**: `tax_ledger` table tracks all tax lots
