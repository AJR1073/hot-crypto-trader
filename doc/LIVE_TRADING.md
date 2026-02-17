# Live Trading Guide

## Prerequisites

1. **Kraken Account** — Create a Kraken account (supports business/LLC accounts for IRA)
2. **API Keys** — Generate in Kraken dashboard with permissions:
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ❌ Withdraw Funds (keep disabled for safety)
3. **Python 3.10+** with dependencies installed

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
export EXCHANGE_API_KEY="your_kraken_api_key"
export EXCHANGE_API_SECRET="your_kraken_api_secret"
```

Or create a `.env` file:

```env
EXCHANGE_API_KEY=your_kraken_api_key
EXCHANGE_API_SECRET=your_kraken_api_secret
```

### 3. Initialize Database

```bash
python -m db.init_db
```

### 4. Fetch Historical Data

```bash
python scripts/fetch_ohlcv_to_db.py --symbol BTC/USD --timeframe 4h --limit 500
python scripts/fetch_ohlcv_to_db.py --symbol ETH/USD --timeframe 4h --limit 500
```

### 5. Configure Strategies

Edit `config/strategies.yaml` to enable/disable strategies and adjust parameters.

Edit `config/live.yaml` to set:
- Trading symbols
- Risk parameters
- Initial capital
- Loop timing

## Paper Trading

Paper trading simulates trades without placing real orders:

```bash
# Single cycle — run strategies once and exit
python scripts/run_live.py --once

# Continuous loop — run every 60 seconds
python scripts/run_live.py

# With live data refresh from Kraken
python scripts/run_live.py --refresh-from-ccxt

# Dry run — print config and exit
python scripts/run_live.py --dry-run
```

### What Happens Each Cycle

1. Load OHLCV from database for each symbol
2. Run all enabled strategies on latest bar
3. Check risk manager (position sizing, daily limits, drawdown)
4. Check circuit breakers (asset drops, portfolio protection)
5. Execute signals in paper portfolio (simulated fills with slippage)
6. Log results to database

## Risk Controls

### Position Sizing

| Parameter | Default | Config Key |
|-----------|---------|-----------|
| Risk per trade | 0.5% | `risk.risk_per_trade` |
| Max open positions | 2 | `risk.max_open_positions` |
| Max daily loss | 2% | `risk.max_daily_loss_pct` |
| Max total drawdown | 10% | `risk.max_total_drawdown_pct` |
| Cooldown after loss | 4 hours | `risk.cooldown_minutes_after_loss` |

### Circuit Breakers

All circuit breakers are described in `config/live.yaml`:

```yaml
circuit_breakers:
  asset_drop_pct: 0.15        # 15% single-asset drop
  asset_lockout_hours: 4
  portfolio_kill_pct: 0.10    # 10% portfolio drop → kill switch
  portfolio_lockout_hours: 24
  consecutive_loss_limit: 3
  flash_crash_pct: 0.20       # 20% drop in 1 bar
```

## Kraken-Specific Notes

### Symbol Format
Kraken uses native USD pairs: `BTC/USD`, `ETH/USD` (not USDT).

### Fees
- Maker: 0.16%
- Taker: 0.26%
- Commission is set in `config/live.yaml` as `commission: 0.0026`

### Rate Limits
- Private API: 15 requests/second (900/minute)
- Matching engine: 1 request/second
- The built-in rate limiter handles this automatically

### Minimum Order Size
Most Kraken pairs have a ~$10 minimum notional value. The exchange client validates this before submitting orders.

## IRA-LLC Compliance Notes

If trading through an IRA-owned LLC:

1. **UBIT Risk**: Active algo trading may trigger Unrelated Business Income Tax — consult your tax advisor
2. **Prohibited Transactions**: All trades must flow through the LLC account, never personal
3. **Wash Sales**: Not applicable within an IRA, but relevant if also trading outside IRA
4. **Record Keeping**: The `tax_ledger` database table tracks tax lots for compliance
5. **Stablecoin Risk**: Avoided by using Kraken's native USD pairs

## Monitoring

### Dashboard

```bash
streamlit run dashboard_streamlit.py
```

### Logs

Trading events are logged to both console and database:
- `paper_events` table: all trade signals, executions, and system events
- `paper_trades` table: individual trade records with entry/exit prices
- Console: INFO-level real-time logging

## Transition to Live Trading

When ready to move from paper to live:

1. Validate paper trading results over 2+ weeks
2. Update `config/live.yaml`:
   ```yaml
   paper_trading: false
   execution:
     mode: live
   ```
3. Start with small position sizes (reduce `risk_per_trade`)
4. Monitor closely for the first few trading sessions
