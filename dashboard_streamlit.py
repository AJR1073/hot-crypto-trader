"""
HOT-Crypto Trader - Streamlit Dashboard

A comprehensive control room UI for inspecting backtest results stored in SQLite.

Features:
- View and filter backtest runs
- Inspect individual run metrics, trades, and charts
- Interactive Plotly equity curves and PnL histograms
- Run new backtests directly from the UI

Usage:
    streamlit run dashboard_streamlit.py
"""

import os
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml
from core.scanner import MarketScanner
from core.moonshot import MoonshotScanner
from core.exchange_client import ExchangeClient

def load_live_config():
    try:
        with open("config/live.yaml", "r") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}

def add_symbol_to_configs(symbol):
    """Add symbol to live.yaml and strategies.yaml."""
    try:
        # 1. Update live.yaml
        with open("config/live.yaml", "r") as f:
            live_config = yaml.safe_load(f) or {}
        
        if symbol not in live_config.get("symbols", []):
            if "symbols" not in live_config:
                live_config["symbols"] = []
            live_config["symbols"].append(symbol)
            
            with open("config/live.yaml", "w") as f:
                yaml.dump(live_config, f, sort_keys=False, default_flow_style=False)
            st.toast(f"✅ Added {symbol} to live.yaml", icon="📝")
        
        # 2. Update strategies.yaml (Enable for SuperTrend and SQZ_BO)
        with open("config/strategies.yaml", "r") as f:
            strat_config = yaml.safe_load(f) or {}
            
        updated_strats = False
        for strategy in ["squeeze_breakout", "supertrend", "mean_reversion_scalp"]:
            if strategy in strat_config:
                if "symbols" not in strat_config[strategy]:
                    strat_config[strategy]["symbols"] = []
                
                if symbol not in strat_config[strategy]["symbols"]:
                    strat_config[strategy]["symbols"].append(symbol)
                    updated_strats = True
        
        if updated_strats:
            with open("config/strategies.yaml", "w") as f:
                yaml.dump(strat_config, f, sort_keys=False, default_flow_style=False)
            st.toast(f"✅ Added {symbol} to strategies.yaml", icon="📈")
            
        return True
    except Exception as e:
        st.error(f"Failed to update config: {e}")
        return False

def show_scanner_section():
    st.header("🕵️ Market Scanner")
    
    tab1, tab2 = st.tabs(["Standard Scanner", "🚀 Moonshot 100x Scanner"])
    
    with tab1:
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.markdown("""
            **Find Hot Opportunities**
            
            Scans for coins that are:
            1. 🐦 **Trending** on CoinGecko (Social Hype)
            2. 📈 **Moving** on Exchange (High Volatility)
            """)
            
            scan_btn = st.button("🔍 Run Live Scan", type="primary")
        
        if scan_btn:
            st.session_state['scan_results'] = None # Clear previous
            with st.spinner("Scanning markets... (This takes a few seconds)"):
                try:
                    # Load config
                    config = load_live_config()
                    scanner_config = config.get("scanner", {
                        "min_volume": 1000000,
                        "min_change_pct": 5.0,
                        "max_symbols": 5
                    })
                    
                    # Init scanner
                    client = ExchangeClient(exchange_name="kraken")
                    scanner = MarketScanner(client, scanner_config)
                    
                    # 1. Get Trending
                    trending = scanner.get_coingecko_trending_tickers()
                    
                    # 2. Get Movers
                    movers = scanner.scan_exchange_movers()
                    
                    # 3. Get Hot Picks (Intersection)
                    hot_picks = []
                    trending_set = set(trending)
                    
                    for mover in movers:
                        base = mover['symbol'].split('/')[0]
                        if base in trending_set:
                            hot_picks.append(mover)
                    
                    # Add top movers if needed
                    if len(hot_picks) < 3:
                        for mover in movers:
                            if mover not in hot_picks:
                                hot_picks.append(mover)
                                if len(hot_picks) >= 3:
                                    break
                    
                    # Save to session state to persist after button clicks
                    st.session_state['scan_results'] = {
                        'hot_picks': hot_picks,
                        'trending': trending,
                        'movers': movers
                    }
                            
                except Exception as e:
                    st.error(f"Scan failed: {e}")
        
        # Display results from session state
        if st.session_state.get('scan_results'):
            results = st.session_state['scan_results']
            hot_picks = results['hot_picks']
            trending = results['trending']
            movers = results['movers']

            # Hot Picks Area
            st.subheader("🔥 Hot Picks (Trending + Active)")
            
            if hot_picks:
                for pick in hot_picks:
                    with st.container():
                        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                        c1.markdown(f"**{pick['symbol']}**")
                        c2.markdown(f"Change: **{pick['change']:+.2f}%**")
                        c3.markdown(f"Vol: **${pick['volume']:,.0f}**")
                        
                        # Check if already in config (simple check)
                        live_conf = load_live_config()
                        current_symbols = live_conf.get("symbols", [])
                        
                        if pick['symbol'] in current_symbols:
                            c4.success("✅ Added")
                        else:
                            if c4.button("➕ Add", key=f"add_{pick['symbol']}"):
                                if add_symbol_to_configs(pick['symbol']):
                                    st.rerun()
                    st.divider()
            else:
                st.info("No hot picks found this scan.")

            # Layout for details
            c1, c2 = st.columns(2)
            
            with c1:
                st.subheader("🐦 CoinGecko Trending")
                st.write(", ".join(trending))
                
            with c2:
                st.subheader("📈 Top Exchange Movers")
                if movers:
                    m_df = pd.DataFrame(movers[:10])
                    m_df['volume'] = m_df['volume'].apply(lambda x: f"${x:,.0f}")
                    m_df['change'] = m_df['change'].apply(lambda x: f"{x:+.2f}%")
                    st.dataframe(m_df, use_container_width=True)
                else:
                    st.info("No high volatility movers found.")

    with tab2:
        st.markdown("""
        ### 🚀 Moonshot 100x Scanner
        **Find Low-Cap Gems with High Momentum**
        
        Looks for coins on CoinGecko with:
        - 💰 **Market Cap < $100M** (Small Cap)
        - 📊 **High Volume/MCap Ratio** (Momentum)
        - 💎 **Hidden Gems**
        """)
        
        moon_btn = st.button("🚀 Scan for Moonshots", type="primary")
        
        if moon_btn:
            with st.spinner("Hunting for gems on CoinGecko..."):
                scanner = MoonshotScanner()
                gems = scanner.find_moonshots()
                
                if gems:
                    st.success(f"Found {len(gems)} potential moonshots!")
                    
                    st.markdown("---")
                    for gem in gems:
                        with st.container():
                            c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])
                            c1.markdown(f"### {gem['symbol']}")
                            c1.caption(gem['name'])
                            c2.metric("Price", f"${gem['price']:.6f}", f"{gem['change_24h']:+.2f}%")
                            c3.metric("Market Cap", f"${gem['mcap']/1e6:.1f}M")
                            
                            # Highlight high ratios
                            ratio_color = "green" if gem['ratio'] > 0.5 else "off"
                            c4.metric("Vol/MCap", f"{gem['ratio']:.2f}")
                            
                            # Add button
                            live_conf = load_live_config()
                            current = live_conf.get("symbols", [])
                            symbol = f"{gem['symbol']}/USD"
                            
                            if symbol in current:
                                c5.success("✅ Added")
                            else:
                                if c5.button("➕ Add", key=f"moon_{gem['symbol']}"):
                                    if add_symbol_to_configs(symbol):
                                        st.rerun()
                        st.divider()
                else:
                    st.warning("No gems found matching criteria. Market might be quiet.")

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_DB_PATH = "data/hot_crypto.db"
STRATEGIES = ["TREND_EMA", "MR_BB", "SQZ_BO", "GRID_LR", "SUPERTREND", "RSI_DIV", "MACD_X", "ICHI", "VWAP", "DUAL_T", "TURTLE", "TRIPLE_MOMO", "TRIPLE_V2", "VOL_HUNT"]
TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "All"]

# Strategy descriptions for UI
STRATEGY_DESCRIPTIONS = {
    "TREND_EMA": "📈 **Trend EMA** - Follows trend using 20/50 EMA crossovers. Best for strong directional markets.",
    "MR_BB": "🔄 **Mean Reversion BB** - Buys at lower Bollinger Band, sells at upper. Works in ranging markets.",
    "SQZ_BO": "💥 **Squeeze Breakout** - Enters after low volatility squeeze. Catches explosive moves.",
    "GRID_LR": "📊 **Grid Ladder** - DCA strategy with multiple entry levels. Good for accumulation.",
    "SUPERTREND": "🌊 **SuperTrend** - ATR-based trend indicator. Simple and effective for trending coins.",
    "RSI_DIV": "🔍 **RSI Divergence** - Detects price/RSI divergence for reversals. Contrarian strategy.",
    "MACD_X": "📉 **MACD Crossover** - Classic momentum strategy. MACD crossing signal line.",
    "ICHI": "☁️ **Ichimoku Cloud** - Japanese indicator with cloud, TK cross. All-in-one system.",
    "VWAP": "⚖️ **VWAP Bounce** - Mean reversion to volume-weighted price. Institutional favorite.",
    "DUAL_T": "🎯 **Dual Thrust** - Range breakout system. Best performer on 4h! (+7.14%)",
    "TURTLE": "🐢 **Turtle Trading** - 20-day breakout system. Classic trend-following. (+8.20% on 4h)",
    "TRIPLE_MOMO": "🚀 **Triple Momentum** - RSI+MACD+Stochastic confirmation with 1-3x leverage sizing.",
    "TRIPLE_V2": "⚡ **Triple Momentum V2** - Aggressive 2-of-3 confirmation with tighter stops.",
    "VOL_HUNT": "🎯 **Volatility Hunter** - Extreme BB (3 StdDev) + RSI exhaustion for volatile coins! +25%+ on AXS!",
}


# =============================================================================
# Database Utilities
# =============================================================================


@contextmanager
def get_conn(db_path: str):
    """Context manager for SQLite connection."""
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_table_columns(conn, table_name: str) -> list[str]:
    """Get list of columns for a table using PRAGMA."""
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]


def table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def load_runs(db_path: str) -> pd.DataFrame:
    """Load backtest runs with graceful column handling."""
    with get_conn(db_path) as conn:
        if not table_exists(conn, "backtest_runs"):
            return pd.DataFrame()
        
        available_cols = get_table_columns(conn, "backtest_runs")
        
        # Core columns we want
        desired_cols = [
            "id", "created_at", "exchange", "symbol", "timeframe",
            "strategy_name", "initial_cash", "final_equity",
            "max_drawdown_pct", "sharpe_ratio", "trades_count"
        ]
        
        # Filter to available columns
        select_cols = [c for c in desired_cols if c in available_cols]
        
        # Add computed return_pct if we have the necessary columns
        if "final_equity" in available_cols and "initial_cash" in available_cols:
            select_cols_str = ", ".join(select_cols)
            query = f"""
            SELECT {select_cols_str},
                   ROUND(100.0 * (final_equity - initial_cash) / initial_cash, 2) AS return_pct
            FROM backtest_runs
            ORDER BY id DESC
            """
        else:
            select_cols_str = ", ".join(select_cols)
            query = f"SELECT {select_cols_str} FROM backtest_runs ORDER BY id DESC"
        
        df = pd.read_sql_query(query, conn)
    
    return df


def load_trades_for_run(db_path: str, run_id: int) -> pd.DataFrame:
    """Load trades for a specific backtest run."""
    with get_conn(db_path) as conn:
        if not table_exists(conn, "backtest_trades"):
            return pd.DataFrame()
        
        available_cols = get_table_columns(conn, "backtest_trades")
        
        desired_cols = [
            "id", "backtest_run_id", "symbol", "strategy_name", "side",
            "size", "entry_ts", "exit_ts", "entry_price", "exit_price",
            "pnl", "pnl_pct"
        ]
        
        select_cols = [c for c in desired_cols if c in available_cols]
        select_cols_str = ", ".join(select_cols)
        
        query = f"""
        SELECT {select_cols_str}
        FROM backtest_trades
        WHERE backtest_run_id = ?
        ORDER BY id
        """
        df = pd.read_sql_query(query, conn, params=(run_id,))
    
    return df


def build_equity_curve(trades: pd.DataFrame, initial_cash: float) -> pd.DataFrame:
    """Build equity curve from trade PnL, ordered by exit_ts."""
    if trades.empty or "pnl" not in trades.columns:
        return pd.DataFrame()
    
    trades = trades.copy()
    if "exit_ts" in trades.columns:
        trades["exit_ts"] = pd.to_datetime(trades["exit_ts"])
        trades = trades.sort_values("exit_ts")
    
    trades["cum_pnl"] = trades["pnl"].cumsum()
    trades["equity"] = initial_cash + trades["cum_pnl"]
    
    # Add starting point
    start_row = pd.DataFrame([{
        "exit_ts": trades["exit_ts"].iloc[0] if "exit_ts" in trades.columns else datetime.now(),
        "equity": initial_cash
    }])
    
    curve = pd.concat([start_row, trades[["exit_ts", "equity"]]], ignore_index=True)
    curve = curve.rename(columns={"exit_ts": "Time", "equity": "Equity"})
    
    return curve


# =============================================================================
# Streamlit UI
# =============================================================================


def main():
    st.set_page_config(
        page_title="HOT-Crypto Dashboard",
        page_icon="🔥",
        layout="wide",
    )

    st.title("🔥 HOT-Crypto Trader – Control Room")

    # -------------------------------------------------------------------------
    # Sidebar
    # -------------------------------------------------------------------------
    st.sidebar.header("⚙️ Settings")
    
    db_path = st.sidebar.text_input("Database Path", value=DEFAULT_DB_PATH)
    
    # Validate database
    if not os.path.exists(db_path):
        st.error(f"❌ Database file not found: `{db_path}`")
        st.info("Run `python -m db.init_db` to create the database, then run some backtests with `--persist`.")
        st.stop()
    
    # Reload button
    if st.sidebar.button("🔄 Reload Data"):
        st.rerun()
    
    # Load runs
    try:
        runs_df = load_runs(db_path)
    except Exception as e:
        st.error(f"❌ Failed to load data: {e}")
        st.stop()
    
    if runs_df.empty:
        st.warning("⚠️ No backtest runs found in the database.")
        st.info("Run some backtests with `--persist` flag:\n\n```\npython scripts/run_backtest.py --all --use-sql --persist\n```")
        
        # Show the run backtest section anyway
        show_run_backtest_section(db_path)
        st.stop()
    
    # -------------------------------------------------------------------------
    # Sidebar Filters
    # -------------------------------------------------------------------------
    st.sidebar.header("🔍 Filters")
    
    # Symbol filter
    symbols = sorted(runs_df["symbol"].unique().tolist()) if "symbol" in runs_df.columns else []
    selected_symbols = st.sidebar.multiselect("Symbol", symbols, default=symbols)
    
    # Strategy filter
    strategies = sorted(runs_df["strategy_name"].unique().tolist()) if "strategy_name" in runs_df.columns else []
    selected_strategies = st.sidebar.multiselect("Strategy", strategies, default=strategies)
    
    # Timeframe filter
    if "timeframe" in runs_df.columns:
        timeframes = sorted(runs_df["timeframe"].dropna().unique().tolist())
        selected_timeframes = st.sidebar.multiselect("Timeframe", timeframes, default=timeframes)
    else:
        selected_timeframes = None
    
    # Apply filters
    filtered_df = runs_df.copy()
    if "symbol" in filtered_df.columns and selected_symbols:
        filtered_df = filtered_df[filtered_df["symbol"].isin(selected_symbols)]
    if "strategy_name" in filtered_df.columns and selected_strategies:
        filtered_df = filtered_df[filtered_df["strategy_name"].isin(selected_strategies)]
    if selected_timeframes and "timeframe" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["timeframe"].isin(selected_timeframes)]
    
    # Sort by return
    if "return_pct" in filtered_df.columns:
        filtered_df = filtered_df.sort_values("return_pct", ascending=False)
    
    # -------------------------------------------------------------------------
    # Market Scanner
    # -------------------------------------------------------------------------
    show_scanner_section()
    
    st.markdown("---")

    # -------------------------------------------------------------------------
    # Main Content: Backtest Runs Table
    # -------------------------------------------------------------------------
    st.header("📊 Backtest Runs")
    
    # Display columns
    display_cols = [c for c in [
        "id", "symbol", "strategy_name", "timeframe", "initial_cash",
        "final_equity", "return_pct", "max_drawdown_pct", "sharpe_ratio", "trades_count"
    ] if c in filtered_df.columns]
    
    st.dataframe(
        filtered_df[display_cols],
        use_container_width=True,
        height=300,
    )
    
    # -------------------------------------------------------------------------
    # Run Selection
    # -------------------------------------------------------------------------
    st.header("🔬 Run Details")
    
    if filtered_df.empty:
        st.info("No runs match the current filters.")
        show_run_backtest_section(db_path)
        st.stop()
    
    # Build selection labels
    filtered_df = filtered_df.copy()
    filtered_df["label"] = (
        "ID " + filtered_df["id"].astype(str) + " – " +
        filtered_df["symbol"].fillna("") + " – " +
        filtered_df["strategy_name"].fillna("") + " – " +
        filtered_df.get("timeframe", pd.Series([""] * len(filtered_df))).fillna("")
    )
    
    selected_label = st.selectbox(
        "Select a run to inspect",
        options=filtered_df["label"].tolist(),
    )
    
    selected_row = filtered_df[filtered_df["label"] == selected_label].iloc[0]
    run_id = int(selected_row["id"])
    initial_cash = float(selected_row.get("initial_cash", 10000))
    final_equity = float(selected_row.get("final_equity", initial_cash))
    return_pct = float(selected_row.get("return_pct", 0))
    max_dd = float(selected_row.get("max_drawdown_pct", 0))
    sharpe = float(selected_row.get("sharpe_ratio", 0)) if pd.notna(selected_row.get("sharpe_ratio")) else 0
    trades_count = int(selected_row.get("trades_count", 0))
    
    # -------------------------------------------------------------------------
    # Metrics Cards
    # -------------------------------------------------------------------------
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("💵 Initial Cash", f"${initial_cash:,.2f}")
    col2.metric("💰 Final Equity", f"${final_equity:,.2f}")
    col3.metric("📈 Return", f"{return_pct:.2f}%", delta=f"{return_pct:.2f}%")
    col4.metric("📉 Max Drawdown", f"{max_dd:.2f}%")
    col5.metric("📊 Sharpe Ratio", f"{sharpe:.3f}")
    col6.metric("🔄 Trades", trades_count)
    
    # -------------------------------------------------------------------------
    # Trades Table
    # -------------------------------------------------------------------------
    st.subheader("📋 Trades")
    
    trades_df = load_trades_for_run(db_path, run_id)
    
    if trades_df.empty:
        st.info("No trades recorded for this run.")
    else:
        st.dataframe(trades_df, use_container_width=True, height=250)
        
        # ---------------------------------------------------------------------
        # Charts
        # ---------------------------------------------------------------------
        chart_col1, chart_col2 = st.columns(2)
        
        # Equity Curve
        with chart_col1:
            st.subheader("💹 Equity Curve")
            curve_df = build_equity_curve(trades_df, initial_cash)
            
            if not curve_df.empty:
                fig = px.line(
                    curve_df, x="Time", y="Equity",
                    title="",
                    template="plotly_dark",
                )
                fig.update_layout(
                    xaxis_title="",
                    yaxis_title="Equity ($)",
                    showlegend=False,
                    height=350,
                )
                fig.update_traces(line_color="#00FF88", line_width=2)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Unable to build equity curve (missing data).")
        
        # PnL Distribution
        with chart_col2:
            st.subheader("📊 Trade PnL Distribution")
            
            if "pnl_pct" in trades_df.columns and trades_df["pnl_pct"].notna().any():
                fig = px.histogram(
                    trades_df, x="pnl_pct",
                    title="",
                    template="plotly_dark",
                    color_discrete_sequence=["#00BFFF"],
                    nbins=20,
                )
                fig.update_layout(
                    xaxis_title="Trade Return (%)",
                    yaxis_title="Count",
                    showlegend=False,
                    height=350,
                )
                # Add zero line
                fig.add_vline(x=0, line_dash="dash", line_color="red", line_width=1)
                st.plotly_chart(fig, use_container_width=True)
            elif "pnl" in trades_df.columns and trades_df["pnl"].notna().any():
                fig = px.histogram(
                    trades_df, x="pnl",
                    title="",
                    template="plotly_dark",
                    color_discrete_sequence=["#00BFFF"],
                    nbins=20,
                )
                fig.update_layout(
                    xaxis_title="Trade PnL ($)",
                    yaxis_title="Count",
                    showlegend=False,
                    height=350,
                )
                fig.add_vline(x=0, line_dash="dash", line_color="red", line_width=1)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No PnL data available for histogram.")
    
    # -------------------------------------------------------------------------
    # Run Backtest Section
    # -------------------------------------------------------------------------
    show_run_backtest_section(db_path)


def show_run_backtest_section(db_path: str):
    """Section to run new backtests from the UI."""
    st.header("🚀 Run New Backtest")
    
    # Get available coins from database
    available_coins = []
    try:
        with get_conn(db_path) as conn:
            cursor = conn.execute("SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol")
            available_coins = [row[0] for row in cursor.fetchall()]
    except Exception:
        available_coins = ["BTC/USD", "ETH/USD"]  # Fallback
    
    with st.expander("Configure and Run Backtest", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            # Coin multiselect
            default_coins = ["BTC/USD", "ETH/USD"] if "BTC/USD" in available_coins else available_coins[:2]
            selected_coins = st.multiselect(
                "Select Coins",
                options=available_coins,
                default=default_coins,
                help="Select one or more coins to backtest"
            )
            symbols_input = ",".join(selected_coins) if selected_coins else "BTC/USD"
            
            timeframe = st.selectbox("Timeframe", TIMEFRAMES, index=TIMEFRAMES.index("4h"))
            mode = st.radio("Mode", ["All Strategies", "Single Strategy"])
            
            if mode == "Single Strategy":
                strategy = st.selectbox("Strategy", STRATEGIES)
                # Show description of selected strategy
                st.markdown(STRATEGY_DESCRIPTIONS.get(strategy, ""))
            else:
                strategy = None
                # Show all strategy descriptions in an expander
                with st.expander("📖 Strategy Guide", expanded=False):
                    for strat, desc in STRATEGY_DESCRIPTIONS.items():
                        st.markdown(desc)
        
        with col2:
            cash = st.number_input("Initial Cash ($)", value=10000.0, min_value=100.0)
            limit = st.number_input("Candles Limit", value=500, min_value=50, max_value=5000)
            use_sql = st.checkbox("Use SQL Data", value=True)
        
        if st.button("▶️ Run Backtest", type="primary"):
            # All available timeframes that have data
            ALL_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]
            
            if timeframe == "All":
                target_timeframes = ALL_TIMEFRAMES
            else:
                target_timeframes = [timeframe]
            
            # Track results for best performer summary
            all_results = []
            
            progress_bar = st.progress(0)
            total_runs = len(target_timeframes)
            
            for idx, tf in enumerate(target_timeframes):
                st.info(f"Running backtest for timeframe: {tf}... ({idx+1}/{total_runs})")
                progress_bar.progress((idx + 1) / total_runs)
                
                # Build command
                if mode == "All Strategies":
                    cmd = [
                        "python", "scripts/run_backtest.py",
                        "--all",
                        "--symbols", symbols_input,
                        "--timeframe", tf,
                        "--cash", str(cash),
                        "--limit", str(limit),
                        "--persist",
                    ]
                else:
                    # Single strategy - use first symbol
                    first_symbol = symbols_input.split(",")[0].strip()
                    cmd = [
                        "python", "scripts/run_backtest.py",
                        "--symbol", first_symbol,
                        "--strategy", strategy,
                        "--timeframe", tf,
                        "--cash", str(cash),
                        "--limit", str(limit),
                        "--persist",
                    ]
                
                if use_sql:
                    cmd.append("--use-sql")
                
                # Run command
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=180,  # Increased timeout for more strategies
                    )
                    
                    if result.returncode == 0:
                        st.success(f"✅ {tf}: Completed!")
                        
                        # Parse output for best performer
                        output = result.stdout
                        if "Best performer:" in output:
                            for line in output.split("\n"):
                                if "Best performer:" in line:
                                    best_info = line.strip()
                                if "Return:" in line and "%" in line:
                                    ret_line = line.strip()
                                    try:
                                        ret_pct = float(ret_line.split(":")[1].replace("%", "").strip())
                                        all_results.append({
                                            "timeframe": tf,
                                            "info": best_info,
                                            "return": ret_pct
                                        })
                                    except:
                                        pass
                        
                        with st.expander(f"Output ({tf})"):
                            st.code(output, language="text")
                    else:
                        st.error(f"❌ {tf}: Failed (no data?)")
                        with st.expander(f"Error ({tf})"):
                            st.code(result.stderr, language="text")
                        
                except subprocess.TimeoutExpired:
                    st.error(f"⏱️ {tf}: Timed out (>180s)")
                except Exception as e:
                    st.error(f"❌ {tf}: Error: {e}")
            
            progress_bar.empty()
            st.success("🏁 All requested backtests completed!")
            
            # Show best performer summary
            if all_results:
                st.markdown("---")
                st.subheader("🏆 Best Performers by Timeframe")
                
                # Sort by return
                all_results.sort(key=lambda x: x["return"], reverse=True)
                
                # Create summary table
                summary_data = []
                for r in all_results:
                    summary_data.append({
                        "Timeframe": r["timeframe"],
                        "Best Strategy": r["info"].replace("🏆 Best performer: ", ""),
                        "Return": f"{r['return']:+.2f}%"
                    })
                
                st.dataframe(pd.DataFrame(summary_data), use_container_width=True)
                
                # Highlight overall best
                if all_results:
                    best = all_results[0]
                    st.success(f"🥇 **Overall Best**: {best['info']} on **{best['timeframe']}** with **{best['return']:+.2f}%** return!")
            
            st.button("🔄 Reload to see new results", on_click=lambda: st.rerun())



if __name__ == "__main__":
    main()
