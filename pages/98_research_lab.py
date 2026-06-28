from pathlib import Path
import json
from datetime import datetime
from uuid import uuid4

import pandas as pd
import streamlit as st

try:
    from research.live_rule_backtest import run_from_saved_files
except Exception:
    run_from_saved_files = None

try:
    import config as live_config
except Exception:
    live_config = None

try:
    from research.experiment_config import build_experiment_config
except Exception:
    build_experiment_config = None


FILES = [
    "portfolio_v2.csv",
    "trade_analytics_v3.csv",
    "trade_journal_v3.csv",
    "paper_30_day_tracker.csv",
    "signal_report_v2.csv",
    "signals_v2.csv",
    "prices_v2.csv",
    "risk_levels_v2.csv",
    "weights_v2.csv",
]

EXPERIMENTS_FILE = Path("research/experiments.json")
EXPERIMENT_STATUSES = ["Draft", "Tested", "Candidate", "Production Ready"]
COMPARABLE_STATUSES = ["Tested", "Candidate", "Production Ready"]
RULE_KEYS = [
    "technical_score_threshold",
    "max_positions",
    "position_size",
    "stop_loss_pct",
    "take_profit_pct",
    "min_volume",
    "exit_mode",
]
METRIC_ROWS = [
    ("Total Return", "total_return", "percent", "higher"),
    ("CAGR", "cagr", "percent", "higher"),
    ("Annualised Return", "annualised_return", "percent", "higher"),
    ("Sharpe Ratio", "sharpe_ratio", "number", "higher"),
    ("Sortino Ratio", "sortino_ratio", "number", "higher"),
    ("Max Drawdown", "max_drawdown", "percent", "higher"),
    ("Win Rate", "win_rate", "percent", "higher"),
    ("Profit Factor", "profit_factor", "number", "higher"),
    ("Average Trade %", "average_trade_pct", "percent", "higher"),
    ("Average Hold Days", "average_holding_period", "number", "lower"),
    ("Number of Trades", "number_of_trades", "number", "higher"),
    ("Completed Trades", "completed_trades", "number", "higher"),
    ("Current Cash", "current_cash", "currency", "higher"),
    ("Ending Equity", "ending_equity", "currency", "higher"),
]


st.set_page_config(
    page_title="Research Lab | Garner Quant",
    page_icon="🧪",
    layout="wide",
)


def load_csv(filename):
    path = Path(filename)

    if not path.exists():
        return pd.DataFrame(), "missing"

    try:
        return pd.read_csv(path), ""
    except pd.errors.EmptyDataError:
        return pd.DataFrame(), "empty"
    except Exception as exc:
        return pd.DataFrame(), str(exc)


def first_metric(df, column, default="Not available"):
    if df.empty or column not in df.columns:
        return default

    value = df[column].iloc[0]

    if pd.isna(value):
        return default

    return value


def latest_metric(df, column, default=0.0):
    if df.empty or column not in df.columns:
        return default

    value = pd.to_numeric(df[column], errors="coerce").dropna()

    if value.empty:
        return default

    return float(value.iloc[-1])


def format_percent(value):
    if value == "Not available":
        return value

    try:
        return f"{float(value):.2%}"
    except Exception:
        return "Not available"


def format_number(value):
    if value == "Not available":
        return value

    try:
        return f"{float(value):,.2f}"
    except Exception:
        return "Not available"


def format_currency(value):
    if value == "Not available":
        return value

    try:
        return f"£{float(value):,.2f}"
    except Exception:
        return "Not available"


def format_metric(value, kind):
    if value in (None, "Not available"):
        return "Not available"

    if kind == "percent":
        return format_percent(value)

    if kind == "currency":
        return format_currency(value)

    return format_number(value)


def numeric_value(value):
    try:
        value = float(value)
    except Exception:
        return None

    if pd.isna(value):
        return None

    return value


def safe_config_value(name):
    try:
        import config

        return getattr(config, name, "Not configured")
    except Exception:
        return "Not configured"


def load_experiments():
    if not EXPERIMENTS_FILE.exists():
        return []

    try:
        with EXPERIMENTS_FILE.open("r", encoding="utf-8") as file:
            experiments = json.load(file)
    except Exception:
        return []

    if not isinstance(experiments, list):
        return []

    return experiments


def save_experiments(experiments):
    EXPERIMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with EXPERIMENTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(experiments, file, indent=2)


def rerun_page():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def save_and_rerun(experiments):
    save_experiments(experiments)
    rerun_page()


def live_strategy_parameters():
    return {
        "Momentum lookback": safe_config_value("MOMENTUM_LOOKBACK"),
        "Technical score threshold": 3,
        "Stop loss method": "ATR-based",
        "Stop loss %": "Not configured",
        "Take profit method": "ATR-based",
        "Take profit %": "Not configured",
        "Exit confirmation days": "Not configured",
        "Minimum holding days": "Not configured",
        "Maximum positions": "Not configured",
        "Position sizing": (
            f"ATR risk sizing ({safe_config_value('RISK_PER_TRADE')})"
            if safe_config_value("RISK_PER_TRADE") != "Not configured"
            else "Not configured"
        ),
        "Position size": "Not configured",
        "Minimum volume": "Not configured",
        "Exit mode": "signals_and_stops",
        "Allow shorts": False,
        "Include crypto": True,
        "Include ETFs": True,
        "Include US equities": True,
        "Benchmark ticker": safe_config_value("BENCHMARK_TICKER"),
    }


def new_experiment_from_live(name, description):
    return {
        "id": str(uuid4()),
        "name": name,
        "description": description,
        "created_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "Draft",
        "parameters": live_strategy_parameters(),
        "results": {},
    }


def duplicate_experiment(experiment):
    copied = json.loads(json.dumps(experiment))
    copied["id"] = str(uuid4())
    copied["name"] = f"{experiment.get('name', 'Experiment')} Copy"
    copied["created_timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    copied["status"] = "Draft"
    copied["results"] = {}
    return copied


def experiment_options(experiments):
    return [
        f"{experiment['name']} | {experiment['status']} | {experiment['created_timestamp']}"
        for experiment in experiments
    ]


def select_index(options, value, default=0):
    try:
        return options.index(value)
    except ValueError:
        return default


def status_badge(status):
    if status == "Production Ready":
        return "🟢 Production Ready"

    if status == "Candidate":
        return "🔵 Candidate"

    if status == "Tested":
        return "🟠 Tested"

    return "⚪ Draft"


def promote_status(status):
    index = select_index(EXPERIMENT_STATUSES, status)
    return EXPERIMENT_STATUSES[min(index + 1, len(EXPERIMENT_STATUSES) - 1)]


def demote_status(status):
    index = select_index(EXPERIMENT_STATUSES, status)
    return EXPERIMENT_STATUSES[max(index - 1, 0)]


def experiment_label(experiment):
    return (
        f"{experiment.get('name', 'Untitled')} | "
        f"{experiment.get('status', 'Draft')} | "
        f"{experiment.get('created_timestamp', 'Unknown')}"
    )


def experiment_by_id(experiments, experiment_id):
    for experiment in experiments:
        if experiment.get("id") == experiment_id:
            return experiment

    return None


def equity_records(equity_curve):
    if equity_curve is None or equity_curve.empty:
        return []

    records = []

    for _, row in equity_curve.iterrows():
        records.append(
            {
                "date": str(pd.to_datetime(row["date"]).date())
                if "date" in row
                else "",
                "portfolio_value": numeric_value(row.get("portfolio_value")),
                "cash": numeric_value(row.get("cash")),
            }
        )

    return records


def trade_metrics(trade_journal):
    if (
        trade_journal is None
        or trade_journal.empty
        or "action" not in trade_journal.columns
    ):
        return {
            "profit_factor": 0,
            "average_trade_pct": 0,
            "number_of_trades": 0,
        }

    sells = trade_journal[trade_journal["action"] == "SELL"].copy()

    if sells.empty:
        return {
            "profit_factor": 0,
            "average_trade_pct": 0,
            "number_of_trades": len(trade_journal),
        }

    pnl = pd.to_numeric(sells["pnl"], errors="coerce").fillna(0)
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss else 0

    if "pnl_percent" in sells.columns:
        average_trade_pct = pd.to_numeric(
            sells["pnl_percent"],
            errors="coerce",
        ).dropna().mean()
    else:
        average_trade_pct = 0

    return {
        "profit_factor": float(profit_factor),
        "average_trade_pct": float(average_trade_pct)
        if not pd.isna(average_trade_pct)
        else 0,
        "number_of_trades": int(len(trade_journal)),
    }


def equity_metrics(equity_curve, starting_cash=10000):
    if equity_curve is None or equity_curve.empty:
        return {
            "cagr": 0,
            "annualised_return": 0,
            "sortino_ratio": 0,
            "current_cash": 0,
            "ending_equity": 0,
        }

    curve = equity_curve.copy()
    curve["date"] = pd.to_datetime(curve["date"], errors="coerce")
    curve = curve.dropna(subset=["date"])
    values = pd.to_numeric(curve["portfolio_value"], errors="coerce").dropna()

    if values.empty:
        return {
            "cagr": 0,
            "annualised_return": 0,
            "sortino_ratio": 0,
            "current_cash": 0,
            "ending_equity": 0,
        }

    daily_returns = values.pct_change().dropna()
    annualised_return = daily_returns.mean() * 252 if not daily_returns.empty else 0
    negative_returns = daily_returns[daily_returns < 0]
    downside_deviation = negative_returns.std()
    sortino_ratio = (
        (daily_returns.mean() / downside_deviation) * (252 ** 0.5)
        if downside_deviation and downside_deviation != 0
        else 0
    )

    elapsed_days = (curve["date"].iloc[-1] - curve["date"].iloc[0]).days
    years = elapsed_days / 365.25 if elapsed_days > 0 else 0
    cagr = (
        (values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1
        if years and values.iloc[0] > 0
        else 0
    )

    current_cash = 0
    if "cash" in curve.columns:
        current_cash = pd.to_numeric(curve["cash"], errors="coerce").dropna()
        current_cash = float(current_cash.iloc[-1]) if not current_cash.empty else 0

    return {
        "cagr": float(cagr),
        "annualised_return": float(annualised_return),
        "sortino_ratio": float(sortino_ratio),
        "current_cash": current_cash,
        "ending_equity": float(values.iloc[-1]),
    }


def enriched_summary(equity_curve, trade_journal, summary):
    result = dict(summary or {})
    result.update(equity_metrics(equity_curve))
    result.update(trade_metrics(trade_journal))
    result.setdefault("number_of_trades", len(trade_journal))
    result.setdefault("ending_equity", 0)
    result.setdefault("current_cash", 0)
    return result


def saved_summary(experiment):
    return experiment.get("results", {}).get("summary", {})


def saved_equity_curve(experiment):
    records = experiment.get("results", {}).get("equity_curve", [])

    if not records:
        return pd.DataFrame()

    curve = pd.DataFrame(records)

    if "date" not in curve.columns or "portfolio_value" not in curve.columns:
        return pd.DataFrame()

    curve["date"] = pd.to_datetime(curve["date"], errors="coerce")
    curve["portfolio_value"] = pd.to_numeric(
        curve["portfolio_value"],
        errors="coerce",
    )
    return curve.dropna(subset=["date", "portfolio_value"])


def live_equity_curve(portfolio):
    if portfolio.empty or "equity" not in portfolio.columns:
        return pd.DataFrame()

    date_column = "Date" if "Date" in portfolio.columns else "date"

    if date_column not in portfolio.columns:
        return pd.DataFrame()

    curve = portfolio[[date_column, "equity"]].copy()
    curve.columns = ["date", "portfolio_value"]
    curve["date"] = pd.to_datetime(curve["date"], errors="coerce")
    curve["portfolio_value"] = pd.to_numeric(
        curve["portfolio_value"],
        errors="coerce",
    )
    return curve.dropna(subset=["date", "portfolio_value"])


def metric_table(experiments):
    columns = ["Metric", "Live Strategy"]
    rows = []

    for experiment in experiments:
        columns.append(experiment.get("name", "Untitled"))

    live_summary = {
        "total_return": stats["total_return"],
        "max_drawdown": stats["max_drawdown"],
        "sharpe_ratio": stats["sharpe_ratio"],
        "win_rate": win_rate,
        "number_of_trades": number_of_trades,
        "completed_trades": number_of_trades,
        "realised_pnl": realised_pnl,
        "ending_equity": current_portfolio_value,
        "current_cash": "Not available",
        "profit_factor": first_metric(analytics, "profit_factor"),
        "average_trade_pct": "Not available",
        "average_holding_period": "Not available",
        "cagr": "Not available",
        "annualised_return": "Not available",
        "sortino_ratio": "Not available",
    }

    for label, key, kind, _ in METRIC_ROWS:
        row = {
            "Metric": label,
            "Live Strategy": format_metric(live_summary.get(key), kind),
        }

        for experiment in experiments:
            row[experiment.get("name", "Untitled")] = format_metric(
                saved_summary(experiment).get(key, "Not available"),
                kind,
            )

        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def highlight_best_worst(table):
    styles = pd.DataFrame("", index=table.index, columns=table.columns)

    for row_index, (_, key, _, direction) in enumerate(METRIC_ROWS):
        values = []

        for column in table.columns[1:]:
            value_text = table.loc[row_index, column]
            cleaned = str(value_text).replace("£", "").replace(",", "")
            cleaned = cleaned.replace("%", "")
            value = numeric_value(cleaned)

            if value is not None and "%" in str(value_text):
                value = value / 100

            values.append((column, value))

        numeric_values = [value for _, value in values if value is not None]

        if len(numeric_values) < 2:
            continue

        best = max(numeric_values) if direction == "higher" else min(numeric_values)
        worst = min(numeric_values) if direction == "higher" else max(numeric_values)

        for column, value in values:
            if value is None:
                continue

            if value == best:
                styles.loc[row_index, column] = "color: #137333"
            elif value == worst:
                styles.loc[row_index, column] = "color: #b3261e"

    return styles


def differing_rules(experiment):
    experiment_rules = (
        experiment.get("results", {}).get("experiment_config")
        or (
            build_experiment_config(live_config, experiment.get("parameters", {}))
            if build_experiment_config is not None
            else {}
        )
    )
    rows = []

    for rule in RULE_KEYS:
        live_value = live_rules_config.get(rule)
        experiment_value = experiment_rules.get(rule)

        if str(live_value) != str(experiment_value):
            rows.append(
                {
                    "Rule": rule,
                    "Live Strategy": str(live_value),
                    "Selected Experiment": str(experiment_value),
                }
            )

    return pd.DataFrame(rows)


def portfolio_stats(portfolio):
    if portfolio.empty:
        return {
            "total_return": "Not available",
            "max_drawdown": "Not available",
            "sharpe_ratio": "Not available",
        }

    if "equity" in portfolio.columns:
        equity = pd.to_numeric(portfolio["equity"], errors="coerce").dropna()
        total_return = (
            (equity.iloc[-1] / equity.iloc[0]) - 1
            if len(equity) > 1 and equity.iloc[0] != 0
            else "Not available"
        )
    else:
        total_return = "Not available"

    max_drawdown = (
        pd.to_numeric(portfolio["drawdown"], errors="coerce").min()
        if "drawdown" in portfolio.columns
        else "Not available"
    )

    if "daily_return" in portfolio.columns:
        daily_return = pd.to_numeric(
            portfolio["daily_return"],
            errors="coerce",
        ).dropna()
        volatility = daily_return.std()
        sharpe_ratio = (
            (daily_return.mean() / volatility) * (252 ** 0.5)
            if volatility and volatility != 0
            else "Not available"
        )
    else:
        sharpe_ratio = "Not available"

    return {
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
    }


data = {}
load_errors = {}

for filename in FILES:
    data[filename], load_errors[filename] = load_csv(filename)

portfolio = data["portfolio_v2.csv"]
analytics = data["trade_analytics_v3.csv"]
journal = data["trade_journal_v3.csv"]
tracker = data["paper_30_day_tracker.csv"]
signals = data["signal_report_v2.csv"]

stats = portfolio_stats(portfolio)

current_portfolio_value = latest_metric(
    tracker,
    "portfolio_value",
    latest_metric(portfolio, "equity", "Not available"),
)
journal_events = len(journal)
current_signals_count = len(signals)
open_signal_count = 0

if not signals.empty and "signal" in signals.columns:
    signal_values = pd.to_numeric(signals["signal"], errors="coerce").fillna(0)
    open_signal_count = int((signal_values > 0).sum())

win_rate = first_metric(analytics, "win_rate")
number_of_trades = first_metric(analytics, "total_trades")
realised_pnl = first_metric(analytics, "realised_pnl")
experiments = load_experiments()
live_params = live_strategy_parameters()

if "selected_experiment_id" not in st.session_state:
    st.session_state["selected_experiment_id"] = (
        experiments[0].get("id") if experiments else None
    )

if "compare_experiment_ids" not in st.session_state:
    st.session_state["compare_experiment_ids"] = []

st.title("🧪 Research Lab")
st.info(
    "This page is for research only. It does not modify the live trading "
    "strategy or paper portfolio."
)

missing_files = [
    filename
    for filename, error in load_errors.items()
    if error
]

if missing_files:
    st.info(
        "Some research inputs are unavailable: "
        + ", ".join(f"{name} ({load_errors[name]})" for name in missing_files)
    )

st.subheader("Current Live Strategy Summary")

summary_cols = st.columns(6)
summary_cols[0].metric("Current portfolio value", format_number(current_portfolio_value))
summary_cols[1].metric("Total return", format_percent(stats["total_return"]))
summary_cols[2].metric("Max drawdown", format_percent(stats["max_drawdown"]))
summary_cols[3].metric("Sharpe ratio", format_number(stats["sharpe_ratio"]))
summary_cols[4].metric("Journal events", journal_events)
summary_cols[5].metric("Open BUY/HOLD signals", open_signal_count)

st.caption(f"Current signals count: {current_signals_count}")

st.divider()
st.subheader("Strategy Parameters")

strategy_params = pd.DataFrame(
    [
        {"Parameter": key, "Live value": str(value)}
        for key, value in live_params.items()
    ]
)

st.dataframe(strategy_params, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Experiments")

with st.form("duplicate_live_strategy"):
    duplicate_name = st.text_input(
        "New experiment name",
        value=f"Live Strategy Copy {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )
    duplicate_description = st.text_area(
        "Description",
        value="Draft experiment duplicated from the current live strategy configuration.",
        height=90,
    )
    duplicate_submitted = st.form_submit_button("Duplicate Live Strategy")

if duplicate_submitted:
    experiments.append(
        new_experiment_from_live(
            duplicate_name.strip() or "Untitled experiment",
            duplicate_description.strip(),
        )
    )
    save_experiments(experiments)
    st.success("Draft experiment created from live strategy.")
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

selected_experiment = None

if experiments:
    selected_experiment = experiment_by_id(
        experiments,
        st.session_state.get("selected_experiment_id"),
    )

    if selected_experiment is None:
        selected_experiment = experiments[0]
        st.session_state["selected_experiment_id"] = selected_experiment.get("id")

    comparable_experiments = [
        experiment
        for experiment in experiments
        if experiment.get("status") in COMPARABLE_STATUSES
    ]
    comparable_options = {
        experiment_label(experiment): experiment.get("id")
        for experiment in comparable_experiments
    }
    current_compare_labels = [
        label
        for label, experiment_id in comparable_options.items()
        if experiment_id in st.session_state["compare_experiment_ids"]
    ]

    chosen_compare_labels = st.multiselect(
        "Compare experiments",
        list(comparable_options.keys()),
        default=current_compare_labels[:5],
        max_selections=5,
        help="Select 2-5 Tested, Candidate, or Production Ready experiments.",
    )
    st.session_state["compare_experiment_ids"] = [
        comparable_options[label]
        for label in chosen_compare_labels
    ]

    st.subheader("Experiment Cards")

    for index, experiment in enumerate(experiments):
        summary = saved_summary(experiment)
        last_tested = experiment.get("results", {}).get(
            "tested_timestamp",
            "Not run yet",
        )
        compare_disabled = experiment.get("status") not in COMPARABLE_STATUSES

        with st.expander(
            f"{experiment.get('name', 'Untitled')} - "
            f"{status_badge(experiment.get('status', 'Draft'))}",
            expanded=experiment.get("id") == selected_experiment.get("id"),
        ):
            st.caption(experiment.get("description", ""))
            meta_cols = st.columns(6)
            meta_cols[0].metric("Status", experiment.get("status", "Draft"))
            meta_cols[1].metric("Created", experiment.get("created_timestamp", ""))
            meta_cols[2].metric("Last tested", last_tested)
            meta_cols[3].metric(
                "Total return",
                format_percent(summary.get("total_return", "Not available")),
            )
            meta_cols[4].metric(
                "Sharpe",
                format_number(summary.get("sharpe_ratio", "Not available")),
            )
            meta_cols[5].metric(
                "Completed",
                summary.get("completed_trades", "Not available"),
            )

            action_cols = st.columns(6)

            if action_cols[0].button("View", key=f"view_{experiment.get('id')}"):
                st.session_state["selected_experiment_id"] = experiment.get("id")
                rerun_page()

            compare_label = (
                "Remove Compare"
                if experiment.get("id") in st.session_state["compare_experiment_ids"]
                else "Compare"
            )

            if action_cols[1].button(
                compare_label,
                key=f"compare_{experiment.get('id')}",
                disabled=compare_disabled,
            ):
                compare_ids = st.session_state["compare_experiment_ids"]

                if experiment.get("id") in compare_ids:
                    compare_ids.remove(experiment.get("id"))
                elif len(compare_ids) < 5:
                    compare_ids.append(experiment.get("id"))

                st.session_state["compare_experiment_ids"] = compare_ids
                rerun_page()

            if action_cols[2].button(
                "Promote",
                key=f"promote_{experiment.get('id')}",
                disabled=experiment.get("status") == "Production Ready",
            ):
                experiment["status"] = promote_status(
                    experiment.get("status", "Draft")
                )
                save_and_rerun(experiments)

            if action_cols[3].button(
                "Demote",
                key=f"demote_{experiment.get('id')}",
                disabled=experiment.get("status") == "Draft",
            ):
                experiment["status"] = demote_status(
                    experiment.get("status", "Draft")
                )
                save_and_rerun(experiments)

            if action_cols[4].button(
                "Duplicate",
                key=f"duplicate_{experiment.get('id')}",
            ):
                experiments.append(duplicate_experiment(experiment))
                save_and_rerun(experiments)

            if action_cols[5].button(
                "Delete",
                key=f"delete_{experiment.get('id')}",
            ):
                experiments.pop(index)
                st.session_state["compare_experiment_ids"] = [
                    experiment_id
                    for experiment_id in st.session_state["compare_experiment_ids"]
                    if experiment_id != experiment.get("id")
                ]
                if st.session_state.get("selected_experiment_id") == experiment.get("id"):
                    st.session_state["selected_experiment_id"] = (
                        experiments[0].get("id") if experiments else None
                    )
                save_and_rerun(experiments)

    selected_experiment = experiment_by_id(
        experiments,
        st.session_state.get("selected_experiment_id"),
    )

    if selected_experiment is not None:
        status_cols = st.columns(4)
        status_cols[0].metric(
            "Experiment status",
            selected_experiment.get("status", "Draft"),
        )
        status_cols[1].metric(
            "Created",
            selected_experiment.get("created_timestamp", ""),
        )
        status_cols[2].metric("Name", selected_experiment.get("name", "Untitled"))
        status_cols[3].metric(
            "Result",
            "Available" if selected_experiment.get("results") else "Not run yet",
        )

        st.caption(selected_experiment.get("description", ""))
        st.subheader("Experiment Configuration")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Parameter": key, "Experiment value": value}
                    for key, value in selected_experiment.get("parameters", {}).items()
                ]
            ).astype(str),
            use_container_width=True,
            hide_index=True,
        )
else:
    st.info("No experiments saved yet. Duplicate the live strategy to create a draft.")

st.divider()
st.subheader("Experiment Sandbox")

col1, col2, col3 = st.columns(3)

selected_parameters = (
    selected_experiment.get("parameters", {})
    if selected_experiment
    else live_params
)


def parameter_default(name, default):
    value = selected_parameters.get(name, default)

    if value == "Not configured":
        return default

    return value


with col1:
    experiment_momentum = st.number_input(
        "Momentum lookback",
        min_value=5,
        max_value=252,
        value=int(parameter_default("Momentum lookback", 50)),
        step=5,
    )
    technical_score_threshold = st.number_input(
        "Technical score threshold",
        min_value=1,
        max_value=5,
        value=int(parameter_default("Technical score threshold", 3)),
        step=1,
    )
    experiment_stop_method = st.selectbox(
        "Stop loss method",
        ["ATR-based", "Fixed percentage", "None"],
        index=select_index(
            ["ATR-based", "Fixed percentage", "None"],
            parameter_default("Stop loss method", "ATR-based"),
        ),
    )
    stop_loss_pct = st.number_input(
        "Stop loss %",
        min_value=0.0,
        max_value=100.0,
        value=float(parameter_default("Stop loss %", 0.0) or 0.0),
        step=0.5,
    )
    experiment_take_profit_method = st.selectbox(
        "Take profit method",
        ["ATR-based", "Fixed percentage", "None"],
        index=select_index(
            ["ATR-based", "Fixed percentage", "None"],
            parameter_default("Take profit method", "ATR-based"),
        ),
    )
    take_profit_pct = st.number_input(
        "Take profit %",
        min_value=0.0,
        max_value=100.0,
        value=float(parameter_default("Take profit %", 0.0) or 0.0),
        step=0.5,
    )

with col2:
    exit_confirmation_days = st.number_input(
        "Exit confirmation days",
        min_value=0,
        max_value=20,
        value=int(parameter_default("Exit confirmation days", 0)),
        step=1,
    )
    minimum_holding_days = st.number_input(
        "Minimum holding days",
        min_value=0,
        max_value=60,
        value=int(parameter_default("Minimum holding days", 0)),
        step=1,
    )
    experiment_max_positions = st.number_input(
        "Maximum positions",
        min_value=1,
        max_value=50,
        value=int(parameter_default("Maximum positions", 5)),
        step=1,
    )
    experiment_position_sizing = st.selectbox(
        "Position sizing",
        ["ATR risk sizing", "Equal weight", "Fixed cash allocation"],
        index=select_index(
            ["ATR risk sizing", "Equal weight", "Fixed cash allocation"],
            parameter_default("Position sizing", "ATR risk sizing"),
        ),
    )
    position_size = st.number_input(
        "Position size",
        min_value=0.0,
        max_value=100.0,
        value=float(parameter_default("Position size", 0.0) or 0.0),
        step=1.0,
    )
    min_volume = st.number_input(
        "Minimum volume",
        min_value=0.0,
        value=float(parameter_default("Minimum volume", 0.0) or 0.0),
        step=1000.0,
    )
    exit_mode = st.selectbox(
        "Exit mode",
        ["signals_and_stops", "stops_only", "signal_only"],
        index=select_index(
            ["signals_and_stops", "stops_only", "signal_only"],
            parameter_default("Exit mode", "signals_and_stops"),
        ),
    )

with col3:
    allow_shorts = st.toggle(
        "Allow shorts",
        value=bool(parameter_default("Allow shorts", False)),
    )
    include_crypto = st.toggle(
        "Include crypto",
        value=bool(parameter_default("Include crypto", True)),
    )
    include_etfs = st.toggle(
        "Include ETFs",
        value=bool(parameter_default("Include ETFs", True)),
    )
    include_us_equities = st.toggle(
        "Include US equities",
        value=bool(parameter_default("Include US equities", True)),
    )

experiment_settings = {
    "Momentum lookback": experiment_momentum,
    "Technical score threshold": technical_score_threshold,
    "Stop loss method": experiment_stop_method,
    "Stop loss %": stop_loss_pct,
    "Take profit method": experiment_take_profit_method,
    "Take profit %": take_profit_pct,
    "Exit confirmation days": exit_confirmation_days,
    "Minimum holding days": minimum_holding_days,
    "Maximum positions": experiment_max_positions,
    "Position sizing": experiment_position_sizing,
    "Position size": position_size,
    "Minimum volume": min_volume,
    "Exit mode": exit_mode,
    "Allow shorts": allow_shorts,
    "Include crypto": include_crypto,
    "Include ETFs": include_etfs,
    "Include US equities": include_us_equities,
}

live_rules_config = (
    build_experiment_config(live_config, {})
    if build_experiment_config is not None
    else {}
)
experiment_rules_config = (
    build_experiment_config(live_config, experiment_settings)
    if build_experiment_config is not None
    else {}
)

st.subheader("Live Rules vs Experiment Rules")
rule_differences = pd.DataFrame(
    [
        {
            "Rule": rule,
            "Live Strategy": str(live_rules_config.get(rule)),
            "Selected Experiment": str(experiment_rules_config.get(rule)),
        }
        for rule in RULE_KEYS
        if str(live_rules_config.get(rule)) != str(experiment_rules_config.get(rule))
    ]
)

if rule_differences.empty:
    st.info("No rule differences for the selected experiment settings.")
else:
    st.dataframe(rule_differences, use_container_width=True, hide_index=True)

if st.button("Run Experiment"):
    if selected_experiment is None:
        st.info("Create or select a draft experiment before running.")
    elif run_from_saved_files is None:
        st.info(
            "Waiting for live-rule backtest implementation."
        )
    elif build_experiment_config is None:
        st.info("Waiting for experiment config implementation.")
    else:
        try:
            experiment_config = build_experiment_config(
                live_config,
                experiment_settings,
            )
            (
                live_rule_equity,
                live_rule_holdings,
                live_rule_journal,
                live_rule_summary,
            ) = run_from_saved_files(experiment_config=experiment_config)
            live_rule_summary = enriched_summary(
                live_rule_equity,
                live_rule_journal,
                live_rule_summary,
            )
            st.session_state["live_rule_backtest"] = {
                "summary": live_rule_summary,
                "equity_rows": len(live_rule_equity),
                "holdings_rows": len(live_rule_holdings),
                "journal_rows": len(live_rule_journal),
                "experiment_config": experiment_config,
                "equity_curve": equity_records(live_rule_equity),
            }
            if selected_experiment is not None:
                selected_experiment["parameters"] = experiment_settings
                selected_experiment["status"] = "Tested"
                selected_experiment["results"] = {
                    "summary": live_rule_summary,
                    "equity_rows": len(live_rule_equity),
                    "holdings_rows": len(live_rule_holdings),
                    "journal_rows": len(live_rule_journal),
                    "experiment_config": experiment_config,
                    "equity_curve": equity_records(live_rule_equity),
                    "tested_timestamp": datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                }
                save_experiments(experiments)
            st.success("Experiment run complete.")
        except Exception as exc:
            st.info(
                "Waiting for live-rule backtest implementation. "
                f"Details: {exc}"
            )

st.caption(
    "Experiment inputs are applied only to the research backtest and are not "
    "connected to live execution."
)

live_rule_result = st.session_state.get("live_rule_backtest")

if live_rule_result is None and selected_experiment is not None:
    saved_results = selected_experiment.get("results", {})

    if saved_results:
        live_rule_result = saved_results

st.divider()
st.subheader("Live-Rule Backtest")

if live_rule_result:
    live_rule_summary = live_rule_result["summary"]
    live_rule_cols = st.columns(6)
    live_rule_cols[0].metric(
        "Total return",
        format_percent(live_rule_summary["total_return"]),
    )
    live_rule_cols[1].metric(
        "Max drawdown",
        format_percent(live_rule_summary["max_drawdown"]),
    )
    live_rule_cols[2].metric(
        "Sharpe ratio",
        format_number(live_rule_summary["sharpe_ratio"]),
    )
    live_rule_cols[3].metric(
        "Completed trades",
        live_rule_summary["completed_trades"],
    )
    live_rule_cols[4].metric(
        "Win rate",
        format_percent(live_rule_summary["win_rate"]),
    )
    live_rule_cols[5].metric(
        "Realised PnL",
        format_number(live_rule_summary["realised_pnl"]),
    )
    st.caption(
        "Research-only simulation using saved signals, prices, weights, and "
        "risk levels. No live files are modified."
    )
else:
    st.info("Run the research backtest to populate live-rule results.")

st.divider()
st.subheader("Strategy Comparison")

experiment_summary = (
    live_rule_result["summary"]
    if live_rule_result
    else None
)

comparison = pd.DataFrame(
    [
        {
            "Metric": "Total Return",
            "Live Strategy": format_percent(stats["total_return"]),
            "Experiment": (
                format_percent(experiment_summary["total_return"])
                if experiment_summary
                else "Not run yet"
            ),
        },
        {
            "Metric": "Max Drawdown",
            "Live Strategy": format_percent(stats["max_drawdown"]),
            "Experiment": (
                format_percent(experiment_summary["max_drawdown"])
                if experiment_summary
                else "Not run yet"
            ),
        },
        {
            "Metric": "Sharpe Ratio",
            "Live Strategy": format_number(stats["sharpe_ratio"]),
            "Experiment": (
                format_number(experiment_summary["sharpe_ratio"])
                if experiment_summary
                else "Not run yet"
            ),
        },
        {
            "Metric": "Win Rate",
            "Live Strategy": format_percent(win_rate),
            "Experiment": (
                format_percent(experiment_summary["win_rate"])
                if experiment_summary
                else "Not run yet"
            ),
        },
        {
            "Metric": "Number of Trades",
            "Live Strategy": str(number_of_trades),
            "Experiment": (
                str(experiment_summary["completed_trades"])
                if experiment_summary
                else "Not run yet"
            ),
        },
        {
            "Metric": "Realised PnL",
            "Live Strategy": format_number(realised_pnl),
            "Experiment": (
                format_number(experiment_summary["realised_pnl"])
                if experiment_summary
                else "Not run yet"
            ),
        },
    ]
)

st.dataframe(comparison, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Experiment Comparison")

selected_compare_experiments = [
    experiment
    for experiment in experiments
    if experiment.get("id") in st.session_state.get("compare_experiment_ids", [])
]

if len(selected_compare_experiments) < 2:
    st.info("Select 2-5 Tested, Candidate, or Production Ready experiments to compare.")
else:
    metrics_comparison = metric_table(selected_compare_experiments)
    st.dataframe(
        metrics_comparison.style.apply(highlight_best_worst, axis=None),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Equity Curve Overlay")
    curve_options = ["Live baseline"] + [
        experiment.get("name", "Untitled")
        for experiment in selected_compare_experiments
    ]
    visible_curves = st.multiselect(
        "Visible curves",
        curve_options,
        default=curve_options,
    )

    overlay_frames = []

    if "Live baseline" in visible_curves:
        live_curve = live_equity_curve(portfolio)

        if not live_curve.empty:
            overlay_frames.append(
                live_curve.assign(strategy="Live baseline")
            )

    missing_curves = []

    for experiment in selected_compare_experiments:
        name = experiment.get("name", "Untitled")

        if name not in visible_curves:
            continue

        experiment_curve = saved_equity_curve(experiment)

        if experiment_curve.empty:
            missing_curves.append(name)
            continue

        overlay_frames.append(
            experiment_curve[["date", "portfolio_value"]].assign(strategy=name)
        )

    if overlay_frames:
        overlay = pd.concat(overlay_frames, ignore_index=True)
        overlay = overlay.pivot_table(
            index="date",
            columns="strategy",
            values="portfolio_value",
            aggfunc="last",
        ).sort_index()
        st.line_chart(overlay, use_container_width=True)
        st.caption("Curves use saved results only. Running an experiment refreshes its saved curve.")
    else:
        st.info("No saved equity curves are available for the selected visibility set.")

    if missing_curves:
        st.info(
            "These experiments were tested before equity curves were saved: "
            + ", ".join(missing_curves)
            + ". Re-run them to populate comparison curves."
        )

    st.subheader("Selected Experiment Rule Differences")
    if selected_experiment is not None:
        selected_rule_diff = differing_rules(selected_experiment)

        if selected_rule_diff.empty:
            st.info("The selected experiment matches the live rules for wired parameters.")
        else:
            st.dataframe(
                selected_rule_diff,
                use_container_width=True,
                hide_index=True,
            )

with st.expander("Current experiment settings"):
    st.json(experiment_settings)

st.divider()
st.subheader("Research Notes")

st.text_area(
    "Notes",
    placeholder="Capture observations, hypotheses, and promotion criteria here.",
    height=180,
)
st.caption("Notes are not persisted yet. Persistence will be added later.")

st.divider()
st.subheader("Safety Rules")

st.markdown(
    """
- Research Lab does not trade.
- Research Lab does not change portfolio files.
- Research Lab does not sync Supabase.
- Research Lab does not change live config.
- Experiments must be manually promoted later.
"""
)
