from pathlib import Path
import subprocess

import pandas as pd
import streamlit as st


FILES = [
    "broker_account.csv",
    "holdings_report.csv",
    "paper_portfolio_v3.csv",
    "trade_journal_v3.csv",
    "trade_audit_trail.csv",
    "trade_snapshots.csv",
    "trade_analytics_v3.csv",
    "paper_30_day_tracker.csv",
    "portfolio_v2.csv",
    "signal_report_v2.csv",
]

HEALTHY = "Healthy"
INFO = "Info"
WARNING = "Warning"
CRITICAL = "Critical"

STATUS_LABELS = {
    HEALTHY: "🟢 Healthy",
    INFO: "🔵 Info",
    WARNING: "🟠 Warning",
    CRITICAL: "🔴 Critical",
}


st.set_page_config(
    page_title="Admin / System Health | Garner Quant",
    page_icon="⚙️",
    layout="wide",
)


def load_csv(filename):
    path = Path(filename)

    if not path.exists():
        return pd.DataFrame(), None

    try:
        return pd.read_csv(path), None
    except pd.errors.EmptyDataError:
        return pd.DataFrame(), "File is empty"
    except Exception as exc:
        return pd.DataFrame(), str(exc)


def file_mtime(filename):
    path = Path(filename)

    if not path.exists():
        return ""

    return pd.Timestamp.fromtimestamp(path.stat().st_mtime)


def display_time(value):
    if value == "" or pd.isna(value):
        return ""

    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def age_label(value):
    if value == "" or pd.isna(value):
        return "Unavailable"

    seconds = max(
        0,
        int((pd.Timestamp.now() - pd.Timestamp(value)).total_seconds()),
    )

    if seconds < 60:
        return "just now"

    minutes = seconds // 60
    if minutes < 60:
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} ago"

    hours = minutes // 60
    if hours < 48:
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} ago"

    days = hours // 24
    unit = "day" if days == 1 else "days"
    return f"{days} {unit} ago"


def run_git_command(args):
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "Unavailable"


def latest_date(df, candidates):
    if df.empty:
        return ""

    for column in candidates:
        if column in df.columns:
            values = pd.to_datetime(df[column], errors="coerce")
            values = values.dropna()

            if not values.empty:
                return values.max()

    first_column = df.columns[0] if len(df.columns) else None

    if first_column is None:
        return ""

    values = pd.to_datetime(df[first_column], errors="coerce")
    values = values.dropna()

    if values.empty:
        return ""

    return values.max()


def is_recent(value, hours=36):
    if value == "" or pd.isna(value):
        return False

    age_hours = (
        pd.Timestamp.now() - pd.Timestamp(value)
    ).total_seconds() / 3600
    return age_hours <= hours


def numeric_series(df, column):
    if df.empty or column not in df.columns:
        return pd.Series(dtype=float)

    return pd.to_numeric(df[column], errors="coerce")


def numeric_sum(df, column):
    values = numeric_series(df, column)

    if values.empty:
        return 0.0

    return float(values.fillna(0).sum())


def first_numeric(df, column, default=0.0):
    values = numeric_series(df, column)

    if values.empty:
        return default

    return float(values.fillna(default).iloc[0])


def completed_pair_capacity(journal):
    if journal.empty or "action" not in journal.columns:
        return 0

    actions = journal["action"].astype(str).str.upper()
    buys = int((actions == "BUY").sum())
    sells = int((actions == "SELL").sum())
    return min(buys, sells)


def status_rank(status):
    return {
        HEALTHY: 0,
        INFO: 0,
        WARNING: 1,
        CRITICAL: 2,
    }.get(status, 0)


def add_check(checks, section, name, status, details):
    action = "No action needed"

    if status == WARNING:
        action = "Run GitHub workflow or inspect CSV file"
    elif status == CRITICAL:
        action = "Run python main_v2.py locally, check Supabase sync, then inspect CSV file"

    checks.append(
        {
            "Section": section,
            "Check name": name,
            "Status": STATUS_LABELS[status],
            "Details": details,
            "Recommended action": action,
        }
    )


def freshness_status(filename, exists, row_count, modified_at):
    if not exists:
        return CRITICAL if filename in REQUIRED_FILES else WARNING

    if row_count == 0:
        return WARNING

    if modified_at == "":
        return WARNING

    age_hours = (
        pd.Timestamp.now() - pd.Timestamp(modified_at)
    ).total_seconds() / 3600

    if age_hours > 72:
        return WARNING

    return HEALTHY


REQUIRED_FILES = {
    "broker_account.csv",
    "holdings_report.csv",
    "paper_portfolio_v3.csv",
    "trade_journal_v3.csv",
}

data = {}
load_errors = {}

for filename in FILES:
    data[filename], load_errors[filename] = load_csv(filename)

broker = data["broker_account.csv"]
holdings = data["holdings_report.csv"]
portfolio = data["paper_portfolio_v3.csv"]
journal = data["trade_journal_v3.csv"]
audit = data["trade_audit_trail.csv"]
snapshots = data["trade_snapshots.csv"]
analytics = data["trade_analytics_v3.csv"]
tracker = data["paper_30_day_tracker.csv"]
backtest_portfolio = data["portfolio_v2.csv"]
signals = data["signal_report_v2.csv"]

checks = []

for filename in FILES:
    path = Path(filename)
    error = load_errors[filename]

    if path.exists() and error is None:
        status = HEALTHY if filename in REQUIRED_FILES else INFO
        detail = f"{len(data[filename])} rows"
    elif path.exists():
        status = WARNING
        detail = error
    else:
        status = CRITICAL if filename in REQUIRED_FILES else WARNING
        detail = f"Missing expected file: {filename}"

    add_check(checks, "Data Files", f"{filename} available", status, detail)

generated_files = [
    "broker_account.csv",
    "holdings_report.csv",
    "paper_portfolio_v3.csv",
    "trade_journal_v3.csv",
    "trade_audit_trail.csv",
    "trade_analytics_v3.csv",
    "paper_30_day_tracker.csv",
    "portfolio_v2.csv",
    "signal_report_v2.csv",
]
generated_mtimes = [
    file_mtime(filename)
    for filename in generated_files
    if file_mtime(filename) != ""
]
latest_generated_mtime = max(generated_mtimes) if generated_mtimes else ""

add_check(
    checks,
    "Freshness",
    "Generated CSVs updated recently",
    HEALTHY if is_recent(latest_generated_mtime, hours=36) else INFO,
    (
        f"Latest generated CSV modified {display_time(latest_generated_mtime)}"
        if latest_generated_mtime != ""
        else "Generated CSV metadata unavailable"
    ),
)

portfolio_latest_date = latest_date(backtest_portfolio, ["Date", "date"])
add_check(
    checks,
    "Freshness",
    "Latest portfolio_v2.csv date exists",
    HEALTHY if portfolio_latest_date != "" else WARNING,
    (
        f"Latest date {display_time(portfolio_latest_date)}"
        if portfolio_latest_date != ""
        else "No parseable date column found in portfolio_v2.csv"
    ),
)

tracker_latest_date = latest_date(tracker, ["date", "Date"])
add_check(
    checks,
    "Freshness",
    "Tracker updated recently",
    HEALTHY if is_recent(tracker_latest_date, hours=36) else WARNING,
    (
        f"Latest tracker date {display_time(tracker_latest_date)}"
        if tracker_latest_date != ""
        else "No parseable tracker date found"
    ),
)

add_check(
    checks,
    "Freshness",
    "signal_report_v2.csv has rows",
    HEALTHY if len(signals) > 0 else WARNING,
    f"{len(signals)} rows",
)

if journal.empty:
    add_check(
        checks,
        "Trade Journal / Audit",
        "Trade journal exists and has rows",
        CRITICAL,
        "trade_journal_v3.csv has no rows",
    )
else:
    add_check(
        checks,
        "Trade Journal / Audit",
        "Trade journal exists and has rows",
        HEALTHY,
        f"{len(journal)} rows",
    )

if tracker.empty:
    add_check(
        checks,
        "Freshness",
        "Tracker exists and has rows",
        WARNING,
        "paper_30_day_tracker.csv has no rows",
    )
else:
    latest_tracker = (
        tracker["date"].iloc[-1]
        if "date" in tracker.columns
        else f"Row {len(tracker)}"
    )
    add_check(
        checks,
        "Freshness",
        "Tracker exists and has rows",
        HEALTHY,
        str(latest_tracker),
    )

if analytics.empty:
    add_check(
        checks,
        "Trade Journal / Audit",
        "Analytics exists and has rows",
        WARNING,
        "trade_analytics_v3.csv has no rows",
    )
else:
    add_check(
        checks,
        "Trade Journal / Audit",
        "Analytics exists and has rows",
        HEALTHY,
        f"{len(analytics)} rows",
    )

if broker.empty:
    add_check(
        checks,
        "Portfolio Integrity",
        "Broker cash + holdings equals portfolio value",
        CRITICAL,
        "broker_account.csv is missing or empty",
    )
else:
    cash = first_numeric(broker, "cash")
    broker_value = first_numeric(broker, "portfolio_value")
    holdings_value = numeric_sum(holdings, "market_value")
    difference = abs((cash + holdings_value) - broker_value)
    tolerance = max(1.0, broker_value * 0.001)
    status = HEALTHY if difference <= tolerance else CRITICAL
    detail = (
        f"cash {cash:,.2f} + holdings {holdings_value:,.2f}; "
        f"broker value {broker_value:,.2f}; diff {difference:,.2f}"
    )
    add_check(
        checks,
        "Portfolio Integrity",
        "Broker cash + holdings equals portfolio value",
        status,
        detail,
    )

if holdings.empty and portfolio.empty:
    add_check(
        checks,
        "Portfolio Integrity",
        "Holdings tickers match paper portfolio tickers",
        HEALTHY,
        "No open holdings in either file",
    )
elif "ticker" not in holdings.columns or "ticker" not in portfolio.columns:
    missing_columns = []
    if "ticker" not in holdings.columns:
        missing_columns.append("holdings_report.csv:ticker")
    if "ticker" not in portfolio.columns:
        missing_columns.append("paper_portfolio_v3.csv:ticker")
    add_check(
        checks,
        "Portfolio Integrity",
        "Holdings tickers match paper portfolio tickers",
        CRITICAL,
        f"Missing column(s): {', '.join(missing_columns)}",
    )
else:
    holdings_tickers = set(holdings["ticker"].dropna().astype(str))
    portfolio_tickers = set(portfolio["ticker"].dropna().astype(str))
    status = HEALTHY if holdings_tickers == portfolio_tickers else CRITICAL
    missing_from_holdings = sorted(portfolio_tickers - holdings_tickers)
    missing_from_portfolio = sorted(holdings_tickers - portfolio_tickers)
    detail = (
        f"expected portfolio tickers={sorted(portfolio_tickers)}; "
        f"actual holdings tickers={sorted(holdings_tickers)}; "
        f"missing_from_holdings={missing_from_holdings}; "
        f"missing_from_portfolio={missing_from_portfolio}"
    )
    add_check(
        checks,
        "Portfolio Integrity",
        "Holdings tickers match paper portfolio tickers",
        status,
        detail,
    )

if portfolio.empty or "ticker" not in portfolio.columns:
    add_check(
        checks,
        "Portfolio Integrity",
        "No duplicate open portfolio tickers",
        WARNING,
        "No portfolio tickers available",
    )
else:
    duplicates = portfolio.loc[
        portfolio["ticker"].duplicated(),
        "ticker",
    ].dropna().astype(str).tolist()
    duplicate_count = len(duplicates)
    add_check(
        checks,
        "Portfolio Integrity",
        "No duplicate open portfolio tickers",
        HEALTHY if duplicate_count == 0 else CRITICAL,
        (
            f"{duplicate_count} duplicate rows: {duplicates}"
            if duplicates
            else "No duplicate tickers"
        ),
    )

if broker.empty or "cash" not in broker.columns:
    add_check(
        checks,
        "Portfolio Integrity",
        "No negative cash",
        CRITICAL,
        "Cash unavailable",
    )
else:
    cash = first_numeric(broker, "cash")
    add_check(
        checks,
        "Portfolio Integrity",
        "No negative cash",
        HEALTHY if cash >= 0 else CRITICAL,
        f"Cash {cash:,.2f}",
    )

share_issues = []
for filename, df in [
    ("holdings_report.csv", holdings),
    ("paper_portfolio_v3.csv", portfolio),
    ("trade_journal_v3.csv", journal),
]:
    shares = numeric_series(df, "shares")
    if not shares.empty:
        negative_count = int((shares < 0).sum())
        if negative_count:
            share_issues.append(f"{filename}: {negative_count}")

add_check(
    checks,
    "Portfolio Integrity",
    "No negative shares",
    CRITICAL if share_issues else HEALTHY,
    "; ".join(share_issues) if share_issues else "No negative shares found",
)

possible_pairs = completed_pair_capacity(journal)
audit_rows = len(audit)
add_check(
    checks,
    "Trade Journal / Audit",
    "Audit rows are not greater than possible completed pairs",
    HEALTHY if audit_rows <= possible_pairs else CRITICAL,
    f"Audit rows {audit_rows}; possible completed pairs {possible_pairs}",
)

if Path("trade_snapshots.csv").exists():
    status = HEALTHY if load_errors["trade_snapshots.csv"] is None else WARNING
    detail = load_errors["trade_snapshots.csv"] or f"{len(snapshots)} rows"
else:
    status = WARNING
    detail = "File is missing"

add_check(checks, "Snapshots", "trade_snapshots.csv exists", status, detail)

if broker.empty:
    add_check(
        checks,
        "Freshness",
        "Latest broker update timestamp",
        INFO,
        "CSV fallback has no broker rows",
    )
elif "updated_at" in broker.columns:
    latest_broker_update = broker["updated_at"].dropna().astype(str).tail(1)
    add_check(
        checks,
        "Freshness",
        "Latest broker update timestamp",
        HEALTHY if not latest_broker_update.empty else WARNING,
        latest_broker_update.iloc[0] if not latest_broker_update.empty else "Missing",
    )
else:
    add_check(
        checks,
        "Freshness",
        "Latest broker update timestamp",
        INFO,
        "Not present in CSV fallback; Supabase broker rows carry updated_at",
    )

freshness_rows = []
for filename in FILES:
    path = Path(filename)
    exists = path.exists()
    df = data[filename]
    modified_at = file_mtime(filename)
    row_count = len(df) if load_errors[filename] is None else 0
    status = freshness_status(filename, exists, row_count, modified_at)
    freshness_rows.append(
        {
            "filename": filename,
            "exists": "yes" if exists else "no",
            "last modified": display_time(modified_at),
            "age": age_label(modified_at),
            "row count": row_count,
            "freshness status": STATUS_LABELS[status],
        }
    )

checks_df = pd.DataFrame(checks)
passed_count = int((checks_df["Status"] == STATUS_LABELS[HEALTHY]).sum())
info_count = int((checks_df["Status"] == STATUS_LABELS[INFO]).sum())
warning_count = int((checks_df["Status"] == STATUS_LABELS[WARNING]).sum())
critical_count = int((checks_df["Status"] == STATUS_LABELS[CRITICAL]).sum())
total_checks = len(checks_df)
scored_checks = passed_count + warning_count + critical_count
pass_percent = (
    (passed_count / scored_checks) * 100
    if scored_checks
    else 0
)

if critical_count:
    overall_status = "Critical"
elif warning_count:
    overall_status = "Warnings"
else:
    overall_status = "Healthy"

latest_commit_time = run_git_command(["log", "-1", "--format=%ci"])
latest_commit_message = run_git_command(["log", "-1", "--format=%s"])
csv_update_status = (
    STATUS_LABELS[HEALTHY]
    if is_recent(latest_generated_mtime, hours=36)
    else STATUS_LABELS[INFO]
)

portfolio_latest_date = latest_date(backtest_portfolio, ["Date", "date"])
tracker_latest_date = latest_date(tracker, ["date", "Date"])

cash = first_numeric(broker, "cash")
portfolio_value = first_numeric(broker, "portfolio_value")
realised_pnl = first_numeric(broker, "realised_pnl")
unrealised_pnl = first_numeric(broker, "unrealised_pnl")
holdings_value = numeric_sum(holdings, "market_value")
open_holdings_count = len(portfolio)

st.title("⚙️ Admin / System Health")

summary_cols = st.columns(7)
summary_cols[0].metric("Overall status", overall_status)
summary_cols[1].metric("Total checks", total_checks)
summary_cols[2].metric("Healthy checks", passed_count)
summary_cols[3].metric("Info", info_count)
summary_cols[4].metric("Warnings", warning_count)
summary_cols[5].metric("Critical issues", critical_count)
summary_cols[6].metric("Passed", f"{pass_percent:.0f}%")

st.caption(
    "Last validation time: "
    f"{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}"
)

if st.button("Run Full System Validation"):
    st.session_state["health_validation_complete"] = {
        "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_checks": total_checks,
        "warnings": warning_count,
        "critical": critical_count,
    }
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

validation_result = st.session_state.get("health_validation_complete")

if validation_result:
    st.success(
        "Validation complete | "
        f"{validation_result['timestamp']} | "
        f"Total checks: {validation_result['total_checks']} | "
        f"Warnings: {validation_result['warnings']} | "
        f"Critical issues: {validation_result['critical']}"
    )

st.divider()
st.subheader("GitHub Automation")

git_cols = st.columns(4)
git_cols[0].metric(
    "Last generated data commit time",
    latest_commit_time or "Unavailable",
)
git_cols[1].metric(
    "Latest commit message",
    latest_commit_message or "Unavailable",
)
git_cols[2].metric("Generated CSV freshness", csv_update_status)
git_cols[3].metric(
    "Latest CSV modified",
    (
        f"{display_time(latest_generated_mtime)} ({age_label(latest_generated_mtime)})"
        if latest_generated_mtime != ""
        else "Unavailable"
    ),
)

st.divider()
st.subheader("Market Data / Signals")

market_cols = st.columns(4)
market_cols[0].metric(
    "Latest portfolio date",
    display_time(portfolio_latest_date) or "Unavailable",
)
market_cols[1].metric(
    "Latest tracker date",
    display_time(tracker_latest_date) or "Unavailable",
)
market_cols[2].metric("Signal report rows", len(signals))
market_cols[3].metric(
    "Tracker freshness",
    (
        STATUS_LABELS[HEALTHY]
        if is_recent(tracker_latest_date, hours=36)
        else STATUS_LABELS[WARNING]
    ),
)

st.divider()
st.subheader("Portfolio Summary")

portfolio_cols = st.columns(6)
portfolio_cols[0].metric("Cash", f"{cash:,.2f}")
portfolio_cols[1].metric("Holdings market value", f"{holdings_value:,.2f}")
portfolio_cols[2].metric("Portfolio value", f"{portfolio_value:,.2f}")
portfolio_cols[3].metric("Realised PnL", f"{realised_pnl:,.2f}")
portfolio_cols[4].metric("Unrealised PnL", f"{unrealised_pnl:,.2f}")
portfolio_cols[5].metric("Open holdings", open_holdings_count)

st.divider()
st.subheader("Integrity Score")

score_cols = st.columns(5)
score_cols[0].metric("Total checks", total_checks)
score_cols[1].metric("Healthy", passed_count)
score_cols[2].metric("Info", info_count)
score_cols[3].metric("Warnings / Critical", f"{warning_count} / {critical_count}")
score_cols[4].metric("Percentage passed", f"{pass_percent:.0f}%")

for section in [
    "Data Files",
    "Portfolio Integrity",
    "Trade Journal / Audit",
    "Snapshots",
    "Freshness",
]:
    section_df = checks_df[checks_df["Section"] == section]

    if section_df.empty:
        continue

    st.subheader(section)
    st.dataframe(section_df, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Data Freshness")
st.dataframe(
    pd.DataFrame(freshness_rows),
    use_container_width=True,
    hide_index=True,
)

st.divider()
st.subheader("Data Sources")
st.table(
    pd.DataFrame(
        [
            {
                "Component": "Broker",
                "Source": "Supabase / broker_account.csv fallback",
            },
            {
                "Component": "Holdings",
                "Source": "Supabase / holdings_report.csv fallback",
            },
            {
                "Component": "Trade Journal",
                "Source": "Supabase / trade_journal_v3.csv fallback",
            },
            {
                "Component": "Trade Audit",
                "Source": "derived from current journal / CSV fallback",
            },
            {
                "Component": "Analytics",
                "Source": "trade_analytics_v3.csv",
            },
            {
                "Component": "Snapshots",
                "Source": "trade_snapshots.csv",
            },
        ]
    )
)

warnings_df = checks_df[checks_df["Status"].isin([WARNING, CRITICAL])]

st.divider()
st.subheader("Warnings")

if warnings_df.empty:
    st.success("No warnings detected.")
else:
    st.dataframe(warnings_df, use_container_width=True, hide_index=True)
