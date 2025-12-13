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

# =============================================================================
# Configuration
# =============================================================================

DEFAULT_DB_PATH = "data/hot_crypto.db"
STRATEGIES = ["TREND_EMA", "MR_BB", "SQZ_BO", "GRID_LR"]
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d", "All"]


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
    
    with st.expander("Configure and Run Backtest", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            symbols_input = st.text_input("Symbols (comma-separated)", value="BTC/USDT,ETH/USDT")
            timeframe = st.selectbox("Timeframe", TIMEFRAMES, index=TIMEFRAMES.index("4h"))
            mode = st.radio("Mode", ["All Strategies", "Single Strategy"])
            
            if mode == "Single Strategy":
                strategy = st.selectbox("Strategy", STRATEGIES)
            else:
                strategy = None
        
        with col2:
            cash = st.number_input("Initial Cash ($)", value=10000.0, min_value=100.0)
            limit = st.number_input("Candles Limit", value=500, min_value=50, max_value=5000)
            use_sql = st.checkbox("Use SQL Data", value=True)
        
        if st.button("▶️ Run Backtest", type="primary"):
            if timeframe == "All":
                target_timeframes = ["1h", "4h", "1d"]
            else:
                target_timeframes = [timeframe]
            
            for tf in target_timeframes:
                st.info(f"Running backtest for timeframe: {tf}...")
                
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
                        timeout=120,
                    )
                    
                    if result.returncode == 0:
                        st.success(f"✅ {tf}: Completed successfully!")
                        with st.expander(f"Output ({tf})"):
                            st.code(result.stdout, language="text")
                    else:
                        st.error(f"❌ {tf}: Failed!")
                        st.code(result.stderr, language="text")
                        
                except subprocess.TimeoutExpired:
                    st.error(f"⏱️ {tf}: Timed out (>120s)")
                except Exception as e:
                    st.error(f"❌ {tf}: Error: {e}")
            
            st.success("🏁 All requested backtests completed.")
            st.button("🔄 Reload to see new results", on_click=lambda: st.rerun())



if __name__ == "__main__":
    main()
