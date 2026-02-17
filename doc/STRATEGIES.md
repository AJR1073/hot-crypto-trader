# Strategies

## Overview

HOT-Crypto includes 11 trading strategies spanning trend following, mean reversion, momentum, and breakout categories. Strategies are configured in `config/strategies.yaml` and can be individually enabled/disabled.

## Enabled Strategies

### Squeeze Breakout (`squeeze_breakout`)
- **Type**: Momentum / Breakout
- **Timeframe**: 4h
- **Symbols**: BTC/USD, ETH/USD
- **Logic**: Detects Bollinger Band squeeze (bandwidth < 4%) then enters on breakout direction
- **Entry**: Band expansion after squeeze with volume confirmation
- **Exit**: Price crosses back below midline or ATR trailing stop (1.5× ATR)
- **Risk**: 0.5% per trade

### Mean Reversion BB (`mean_reversion_bb`)
- **Type**: Mean Reversion
- **Timeframe**: 4h
- **Symbols**: BTC/USD, ETH/USD + altcoins (AXS, BONK, SHIB, FET, JUP, IMX)
- **Logic**: Buy when price touches lower Bollinger Band, sell at SMA(20)
- **Entry**: Close < Lower BB (SMA(20) − 2σ)
- **Exit**: Close ≥ SMA(20) or ATR stop (2× ATR)
- **Risk**: 1% per trade
- **Performance**: Best performer on volatile coins (+25.45% on AXS)

### SuperTrend (`supertrend`)
- **Type**: Trend Following
- **Timeframe**: 1d
- **Logic**: ATR-based dynamic support/resistance line
- **Entry**: Close crosses above SuperTrend line
- **Exit**: Close crosses below SuperTrend line
- **Risk**: 1% per trade

### Turtle (`turtle`)
- **Type**: Breakout
- **Timeframe**: 1d
- **Logic**: Donchian channel breakout (20-period entry, 10-period exit)
- **Entry**: Close > 20-period high
- **Exit**: Close < 10-period low or ATR stop (2× ATR)
- **Risk**: 1% per trade
- **Performance**: +8.20% in backtests

### Triple Momentum (`triple_momentum`)
- **Type**: Momentum
- **Timeframe**: 4h
- **Logic**: Consensus of RSI(14), MACD(12/26/9), and Stochastic(14/3)
- **Entry**: All three indicators aligned bullish
- **Exit**: Trailing ATR stop (2× ATR)
- **Risk**: 1.5% base risk

### Volatility Hunter (`volatility_hunter`)
- **Type**: Mean Reversion (extreme)
- **Timeframe**: 4h
- **Symbols**: AXS/USD, BONK/USD, SHIB/USD, FET/USD, JUP/USD
- **Logic**: Extreme Bollinger (3σ) + RSI oversold with volume spike
- **Entry**: Close < Lower BB(3σ) AND RSI < 25 AND volume > 1.3× average
- **Exit**: RSI > 75 or ATR stop
- **Risk**: 2% per trade
- **Performance**: FET +18%, JUP +14%

### Mean Reversion Scalp (`mean_reversion_scalp`)
- **Type**: Scalping
- **Timeframe**: 1m
- **Symbols**: BTC/USD
- **Logic**: Extreme mean reversion on 1-minute bars (3σ bands)
- **Risk**: 0.5% per trade

## Disabled Strategies (Available for Backtesting)

| Strategy | Type | Timeframe | Notes |
|----------|------|-----------|-------|
| **Trend EMA** | Trend | 1d | EMA(20)/EMA(50) crossover |
| **Grid Ladder** | DCA | 4h | 5 grid levels below SMA(50) |
| **RSI Divergence** | Divergence | 4h | Price/RSI divergence detection |
| **MACD Crossover** | Momentum | 4h | MACD signal line cross |
| **Ichimoku** | Trend | 1d | Full Ichimoku cloud system |
| **VWAP Bounce** | Mean Reversion | 1h | VWAP mean reversion |
| **Dual Thrust** | Breakout | 4h | Range breakout strategy |

## Configuration

Each strategy in `config/strategies.yaml`:

```yaml
strategy_name:
  enabled: true/false
  symbols: ["BTC/USD", "ETH/USD"]
  timeframe: "4h"
  params:
    # Strategy-specific parameters
    risk_per_trade: 0.01
```

## Ensemble System

When multiple strategies are enabled, the **Ensemble** module aggregates their signals:

1. Each strategy produces a signal: BUY, SELL, or HOLD
2. The **Regime Detector** classifies the market state
3. Strategies matching the regime get higher voting weight
4. A **2-of-3 consensus** rule determines the final signal
5. Conflicting BUY/SELL signals default to HOLD
