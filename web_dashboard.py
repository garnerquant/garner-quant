import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

from dashboard.data_loader import load_csv
from execution.trade_audit import build_trade_audit_trail
from ui.responsive import (
    apply_responsive_styles,
    responsive_columns,
    responsive_table,
)
from ui.runtime_status import load_runtime_status, runtime_status_updated_at

try:
    from ui.auto_refresh import (
        fragment_runner as _shared_fragment_runner,
        live_mode_controls as _shared_live_mode_controls,
    )
except ImportError:
    _shared_fragment_runner = None
    _shared_live_mode_controls = None


def fragment_runner():
    if _shared_fragment_runner is not None:
        return _shared_fragment_runner()
    if hasattr(st, "fragment"):
        return st.fragment
    if hasattr(st, "experimental_fragment"):
        return st.experimental_fragment
    return None


def live_mode_controls(interval_seconds=60, key="dashboard_live_mode", default_enabled=False):
    if _shared_live_mode_controls is not None:
        return _shared_live_mode_controls(
            interval_seconds=interval_seconds,
            key=key,
            default_enabled=default_enabled,
        )

    enabled_key = f"{key}_enabled"
    control_key = f"{enabled_key}_control"
    if enabled_key not in st.session_state:
        st.session_state[enabled_key] = bool(default_enabled)
    if control_key not in st.session_state:
        st.session_state[control_key] = bool(st.session_state[enabled_key])

    enabled = st.checkbox(
        "Live mode",
        key=control_key,
        help="Updates key cards without forcing full-page navigation where possible.",
    )
    st.caption(
        "Updates key cards without forcing full-page navigation where possible."
    )

    fragments_available = fragment_runner() is not None
    if enabled and not fragments_available:
        st.caption("Live mode unavailable in this Streamlit version.")
        enabled = False

    st.session_state[enabled_key] = bool(enabled)
    return {
        "enabled": bool(enabled),
        "interval_seconds": int(interval_seconds),
        "fragments_available": fragments_available,
        "method": "streamlit_fragment" if enabled and fragments_available else "manual",
    }


def inject_mobile_css():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 3rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 1280px;
        }

        .status-card {
            background: linear-gradient(135deg, #114f2f, #0d3823);
            border: 1px solid #2f9d5c;
            border-radius: 18px;
            padding: 16px 22px;
            margin-bottom: 24px;
            min-height: 70px;
        }

        .metric-card {
            background:#111827;
            border:1px solid #30363d;
            border-radius:18px;
            padding:16px;
            margin-bottom:16px;
            min-height:90px;
            box-shadow:0 4px 18px rgba(0,0,0,.25);
        }

        .metric-label {
            color:#9ca3af;
            font-size:14px;
            margin-bottom:6px;
        }

        .metric-value {
            color:white;
            font-size:24px;
            font-weight:700;
            line-height:1.2;
        }

        .metric-value-green {
            color:#68ff8b;
            font-size:24px;
            font-weight:700;
            line-height:1.2;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_card(last_updated):
    st.markdown(
        f"""
        <div class="status-card">
            <div style="font-size:17px;font-weight:700;color:white;">
                🟢 Live Data Connected
            </div>
            <div style="margin-top:6px;font-size:15px;color:#b7f7c8;">
                Updated: {last_updated}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label, value, green=False):
    value_class = "metric-value-green" if green else "metric-value"

    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="{value_class}">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_last_updated():
    now = pd.Timestamp.now(tz="Europe/London")
    timezone_label = now.tzname()
    return f"Today \u2022 {now:%H:%M} {timezone_label}"

    if not value:
        return "Unknown"

    try:
        dt = pd.to_datetime(value, utc=True).tz_convert("Europe/London")
        today = pd.Timestamp.now(tz="Europe/London")

        if dt.date() == today.date():
            return dt.strftime("Today • %H:%M BST")

        return dt.strftime("%d %b %Y • %H:%M BST")

    except Exception:
        return "Unknown"


def age_freshness_from_timestamp(value):
    if not value:
        return None

    try:
        updated_at = pd.to_datetime(value, utc=True)
    except Exception:
        return None

    age_seconds = max(
        0,
        (pd.Timestamp.now(tz="UTC") - updated_at).total_seconds(),
    )
    if age_seconds <= 60:
        return "Live"
    if age_seconds <= 300:
        return "Recent"
    if age_seconds <= 900:
        return "Slightly stale"
    return "Stale"


def latest_trade_label():
    journal = load_csv("trade_journal_v3.csv")
    if journal.empty:
        return "None today"

    latest = journal.iloc[-1]
    action = latest.get("action", "TRADE")
    ticker = latest.get("ticker", "UNKNOWN")
    time_value = latest.get("time", "")
    if pd.isna(time_value):
        time_value = ""
    return f"{action} {ticker} {time_value}".strip()


def holdings_count_label():
    current_holdings = load_csv("holdings_report.csv")
    if current_holdings.empty:
        return "0"

    ticker_column = None
    for column in current_holdings.columns:
        if column.lower() == "ticker":
            ticker_column = column
            break

    if ticker_column is None:
        return str(len(current_holdings))

    tickers = current_holdings[ticker_column].astype(str).str.upper()
    return str(int((tickers != "CASH").sum()))


def runtime_status_label():
    status = load_runtime_status()
    return str(status.get("status") or "Unknown").title()


def runtime_freshness_label():
    status = load_runtime_status()
    if status.get("_runtime_source") == "supabase":
        freshness = age_freshness_from_timestamp(status.get("updated_at"))
        if freshness:
            return freshness

    updated_at = runtime_status_updated_at(status)
    if updated_at:
        freshness = age_freshness_from_timestamp(updated_at)
        if freshness:
            return freshness

    return "Missing"


def render_live_operational_cards():
    status_card(format_last_updated())

    cols = responsive_columns(4)
    with cols[0]:
        metric_card(
            "Data Freshness",
            runtime_freshness_label(),
            True,
        )
    with cols[1]:
        metric_card("Runtime Status", runtime_status_label(), True)
    with cols[2]:
        metric_card("Latest Paper Trade", latest_trade_label(), True)
    with cols[3]:
        metric_card("Current Holdings", holdings_count_label(), True)


def render_live_panel(live_mode):
    # Full-page auto-refresh is deliberately avoided because Streamlit reruns can
    # return the browser to the top of the page. Fragments refresh this small
    # operational panel every 60 seconds without rebuilding the whole dashboard.
    fragment = fragment_runner()
    if live_mode["enabled"] and fragment is not None:
        live_fragment = fragment(run_every="60s")(render_live_operational_cards)
        live_fragment()
        return

    render_live_operational_cards()


st.set_page_config(
    page_title="Garner Quant",
    page_icon="📊",
    layout="wide",
)

inject_mobile_css()
apply_responsive_styles()

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

try:
    supabase = (
        create_client(SUPABASE_URL, SUPABASE_KEY)
        if SUPABASE_URL and SUPABASE_KEY
        else None
    )
except Exception:
    supabase = None


def load_supabase_table(table_name, fallback_csv=None, order_col=None):
    try:
        if supabase is None:
            raise RuntimeError("Supabase is not configured.")

        query = supabase.table(table_name).select("*")

        if order_col:
            query = query.order(order_col)

        response = query.execute()
        return pd.DataFrame(response.data)

    except Exception:
        if fallback_csv:
            return load_csv(fallback_csv)

        return pd.DataFrame()


def load_trade_audit(journal):
    if journal is not None and not journal.empty:
        return build_trade_audit_trail(journal)

    return pd.DataFrame()


broker = load_supabase_table("broker_account", "broker_account.csv")
paper_30 = load_supabase_table(
    "paper_30_day_tracker",
    "paper_30_day_tracker.csv",
    "date",
)
holdings = load_supabase_table("holdings", "holdings_report.csv")
history = load_supabase_table("holdings_history", None, "date")
signals = load_supabase_table("signals", "signal_report_v2.csv")
trades = load_supabase_table("trade_journal", "trade_journal_v3.csv")

portfolio = load_csv("portfolio_v2.csv")
analytics = load_csv("trade_analytics_v3.csv")
snapshots = load_csv("trade_snapshots.csv")

if broker.empty:
    st.error(
        "broker_account.csv not found. Run main_v2.py first, then push the updated CSV files."
    )
    st.stop()

broker_row = broker.iloc[0]

st.title("📈 Garner Quant")
st.caption("Personal investment research and paper trading dashboard.")
if st.button("Refresh now", type="primary"):
    st.rerun()
live_mode = live_mode_controls(
    interval_seconds=60,
    key="main_dashboard_live_mode",
    default_enabled=False,
)
if live_mode["enabled"]:
    st.caption("Live mode: ON | Key cards update every 60s")
else:
    st.caption("Auto-refresh paused to preserve scroll position")
render_live_panel(live_mode)

page = "Home"


if page == "Home":
    st.subheader("🚀 30 Day Paper Trading Challenge")

    if paper_30.empty:
        st.info("30 day tracker has not started yet.")
        start_balance = 0
        current_balance = 0
        total_return = 0

    else:
        paper_row = paper_30.iloc[-1]

        start_balance = paper_30["portfolio_value"].iloc[0]
        current_balance = paper_row["portfolio_value"]
        total_return = (
            (current_balance / start_balance) - 1
            if start_balance > 0
            else 0
        )

        paper_30["date"] = pd.to_datetime(
            paper_30["date"],
            errors="coerce",
        )

        start_date = paper_30["date"].min().date()
        today = pd.Timestamp.now().date()
        days_tracked = (today - start_date).days + 1

        col1, col2 = responsive_columns(2)

        with col1:
            metric_card("Day", f"{days_tracked}/30", True)
            metric_card("Return", f"{total_return:.2%}", True)
            metric_card(
                "Realised PnL",
                f"£{paper_row['realised_pnl']:,.2f}",
                True,
            )

        with col2:
            metric_card("Starting Balance", f"£{start_balance:,.2f}")
            metric_card("Current Balance", f"£{current_balance:,.2f}")
            metric_card(
                "Unrealised PnL",
                f"£{paper_row['unrealised_pnl']:,.2f}",
                True,
            )

        st.subheader("📈 30 Day Equity Curve")

        chart_data = paper_30.copy()
        chart_data["date"] = pd.to_datetime(chart_data["date"])
        chart_data = chart_data.sort_values("date")
        chart_data = chart_data.set_index("date")

        st.line_chart(chart_data["portfolio_value"])

    st.divider()

    st.subheader("📊 Strategy Analytics")

    cash_value = broker_row["cash"]
    portfolio_value = broker_row["portfolio_value"]
    cash_percent = cash_value / portfolio_value if portfolio_value > 0 else 0

    col1, col2 = responsive_columns(2)

    with col1:
        metric_card("Total Return", f"{total_return:.2%}", True)
        metric_card("Open Holdings", len(holdings))

    with col2:
        metric_card("Cash %", f"{cash_percent:.2%}", True)
        metric_card(
            "Unrealised PnL",
            f"£{broker_row['unrealised_pnl']:,.2f}",
            True,
        )

    st.subheader("📊 Benchmark")

    if not paper_30.empty:
        latest_tracker_row = paper_30.sort_values("date").iloc[-1]
        benchmark_return = float(
            latest_tracker_row.get("benchmark_return", 0)
        )

        if benchmark_return > 0.10:
            benchmark_return = benchmark_return / 100

        alpha = total_return - benchmark_return

        col1, col2, col3 = responsive_columns(3)

        with col1:
            metric_card("Garner Quant", f"{total_return:.2%}", True)

        with col2:
            metric_card("SPY", f"{benchmark_return:.2%}")

        with col3:
            metric_card("Alpha", f"{alpha:.2%}", True)

    else:
        st.info("No benchmark data available.")

    st.subheader("Portfolio")

    col1, col2 = responsive_columns(2)

    with col1:
        metric_card(
            "Portfolio Value",
            f"£{broker_row['portfolio_value']:,.2f}",
        )
        metric_card(
            "Buying Power",
            f"£{broker_row['buying_power']:,.2f}",
        )

    with col2:
        metric_card("Cash", f"£{broker_row['cash']:,.2f}")
        metric_card(
            "Unrealised PnL",
            f"£{broker_row['unrealised_pnl']:,.2f}",
            True,
        )

    st.divider()

    if not paper_30.empty and len(paper_30) > 1:
        paper_30["daily_return"] = paper_30["portfolio_value"].pct_change()

        best_day = paper_30["daily_return"].max()
        worst_day = paper_30["daily_return"].min()

        rolling_peak = paper_30["portfolio_value"].cummax()
        drawdown = (paper_30["portfolio_value"] / rolling_peak) - 1
        max_drawdown = drawdown.min()

        col1, col2, col3 = responsive_columns(3)

        with col1:
            metric_card("Best Day", f"{best_day:.2%}", True)

        with col2:
            metric_card("Worst Day", f"{worst_day:.2%}")

        with col3:
            metric_card("Max Drawdown", f"{max_drawdown:.2%}")

    else:
        st.info("Need at least 2 days of data for daily return analytics.")

    st.subheader("Day-over-Day Attribution")

    if history.empty:
        st.info("No holdings history available yet.")

    else:
        history["date"] = pd.to_datetime(history["date"])
        dates = sorted(history["date"].dt.date.unique())

        if len(dates) < 2:
            st.info("Need at least 2 days of holdings history for attribution.")

        else:
            yesterday = dates[-2]
            today = dates[-1]

            yesterday_holdings = history[
                history["date"].dt.date == yesterday
            ][["ticker", "market_value"]].rename(
                columns={"market_value": "Yesterday Value"}
            )

            today_holdings = history[
                history["date"].dt.date == today
            ][["ticker", "market_value"]].rename(
                columns={"market_value": "Today Value"}
            )

            attribution = today_holdings.merge(
                yesterday_holdings,
                on="ticker",
                how="outer",
            ).fillna(0)

            attribution["Daily PnL"] = (
                attribution["Today Value"]
                - attribution["Yesterday Value"]
            )

            total_yesterday = attribution["Yesterday Value"].sum()

            if total_yesterday > 0:
                attribution["Contribution %"] = (
                    attribution["Daily PnL"]
                    / total_yesterday
                    * 100
                )
            else:
                attribution["Contribution %"] = 0

            attribution = attribution.sort_values(
                "Daily PnL",
                ascending=False,
            )

            st.caption(f"Comparing {yesterday} → {today}")

            responsive_table(
                attribution.style.format(
                    {
                        "Yesterday Value": "£{:,.2f}",
                        "Today Value": "£{:,.2f}",
                        "Daily PnL": "£{:,.2f}",
                        "Contribution %": "{:.2f}%",
                    }
                ),
                hide_index=True,
            )

    st.subheader("Drawdown")

    if portfolio.empty or "drawdown" not in portfolio.columns:
        st.info("No drawdown data available.")
    else:
        st.line_chart(portfolio["drawdown"])

    st.divider()

    st.subheader("Current Holdings")

    if holdings.empty:
        st.info("No open holdings.")

    else:
        holdings = holdings.copy()

        holdings.columns = [
            col.lower().replace(" ", "_")
            for col in holdings.columns
        ]

        portfolio_value = broker_row["portfolio_value"]

        holdings["portfolio_weight"] = (
            holdings["market_value"] / portfolio_value * 100
        ).round(2)

        cash_row = pd.DataFrame(
            [
                {
                    "ticker": "CASH",
                    "shares": 0,
                    "entry_price": 0,
                    "current_price": 0,
                    "market_value": broker_row["cash"],
                    "portfolio_weight": round(
                        broker_row["cash"]
                        / broker_row["portfolio_value"]
                        * 100,
                        2,
                    ),
                    "unrealised_pnl": 0,
                }
            ]
        )

        holdings = pd.concat(
            [holdings, cash_row],
            ignore_index=True,
        )

        holdings = holdings.sort_values(
            "market_value",
            ascending=False,
        )

        display_holdings = holdings[
            [
                "ticker",
                "shares",
                "entry_price",
                "current_price",
                "market_value",
                "portfolio_weight",
                "unrealised_pnl",
            ]
        ].rename(
            columns={
                "ticker": "Ticker",
                "shares": "Shares",
                "entry_price": "Entry Price",
                "current_price": "Current Price",
                "market_value": "Market Value",
                "portfolio_weight": "Weight %",
                "unrealised_pnl": "PnL",
            }
        )

        responsive_table(
            display_holdings.style.format(
                {
                    "Shares": "{:.2f}",
                    "Entry Price": "£{:,.2f}",
                    "Current Price": "£{:,.2f}",
                    "Market Value": "£{:,.2f}",
                    "Weight %": "{:.2f}%",
                    "PnL": "£{:,.2f}",
                }
            ),
            hide_index=True,
        )

    st.divider()

    st.subheader("Current Signals")

    if signals.empty:
        st.info("No signal report available.")
    else:
        responsive_table(
            signals,
            hide_index=False,
        )

    st.divider()

    st.subheader("Trade Analytics")

    if analytics.empty:
        st.info("No trade analytics available.")
    else:
        analytics_row = analytics.iloc[0]

        col1, col2 = responsive_columns(2)

        with col1:
            metric_card(
                "Journal Events",
                int(analytics_row["total_trades"]),
            )
            metric_card(
                "Win Rate",
                f"{analytics_row['win_rate']:.2%}",
                True,
            )

        with col2:
            metric_card(
                "Profit Factor",
                f"{analytics_row['profit_factor']:.2f}",
            )
            metric_card(
                "Realised PnL",
                f"£{analytics_row['realised_pnl']:,.2f}",
                True,
            )

    st.divider()

    st.subheader("Signals")

    if signals.empty:
        st.info("No signals available yet.")

    else:
        signals = signals.copy()

        signals.columns = [
            col.lower().replace(" ", "_")
            for col in signals.columns
        ]

        required_signal_cols = [
            "date",
            "ticker",
            "signal",
            "weight",
            "status",
        ]

        for col in required_signal_cols:
            if col not in signals.columns:
                signals[col] = ""

        display_signals = signals[
            required_signal_cols
        ].rename(
            columns={
                "date": "Date",
                "ticker": "Ticker",
                "signal": "Signal",
                "weight": "Weight",
                "status": "Status",
            }
        )

        responsive_table(
            display_signals,
            hide_index=True,
        )

    st.divider()

    st.subheader("Trade Audit")

    audit = load_trade_audit(trades)

    if audit.empty:
        st.info("No completed trades audited yet.")

    else:
        audit = audit.copy()

        audit["open_time"] = pd.to_datetime(
            audit["open_time"],
            format="mixed",
            errors="coerce",
        )

        audit["close_time"] = pd.to_datetime(
            audit["close_time"],
            format="mixed",
            errors="coerce",
        )

        audit["holding_days"] = (
            audit["close_time"] - audit["open_time"]
        ).dt.total_seconds() / 86400

        total_trades = len(audit)
        winning_trades = len(audit[audit["pnl"] > 0])
        losing_trades = len(audit[audit["pnl"] < 0])

        win_rate = (
            winning_trades / total_trades * 100
            if total_trades
            else 0
        )

        total_pnl = audit["pnl"].sum()
        best_trade = audit["pnl"].max()
        worst_trade = audit["pnl"].min()
        avg_pnl = audit["pnl"].mean()

        gross_profit = audit.loc[audit["pnl"] > 0, "pnl"].sum()
        gross_loss = abs(audit.loc[audit["pnl"] < 0, "pnl"].sum())

        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else 0
        )

        avg_win = (
            audit.loc[audit["pnl"] > 0, "pnl"].mean()
            if winning_trades > 0
            else 0
        )

        avg_loss = (
            audit.loc[audit["pnl"] < 0, "pnl"].mean()
            if losing_trades > 0
            else 0
        )

        c1, c2, c3 = responsive_columns(3)

        with c1:
            metric_card("Completed BUY -> SELL Pairs", total_trades)
            metric_card("Winners", winning_trades)

        with c2:
            metric_card("Win Rate", f"{win_rate:.1f}%", True)
            metric_card("Losers", losing_trades)

        with c3:
            metric_card("Total PnL", f"£{total_pnl:,.2f}", total_pnl >= 0)
            metric_card("Profit Factor", f"{profit_factor:.2f}", profit_factor >= 1)

        c4, c5, c6 = responsive_columns(3)

        with c4:
            metric_card("Average PnL", f"£{avg_pnl:,.2f}", avg_pnl >= 0)

        with c5:
            metric_card("Best Trade", f"£{best_trade:,.2f}", best_trade >= 0)

        with c6:
            metric_card("Worst Trade", f"£{worst_trade:,.2f}", worst_trade >= 0)

        st.divider()

        audit = audit.tail(50).iloc[::-1]

        for _, trade in audit.iterrows():
            symbol = trade.get("symbol", "Unknown")
            pnl = trade.get("pnl", 0)
            pnl_pct = trade.get("pnl_pct", 0)

            open_time = trade.get("open_time")
            close_time = trade.get("close_time")

            opened = (
                open_time.strftime("%Y-%m-%d %H:%M")
                if pd.notna(open_time)
                else "N/A"
            )
            closed = (
                close_time.strftime("%Y-%m-%d %H:%M")
                if pd.notna(close_time)
                else "N/A"
            )

            buy_price = trade.get("buy_price", 0)
            sell_price = trade.get("sell_price", 0)
            shares = trade.get("shares", 0)
            held = trade.get("holding_period", "N/A")
            open_reason = trade.get("open_reason", "N/A")
            close_reason = trade.get("close_reason", "N/A")

            result = "WIN ✅" if pnl > 0 else "LOSS ❌" if pnl < 0 else "FLAT ➖"

            with st.container(border=True):
                st.subheader(f"{symbol} — {result}")

                col1, col2 = responsive_columns(2)

            with col1:
                st.write(f"**Opened:** {opened}")
                st.write(f"**Closed:** {closed}")
                st.write(f"**Held:** {held}")
                st.write(f"**Shares:** {shares:.4f}")

            with col2:
                st.write(f"**Buy:** £{buy_price:,.2f}")
                st.write(f"**Sell:** £{sell_price:,.2f}")
                st.write(f"**PnL:** £{pnl:,.2f} ({pnl_pct:.2f}%)")

            with st.expander("🔍 Trade Replay"):
                trade_snapshot = pd.DataFrame()

                if not snapshots.empty:

                    trade_snapshot = snapshots[
                        snapshots["ticker"] == symbol
                    ].copy()

                    if not trade_snapshot.empty:

                        trade_snapshot["timestamp"] = pd.to_datetime(
                            trade_snapshot["timestamp"],
                            errors="coerce"
                        )

                        trade_snapshot = trade_snapshot.sort_values("timestamp")

                if trade_snapshot.empty:

                    st.info("No snapshot data available.")

                else:

                    buy_rows = trade_snapshot[trade_snapshot["event"] == "BUY"]
                    sell_rows = trade_snapshot[trade_snapshot["event"] == "SELL"]

                    if buy_rows.empty:
                        st.info("No entry snapshot available for this trade yet.")
                        st.stop()

                    buy = buy_rows.iloc[0]
                    sell = sell_rows.iloc[-1] if not sell_rows.empty else None

                    st.markdown("### 🟢 Entry")

                    c1, c2 = responsive_columns(2)

                    with c1:
                        st.metric("Cash", f"£{buy['cash']:,.2f}")
                        st.metric("Weight", f"{buy['portfolio_weight']:.1%}")

                    with c2:
                        st.metric("Stop Loss", f"£{buy['stop_loss']:,.2f}")
                        st.metric("Take Profit", f"£{buy['take_profit']:,.2f}")

                    st.write(f"**Reason:** {buy['reason']}")

                    st.divider()

                    st.markdown("### 🔴 Exit")

                    if sell is None:
                        st.info("No exit snapshot available yet. This trade may still be open or was created before snapshot logging.")
                    else:
                        st.metric("Reason", sell["reason"])

                        st.metric(
                            "Portfolio Value",
                            f"£{sell['portfolio_value']:,.2f}"
                        )

                    st.divider()

                    st.markdown("### 📈 Result")

                    c1, c2 = responsive_columns(2)

                    with c1:
                        st.metric("PnL", f"£{pnl:,.2f}")

                    with c2:
                        st.metric("Return", f"{pnl_pct:.2f}%")

    st.divider()
    
    if audit.empty or "close_time" not in audit.columns or "pnl" not in audit.columns:
        st.info("No completed trade equity curve available yet.")
    else:
        st.subheader("📈 Realised Equity Curve")

        equity = audit.copy()
        equity["close_time"] = pd.to_datetime(
            equity["close_time"],
            format="mixed",
            errors="coerce"
        )

        equity = equity.dropna(subset=["close_time"])
        equity = equity.sort_values("close_time")
        equity["Cumulative PnL"] = equity["pnl"].cumsum()

        st.line_chart(
            equity.set_index("close_time")["Cumulative PnL"],
            width="stretch",
        )
    if audit.empty or "pnl" not in audit.columns:
        st.info("No trade statistics available yet.")
    else:
        st.subheader("Trade Statistics")

        if "holding_days" in audit.columns:
            avg_hold = audit["holding_days"].mean()
        elif "holding_period" in audit.columns:
            holding = pd.to_timedelta(
                audit["holding_period"],
                errors="coerce"
            )
            avg_hold = holding.dt.total_seconds().div(86400).mean()
        else:
            avg_hold = 0
 
        if "pnl_pct" in audit.columns:
            avg_return = audit["pnl_pct"].mean()
        else:
            avg_return = 0

        largest_win = (
            audit.loc[audit["pnl"].idxmax(), "symbol"]
            if "symbol" in audit.columns and len(audit[audit["pnl"] > 0]) > 0
            else "None"
        )

        c1, c2, c3 = responsive_columns(3)

        with c1:
            metric_card("Average Hold", f"{avg_hold:.1f} days")

        with c2:
            metric_card("Average Return", f"{avg_return:.2f}%", avg_return >= 0)

        with c3:
            metric_card("Largest Winner", largest_win)

    st.subheader("Trade Journal")

    if trades.empty:
        st.info("No trades logged yet.")

    else:
        trades = trades.copy()

        trades.columns = [
            col.lower().replace(" ", "_")
            for col in trades.columns
        ]

        required_cols = [
            "date",
            "time",
            "ticker",
            "action",
            "shares",
            "price",
            "value",
            "pnl",
            "reason",
        ]

        for col in required_cols:
            if col not in trades.columns:
                trades[col] = ""

        trades["time"] = trades["time"].fillna("").replace("nan", "")

        trades["date"] = (
            pd.to_datetime(
                trades["date"],
                format="mixed",
                errors="coerce",
            )
            .dt.strftime("%Y-%m-%d")
            .fillna("")
        )

        display_trades = trades[
            required_cols
        ].rename(
            columns={
                "date": "Date",
                "time": "Time",
                "ticker": "Ticker",
                "action": "Action",
                "shares": "Shares",
                "price": "Price",
                "value": "Value",
                "pnl": "PnL",
                "reason": "Reason",
            }
        )

        display_trades = display_trades.tail(20).iloc[::-1]

        responsive_table(
            display_trades.style.format(
                {
                    "Shares": "{:.2f}",
                    "Price": "£{:,.2f}",
                    "Value": "£{:,.2f}",
                    "PnL": "£{:,.2f}",
                }
            ),
            hide_index=True,
        )


st.caption("Garner Quant V3 | Paper Trading Only")
