"""
Simple Streamlit dashboard for HOT-Crypto-Trader.

- Reads from data/hot_crypto.db (backtest_runs, backtest_trades, ohlcv)
- Shows best runs by return
- Lets you inspect a specific run's trades and a basic equity curve

Usage:
    streamlit run scripts/dashboard.py
"""

import os
import sqlite3
from contextlib import contextmanager

import pandas as pd
import streamlit as st


# ---------- CONFIG ----------

DEFAULT_DB_PATH = "data/hot_crypto.db"


@contextmanager
def get_conn(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def load_runs(db_path: str) -> pd.DataFrame:
    with get_conn(db_path) as conn:
        # We only rely on columns that almost certainly exist:
        # id, symbol, strategy_name, initial_cash, final_equity
        query = """
        SELECT
            id,
            symbol,
            strategy_name,
            timeframe,
            initial_cash,
            final_equity,
            ROUND(100.0 * (final_equity - initial_cash) / initial_cash, 2) AS return_pct
        FROM backtest_runs
        ORDER BY id DESC
        """
        df = pd.read_sql_query(query, conn)
    return df


def load_trades_for_run(db_path: str, run_id: int) -> pd.DataFrame:
    with get_conn(db_path) as conn:
        query = """
        SELECT
            id,
            backtest_run_id,
            symbol,
            strategy_name,
            side,
            size,
            entry_ts,
            exit_ts,
            entry_price,
            exit_price,
            pnl,
            pnl_pct
        FROM backtest_trades
        WHERE backtest_run_id = ?
        ORDER BY id
        """
        df = pd.read_sql_query(query, conn, params=(run_id,))
    return df


def build_equity_curve(trades: pd.DataFrame, initial_cash: float) -> pd.DataFrame:
    """Build a basic equity curve from trade PnL, ordered by exit_ts."""
    if trades.empty or "pnl" not in trades.columns:
        return pd.DataFrame()

    # Make sure exit_ts is datetime
    trades = trades.copy()
    trades["exit_ts"] = pd.to_datetime(trades["exit_ts"])
    trades = trades.sort_values("exit_ts")

    trades["cum_pnl"] = trades["pnl"].cumsum()
    trades["equity"] = initial_cash + trades["cum_pnl"]

    curve = trades[["exit_ts", "equity"]].rename(
        columns={"exit_ts": "timestamp", "equity": "equity"}
    )
    curve.set_index("timestamp", inplace=True)
    return curve


def main():
    st.set_page_config(
        page_title="HOT-Crypto Dashboard",
        layout="wide",
    )

    st.title("🔥 HOT-Crypto Trader – Backtest Dashboard")

    # ----- Sidebar: DB path & filters -----

    st.sidebar.header("Database")
    db_path = st.sidebar.text_input("SQLite DB path", value=DEFAULT_DB_PATH)

    if not os.path.exists(db_path):
        st.error(f"Database file not found at: {db_path}")
        st.stop()

    # Load runs
    try:
        runs_df = load_runs(db_path)
    except Exception as e:
        st.error(f"Failed to load backtest_runs from DB: {e}")
        st.stop()

    if runs_df.empty:
        st.warning("No backtest_runs found in the database yet.")
        st.stop()

    st.sidebar.subheader("Filters")

    symbols = sorted(runs_df["symbol"].unique().tolist())
    strategies = sorted(runs_df["strategy_name"].unique().tolist())

    symbol_filter = st.sidebar.multiselect("Symbols", symbols, default=symbols)
    strategy_filter = st.sidebar.multiselect("Strategies", strategies, default=strategies)

    filtered_runs = runs_df[
        runs_df["symbol"].isin(symbol_filter)
        & runs_df["strategy_name"].isin(strategy_filter)
    ].copy()

    # ----- Top runs summary -----

    st.subheader("Top Backtest Runs")

    # Sort by return_pct desc, then final_equity desc
    filtered_runs = filtered_runs.sort_values(
        by=["return_pct", "final_equity"], ascending=[False, False]
    )

    st.dataframe(
        filtered_runs,
        use_container_width=True,
    )

    # ----- Run selection -----

    st.subheader("Inspect a Specific Run")

    # Build a label for selection, e.g. "ID 12 – BTC/USDT – SQZ_BO – 4h"
    filtered_runs["label"] = (
        "ID "
        + filtered_runs["id"].astype(str)
        + " – "
        + filtered_runs["symbol"]
        + " – "
        + filtered_runs["strategy_name"]
        + " – "
        + filtered_runs["timeframe"].fillna("")
    )

    selected_label = st.selectbox(
        "Choose a run to inspect",
        options=filtered_runs["label"].tolist(),
    )

    selected_row = filtered_runs[filtered_runs["label"] == selected_label].iloc[0]
    run_id = int(selected_row["id"])
    initial_cash = float(selected_row["initial_cash"])
    final_equity = float(selected_row["final_equity"])
    return_pct = float(selected_row["return_pct"])

    cols = st.columns(3)
    cols[0].metric("Initial Cash", f"${initial_cash:,.2f}")
    cols[1].metric("Final Equity", f"${final_equity:,.2f}")
    cols[2].metric("Return (%)", f"{return_pct:.2f}%")

    # ----- Trades for that run -----

    st.markdown("### Trades for Selected Run")

    trades_df = load_trades_for_run(db_path, run_id)

    if trades_df.empty:
        st.info("No trades recorded for this run.")
    else:
        st.dataframe(trades_df, use_container_width=True, height=300)

        # ----- Equity curve -----
        st.markdown("### Equity Curve (from trade PnL)")

        curve_df = build_equity_curve(trades_df, initial_cash)
        if curve_df.empty:
            st.info("Could not build equity curve (missing PnL or timestamps).")
        else:
            st.line_chart(curve_df)


if __name__ == "__main__":
    main()
