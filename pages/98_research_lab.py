from pathlib import Path
import json
from datetime import datetime
from uuid import uuid4

import pandas as pd
import streamlit as st
from ui.responsive import (
    apply_responsive_styles,
    responsive_columns,
    responsive_table,
)

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

try:
    from research.parameter_schema import PARAMETER_SCHEMA, parameter_metadata
except Exception:
    PARAMETER_SCHEMA = {}
    parameter_metadata = None

try:
    from research.parameter_sweep import (
        generate_parameter_combinations,
        run_parameter_sweep,
    )
except Exception:
    generate_parameter_combinations = None
    run_parameter_sweep = None

try:
    from research.walk_forward import run_walk_forward_validation
except Exception:
    run_walk_forward_validation = None

try:
    from research.experiment_verdict import generate_experiment_verdict
except Exception:
    generate_experiment_verdict = None


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
RESEARCH_MODES = [
    "Test One Idea",
    "Run Parameter Sweep",
    "Validate Strategy",
    "Research Insights",
]
SIMPLE_PARAMETER_OPTIONS = {
    "Technical Score Threshold": {
        "key": "technical_score_threshold",
        "experiment_name": "Technical score threshold",
        "help": (
            "How strict the strategy is when selecting trades. Higher values "
            "usually mean fewer trades but potentially higher quality signals."
        ),
    },
    "Max Positions": {
        "key": "max_positions",
        "experiment_name": "Maximum positions",
        "help": "The maximum number of holdings the strategy can own at once.",
    },
    "Stop Loss %": {
        "key": "stop_loss_pct",
        "experiment_name": "Stop loss %",
        "help": "The point where the strategy exits to limit losses.",
    },
    "Take Profit %": {
        "key": "take_profit_pct",
        "experiment_name": "Take profit %",
        "help": "The point where the strategy exits to lock in gains.",
    },
    "Position Size": {
        "key": "position_size",
        "experiment_name": "Position size",
        "help": "How much capital the strategy allocates to each trade.",
    },
    "Exit Mode": {
        "key": "exit_mode",
        "experiment_name": "Exit mode",
        "help": "How the strategy decides when to sell.",
    },
}


st.set_page_config(
    page_title="Research Lab | Garner Quant",
    page_icon="🧪",
    layout="wide",
)
apply_responsive_styles()


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


def log_experiment_run(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.setdefault("experiment_run_debug_log", [])
    st.session_state["experiment_run_debug_log"].append(f"{timestamp} - {message}")


def mark_experiment_run_success(experiment):
    st.session_state["experiment_run_success"] = (
        f"Experiment '{experiment.get('name', 'Untitled')}' updated to Tested."
    )


def live_strategy_parameters():
    return {
        "Momentum lookback": safe_config_value("MOMENTUM_LOOKBACK"),
        "Technical score threshold": schema_value(
            "technical_score_threshold",
            "default",
            3,
        ),
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
        "Exit mode": schema_value("exit_mode", "default", "signals_and_stops"),
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


def schema_value(key, field, fallback=None):
    if parameter_metadata is None:
        return fallback

    return parameter_metadata(key).get(field, fallback)


def schema_number_input(label, key, value, widget_key):
    metadata = parameter_metadata(key)
    input_kwargs = {
        "label": label,
        "min_value": metadata["minimum"],
        "value": value,
        "step": metadata["step"],
        "key": widget_key,
        "help": metadata.get("description"),
    }

    if metadata.get("maximum") is not None:
        input_kwargs["max_value"] = metadata["maximum"]

    return st.number_input(**input_kwargs)


def simple_parameter_input(label, current_value, widget_key):
    option = SIMPLE_PARAMETER_OPTIONS[label]
    key = option["key"]
    metadata = parameter_metadata(key)

    if metadata["type"] == "select":
        options = metadata.get("options", [])
        return st.selectbox(
            "New value",
            options,
            index=select_index(options, current_value, 0),
            key=widget_key,
            help=option["help"],
        )

    value = current_value
    if value in (None, "Not configured", "Not available"):
        value = metadata["default"]

    if metadata["type"] == "integer":
        value = int(value)
    else:
        value = float(value)

    return schema_number_input(
        "New value",
        key,
        value,
        widget_key,
    )


def mode_label(mode):
    labels = {
        "Test One Idea": "Test One Idea",
        "Run Parameter Sweep": "Run Parameter Sweep",
        "Validate Strategy": "Validate Strategy",
        "Research Insights": "Research Insights",
    }
    return labels.get(mode, mode)


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


def run_and_save_experiment(experiments, experiment, experiment_settings):
    if experiment is None:
        raise RuntimeError("Create or select an experiment before running.")

    if run_from_saved_files is None:
        raise RuntimeError("Research backtest runner is unavailable.")

    if build_experiment_config is None:
        raise RuntimeError("Experiment config builder is unavailable.")

    log_experiment_run(f"Loading experiment {experiment.get('id')}")
    log_experiment_run("Building experiment config")
    experiment_config = build_experiment_config(
        live_config,
        experiment_settings,
    )
    log_experiment_run("Running research backtest")
    (
        live_rule_equity,
        live_rule_holdings,
        live_rule_journal,
        live_rule_summary,
    ) = run_from_saved_files(experiment_config=experiment_config)
    log_experiment_run("Backtest complete")
    log_experiment_run("Generating summary metrics")
    live_rule_summary = enriched_summary(
        live_rule_equity,
        live_rule_journal,
        live_rule_summary,
    )
    tested_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_experiment_run("Saving experiment")
    experiment["parameters"] = experiment_settings
    experiment["status"] = "Tested"
    experiment["last_tested"] = tested_timestamp
    experiment["results"] = {
        "summary": live_rule_summary,
        "equity_rows": len(live_rule_equity),
        "holdings_rows": len(live_rule_holdings),
        "journal_rows": len(live_rule_journal),
        "experiment_config": experiment_config,
        "equity_curve": equity_records(live_rule_equity),
        "tested_timestamp": tested_timestamp,
    }
    save_experiments(experiments)

    log_experiment_run("Reloading experiment")
    reloaded_experiment = experiment_by_id(load_experiments(), experiment.get("id"))

    if reloaded_experiment is None:
        raise RuntimeError("Experiment was not found after saving.")

    if reloaded_experiment.get("status") != "Tested":
        raise RuntimeError("Experiment status did not persist as Tested.")

    if not reloaded_experiment.get("results", {}).get("summary"):
        raise RuntimeError("Experiment summary metrics did not persist.")

    log_experiment_run("Status updated to Tested")
    st.session_state["live_rule_backtest"] = reloaded_experiment["results"]
    return reloaded_experiment


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


def format_seconds(seconds):
    seconds = int(seconds or 0)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"

    if minutes:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def ranking_table(experiments, metric, ascending=False):
    rows = []

    for experiment in experiments:
        summary = saved_summary(experiment)
        value = numeric_value(summary.get(metric))

        if value is None:
            continue

        rows.append(
            {
                "Experiment": experiment.get("name", "Untitled"),
                "Status": experiment.get("status", "Draft"),
                "Metric": value,
                "Total Return": summary.get("total_return", "Not available"),
                "Sharpe": summary.get("sharpe_ratio", "Not available"),
                "Max Drawdown": summary.get("max_drawdown", "Not available"),
                "Profit Factor": summary.get("profit_factor", "Not available"),
                "Completed Trades": summary.get(
                    "completed_trades",
                    "Not available",
                ),
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("Metric", ascending=ascending).head(10)


def display_ranking(title, experiments, metric, kind, ascending=False):
    table = ranking_table(experiments, metric, ascending=ascending)

    st.write(title)

    if table.empty:
        st.info("No ranked results available yet.")
        return

    table = table.copy()
    table["Metric"] = table["Metric"].apply(lambda value: format_metric(value, kind))
    table["Total Return"] = table["Total Return"].apply(
        lambda value: format_percent(value)
    )
    table["Sharpe"] = table["Sharpe"].apply(lambda value: format_number(value))
    table["Max Drawdown"] = table["Max Drawdown"].apply(
        lambda value: format_percent(value)
    )
    table["Profit Factor"] = table["Profit Factor"].apply(
        lambda value: format_number(value)
    )

    responsive_table(table, hide_index=True)


def walk_forward_result(experiment):
    return experiment.get("walk_forward", {})


def walk_forward_status(experiment):
    return walk_forward_result(experiment).get("status", "Not Run")


def walk_forward_fold_table(result):
    rows = result.get("fold_results", [])

    if not rows:
        return pd.DataFrame()

    table = pd.DataFrame(rows)

    for column in [
        "Return",
        "CAGR",
        "Sharpe Ratio",
        "Sortino Ratio",
        "Max Drawdown",
        "Win Rate",
        "Profit Factor",
        "Number of Trades",
    ]:
        if column in table.columns:
            table[column] = pd.to_numeric(table[column], errors="coerce")

    return table


def display_walk_forward_table(table):
    if table.empty:
        st.info("No fold results available.")
        return

    display = table.copy()

    for column in ["Return", "CAGR", "Max Drawdown", "Win Rate"]:
        if column in display.columns:
            display[column] = display[column].apply(format_percent)

    for column in ["Sharpe Ratio", "Sortino Ratio", "Profit Factor"]:
        if column in display.columns:
            display[column] = display[column].apply(format_number)

    responsive_table(display, hide_index=True)


def walk_forward_curve_frame(result, per_fold=True):
    rows = []

    if per_fold:
        for fold in result.get("fold_curves", []):
            for row in fold.get("equity_curve", []):
                rows.append(
                    {
                        "date": row.get("date"),
                        "portfolio_value": row.get("portfolio_value"),
                        "fold": f"Fold {fold.get('fold')}",
                    }
                )
    else:
        rows = result.get("combined_equity_curve", [])

    if not rows:
        return pd.DataFrame()

    curve = pd.DataFrame(rows)
    curve["date"] = pd.to_datetime(curve["date"], errors="coerce")
    curve["portfolio_value"] = pd.to_numeric(
        curve["portfolio_value"],
        errors="coerce",
    )
    curve = curve.dropna(subset=["date", "portfolio_value"])

    if per_fold and "fold" in curve.columns:
        return curve.pivot_table(
            index="date",
            columns="fold",
            values="portfolio_value",
            aggfunc="last",
        ).sort_index()

    return curve.set_index("date")["portfolio_value"].sort_index()


def metric_fold_frame(table):
    if table.empty:
        return pd.DataFrame()

    columns = [
        "Return",
        "CAGR",
        "Sharpe Ratio",
        "Sortino Ratio",
        "Max Drawdown",
        "Win Rate",
        "Profit Factor",
    ]
    available = [column for column in columns if column in table.columns]

    if not available:
        return pd.DataFrame()

    frame = table[["Fold"] + available].copy()
    frame["Fold"] = frame["Fold"].apply(lambda value: f"Fold {int(value)}")
    return frame.set_index("Fold")


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
    "Use Research Lab to safely test strategy ideas without changing live trading."
)
st.caption(
    "Research Lab does not trade, modify live config, change the paper portfolio, "
    "deploy strategies, or sync production data. It only creates research results."
)

st.markdown(
    """
**Simple workflow**
1. Choose an idea
2. Run experiment
3. Compare results
4. Read verdict
5. Validate before production
"""
)

if "research_lab_mode" not in st.session_state:
    st.session_state["research_lab_mode"] = "Test One Idea"

mode_cols = responsive_columns(4)
mode_descriptions = {
    "Test One Idea": "Change one setting and see what happens.",
    "Run Parameter Sweep": "Test a range of values automatically.",
    "Validate Strategy": "Check robustness with walk-forward testing.",
    "Research Insights": "Find suggested ideas from trade history.",
}

for index, mode in enumerate(RESEARCH_MODES):
    with mode_cols[index]:
        active = st.session_state["research_lab_mode"] == mode
        st.write(f"**{mode_label(mode)}**")
        st.caption(mode_descriptions[mode])
        if st.button(
            "Selected" if active else "Open",
            key=f"research_mode_{mode}",
            disabled=active,
            use_container_width=True,
        ):
            st.session_state["research_lab_mode"] = mode
            rerun_page()

research_mode = st.session_state["research_lab_mode"]
st.success(f"Current mode: {mode_label(research_mode)}")

if st.session_state.get("experiment_run_success"):
    st.success(st.session_state.pop("experiment_run_success"))

if st.session_state.get("experiment_run_debug_log"):
    with st.expander("Last experiment run debug log", expanded=False):
        for log_line in st.session_state["experiment_run_debug_log"]:
            st.write(log_line)

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

summary_cols = responsive_columns(6)
summary_cols[0].metric("Current portfolio value", format_number(current_portfolio_value))
summary_cols[1].metric("Total return", format_percent(stats["total_return"]))
summary_cols[2].metric("Max drawdown", format_percent(stats["max_drawdown"]))
summary_cols[3].metric("Sharpe ratio", format_number(stats["sharpe_ratio"]))
summary_cols[4].metric("Journal events", journal_events)
summary_cols[5].metric("Open BUY/HOLD signals", open_signal_count)

st.caption(f"Current signals count: {current_signals_count}")

if research_mode == "Test One Idea":
    st.divider()
    st.subheader("Strategy Parameters")

    strategy_params = pd.DataFrame(
        [
            {"Parameter": key, "Live value": str(value)}
            for key, value in live_params.items()
        ]
    )

    responsive_table(strategy_params, hide_index=True)

if research_mode == "Research Insights":
    st.divider()
    st.subheader("Research Insights")
    st.info(
        "Use the Research Insights page to find patterns worth investigating "
        "from completed trades and tested experiments."
    )
    st.write(
        "Insights are research-only. They suggest ideas to test here; they do "
        "not change the live strategy."
    )
    st.markdown(
        """
**Suggested path**
1. Review patterns worth investigating
2. Bring one idea back to Test One Idea
3. Run a parameter sweep if the first result looks interesting
4. Validate with walk-forward testing before production review
"""
    )

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
    new_experiment = new_experiment_from_live(
        duplicate_name.strip() or "Untitled experiment",
        duplicate_description.strip(),
    )
    experiments.append(new_experiment)
    st.session_state["selected_experiment_id"] = new_experiment.get("id")
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

    st.caption("To compare experiments, click Compare on 2-5 tested experiment cards.")
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

    selected_compare_count = len(st.session_state["compare_experiment_ids"])
    if selected_compare_count == 0:
        st.info("No experiments selected for comparison yet.")
    elif selected_compare_count == 1:
        selected_label = next(
            (
                label
                for label, experiment_id in comparable_options.items()
                if experiment_id in st.session_state["compare_experiment_ids"]
            ),
            "Selected experiment",
        )
        st.info(
            f"Selected: {selected_label}. Select one more tested experiment "
            "to unlock comparison."
        )
    else:
        st.success(f"{selected_compare_count} experiments selected for comparison.")

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
            meta_cols = responsive_columns(6)
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

            action_cols = responsive_columns(6)

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
                copied_experiment = duplicate_experiment(experiment)
                experiments.append(copied_experiment)
                st.session_state["selected_experiment_id"] = copied_experiment.get(
                    "id"
                )
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
        status_cols = responsive_columns(4)
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
        responsive_table(
            pd.DataFrame(
                [
                    {"Parameter": key, "Experiment value": value}
                    for key, value in selected_experiment.get("parameters", {}).items()
                ]
            ).astype(str),
            hide_index=True,
        )
else:
    st.info("No experiments saved yet. Duplicate the live strategy to create a draft.")

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


if research_mode == "Test One Idea":
    st.divider()
    st.subheader("Test One Idea")
    st.caption(
        "Use this guided workflow when you want to change one strategy setting "
        "and see what happens. Everything else stays the same."
    )

    tested_options = {
        experiment_label(experiment): experiment
        for experiment in experiments
        if experiment.get("status") in COMPARABLE_STATUSES
    }
    baseline_options = ["Live Strategy"] + list(tested_options.keys())

    wizard_cols = responsive_columns(3)

    with wizard_cols[0]:
        st.markdown("**Step 1: Choose baseline strategy**")
        wizard_baseline_label = st.selectbox(
            "Baseline strategy",
            baseline_options,
            key="wizard_baseline_strategy",
            help="The strategy you want to compare against.",
        )

    wizard_baseline_experiment = tested_options.get(wizard_baseline_label)
    wizard_base_parameters = (
        wizard_baseline_experiment.get("parameters", {})
        if wizard_baseline_experiment is not None
        else live_params
    )

    with wizard_cols[1]:
        st.markdown("**Step 2: Choose what to test**")
        wizard_parameter_label = st.selectbox(
            "Strategy setting",
            list(SIMPLE_PARAMETER_OPTIONS.keys()),
            key="wizard_parameter_label",
        )
        st.caption(SIMPLE_PARAMETER_OPTIONS[wizard_parameter_label]["help"])

    wizard_option = SIMPLE_PARAMETER_OPTIONS[wizard_parameter_label]
    wizard_experiment_name = wizard_option["experiment_name"]
    wizard_current_value = wizard_base_parameters.get(
        wizard_experiment_name,
        schema_value(wizard_option["key"], "default", "Not configured"),
    )

    with wizard_cols[2]:
        st.markdown("**Step 3: Set new value**")
        wizard_new_value = simple_parameter_input(
            wizard_parameter_label,
            wizard_current_value,
            "wizard_new_parameter_value",
        )

    wizard_settings = dict(wizard_base_parameters)
    wizard_settings[wizard_experiment_name] = wizard_new_value

    st.markdown("**Step 4: Review before running**")
    review = pd.DataFrame(
        [
            {
                "You are testing": wizard_parameter_label,
                "Current value": wizard_current_value,
                "New value": wizard_new_value,
            },
            {
                "You are testing": "Everything else",
                "Current value": "Unchanged",
                "New value": "Unchanged",
            },
            {
                "You are testing": "Live trading impact",
                "Current value": "None",
                "New value": "This will not affect live trading",
            },
        ]
    )
    responsive_table(review.astype(str), hide_index=True)

    if st.button("Run Guided Experiment", use_container_width=True):
        st.session_state["experiment_run_debug_log"] = []
        log_experiment_run("Run guided experiment clicked")

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            if wizard_baseline_experiment is None:
                wizard_experiment = new_experiment_from_live(
                    f"Test {wizard_parameter_label} {wizard_current_value} to {wizard_new_value} {timestamp}",
                    "Guided one-setting experiment created in Research Lab.",
                )
            else:
                wizard_experiment = duplicate_experiment(wizard_baseline_experiment)
                wizard_experiment["name"] = (
                    f"Test {wizard_parameter_label} "
                    f"{wizard_current_value} to {wizard_new_value} {timestamp}"
                )
                wizard_experiment["description"] = (
                    "Guided one-setting experiment duplicated from "
                    f"{wizard_baseline_experiment.get('name', 'baseline')}."
                )

            wizard_experiment["parameters"] = wizard_settings
            experiments.append(wizard_experiment)
            reloaded_experiment = run_and_save_experiment(
                experiments,
                wizard_experiment,
                wizard_settings,
            )
            mark_experiment_run_success(reloaded_experiment)
            st.session_state["selected_experiment_id"] = reloaded_experiment.get("id")
            compare_ids = set(st.session_state.get("compare_experiment_ids", []))

            if wizard_baseline_experiment is not None:
                compare_ids.add(wizard_baseline_experiment.get("id"))

            compare_ids.add(reloaded_experiment.get("id"))
            st.session_state["compare_experiment_ids"] = list(compare_ids)[-5:]
            rerun_page()
        except Exception as exc:
            log_experiment_run(f"Guided run failed: {exc}")
            st.info(f"Guided experiment could not run: {exc}")

    wizard_result = (
        selected_experiment
        if selected_experiment and selected_experiment.get("status") == "Tested"
        else None
    )

    if wizard_result:
        st.markdown("**Step 5: Latest selected result**")
        wizard_summary = saved_summary(wizard_result)
        result_cols = responsive_columns(6)
        result_cols[0].metric("Status", wizard_result.get("status", "Draft"))
        result_cols[1].metric(
            "Total Return",
            format_percent(wizard_summary.get("total_return", "Not available")),
        )
        result_cols[2].metric(
            "Sharpe",
            format_number(wizard_summary.get("sharpe_ratio", "Not available")),
        )
        result_cols[3].metric(
            "Max Drawdown",
            format_percent(wizard_summary.get("max_drawdown", "Not available")),
        )
        result_cols[4].metric(
            "Win Rate",
            format_percent(wizard_summary.get("win_rate", "Not available")),
        )
        result_cols[5].metric(
            "Completed Trades",
            wizard_summary.get("completed_trades", "Not available"),
        )

st.divider()
with st.expander("Advanced Experiment Controls", expanded=False):
    st.subheader("Experiment Sandbox")
    col1, col2, col3 = responsive_columns(3)


with col1:
    experiment_momentum = st.number_input(
        "Momentum lookback",
        min_value=5,
        max_value=252,
        value=int(parameter_default("Momentum lookback", 50)),
        step=5,
    )
    technical_score_threshold = schema_number_input(
        "Technical score threshold",
        "technical_score_threshold",
        int(
            parameter_default(
                "Technical score threshold",
                schema_value("technical_score_threshold", "default", 3),
            )
        ),
        "experiment_technical_score_threshold",
    )
    experiment_stop_method = st.selectbox(
        "Stop loss method",
        ["ATR-based", "Fixed percentage", "None"],
        index=select_index(
            ["ATR-based", "Fixed percentage", "None"],
            parameter_default("Stop loss method", "ATR-based"),
        ),
    )
    stop_loss_pct = schema_number_input(
        "Stop loss %",
        "stop_loss_pct",
        float(
            parameter_default(
                "Stop loss %",
                schema_value("stop_loss_pct", "default", 0.0),
            )
            or 0.0
        ),
        "experiment_stop_loss_pct",
    )
    experiment_take_profit_method = st.selectbox(
        "Take profit method",
        ["ATR-based", "Fixed percentage", "None"],
        index=select_index(
            ["ATR-based", "Fixed percentage", "None"],
            parameter_default("Take profit method", "ATR-based"),
        ),
    )
    take_profit_pct = schema_number_input(
        "Take profit %",
        "take_profit_pct",
        float(
            parameter_default(
                "Take profit %",
                schema_value("take_profit_pct", "default", 0.0),
            )
            or 0.0
        ),
        "experiment_take_profit_pct",
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
    experiment_max_positions = schema_number_input(
        "Maximum positions",
        "max_positions",
        int(
            parameter_default(
                "Maximum positions",
                schema_value("max_positions", "default", 5),
            )
        ),
        "experiment_max_positions",
    )
    experiment_position_sizing = st.selectbox(
        "Position sizing",
        ["ATR risk sizing", "Equal weight", "Fixed cash allocation"],
        index=select_index(
            ["ATR risk sizing", "Equal weight", "Fixed cash allocation"],
            parameter_default("Position sizing", "ATR risk sizing"),
        ),
    )
    position_size = schema_number_input(
        "Position size",
        "position_size",
        float(
            parameter_default(
                "Position size",
                schema_value("position_size", "default", 0.0),
            )
            or 0.0
        ),
        "experiment_position_size",
    )
    min_volume = schema_number_input(
        "Minimum volume",
        "min_volume",
        float(
            parameter_default(
                "Minimum volume",
                schema_value("min_volume", "default", 0.0),
            )
            or 0.0
        ),
        "experiment_min_volume",
    )
    exit_mode = st.selectbox(
        "Exit mode",
        schema_value(
            "exit_mode",
            "options",
            ["signals_and_stops", "stops_only", "signal_only"],
        ),
        index=select_index(
            schema_value(
                "exit_mode",
                "options",
                ["signals_and_stops", "stops_only", "signal_only"],
            ),
            parameter_default(
                "Exit mode",
                schema_value("exit_mode", "default", "signals_and_stops"),
            ),
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

if research_mode == "Test One Idea":
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
        responsive_table(rule_differences, hide_index=True)

    if st.button("Run Experiment"):
        st.session_state["experiment_run_debug_log"] = []
        log_experiment_run("Run Experiment clicked")
        try:
            reloaded_experiment = run_and_save_experiment(
                experiments,
                selected_experiment,
                experiment_settings,
            )
            mark_experiment_run_success(reloaded_experiment)
            st.session_state["selected_experiment_id"] = reloaded_experiment.get("id")
            st.session_state["compare_experiment_ids"] = list(
                set(st.session_state.get("compare_experiment_ids", []))
                | {reloaded_experiment.get("id")}
            )
            rerun_page()
        except Exception as exc:
            log_experiment_run(f"Run failed: {exc}")
            st.info(f"Experiment could not run: {exc}")

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
        live_rule_cols = responsive_columns(6)
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

    responsive_table(comparison, hide_index=True)

    st.divider()
    st.subheader("Experiment Comparison")

    selected_compare_experiments = [
        experiment
        for experiment in experiments
        if experiment.get("id") in st.session_state.get("compare_experiment_ids", [])
    ]

    if len(selected_compare_experiments) < 2:
        if len(selected_compare_experiments) == 1:
            st.info(
                f"Selected: {selected_compare_experiments[0].get('name', 'Untitled')}. "
                "Select one more tested experiment to unlock comparison."
            )
        else:
            st.info(
                "Select one more tested experiment to unlock comparison. "
                "Use the Compare button on 2-5 tested experiment cards."
            )
    else:
            st.subheader("Experiment Verdict")

            if generate_experiment_verdict is None:
                st.info("Experiment verdict engine is unavailable.")
            else:
                verdict_options = {
                    experiment_label(experiment): experiment
                    for experiment in selected_compare_experiments
                }
                verdict_labels = list(verdict_options.keys())
                verdict_cols = responsive_columns(2)

                baseline_label = verdict_cols[0].selectbox(
                    "Baseline",
                    verdict_labels,
                    index=0,
                    key="verdict_baseline_experiment",
                )
                candidate_label = verdict_cols[1].selectbox(
                    "Candidate",
                    verdict_labels,
                    index=1 if len(verdict_labels) > 1 else 0,
                    key="verdict_candidate_experiment",
                )

                baseline_experiment = verdict_options[baseline_label]
                candidate_experiment = verdict_options[candidate_label]

                if baseline_experiment.get("id") == candidate_experiment.get("id"):
                    st.info("Choose two different experiments to generate a verdict.")
                else:
                    verdict = generate_experiment_verdict(
                        baseline_experiment,
                        candidate_experiment,
                    )
                    verdict_label = verdict.get("verdict", "Neutral")
                    verdict_icon = {
                        "Highly Promising": "✅",
                        "Promising": "🟢",
                        "Neutral": "⚪",
                        "Needs More Testing": "🟠",
                        "Not Recommended": "❌",
                    }.get(verdict_label, "⚪")

                    verdict_metric_cols = responsive_columns(3)
                    verdict_metric_cols[0].metric(
                        "Plain-English Verdict",
                        f"{verdict_icon} {verdict_label}",
                    )
                    verdict_metric_cols[1].metric(
                        "Confidence",
                        verdict.get("confidence", "Low"),
                    )
                    verdict_metric_cols[2].metric(
                        "Research Score",
                        format_number(verdict.get("score", 0)),
                    )

                    st.markdown("**Executive Summary**")
                    st.write(verdict.get("summary", "No summary available."))

                    parameter_changes = verdict.get("parameter_changes", [])
                    st.markdown("**What changed**")
                    if parameter_changes:
                        responsive_table(
                            pd.DataFrame(parameter_changes).rename(
                                columns={
                                    "parameter": "Setting",
                                    "baseline": "Old value",
                                    "candidate": "New value",
                                }
                            ),
                            hide_index=True,
                        )
                    else:
                        st.info("No wired parameter differences were detected.")

                    detail_cols = responsive_columns(2)
                    with detail_cols[0]:
                        st.markdown("**Good: what improved**")
                        for item in verdict.get("strengths", []):
                            st.write(f"- {item}")

                    with detail_cols[1]:
                        st.markdown("**Bad: what got worse**")
                        for item in verdict.get("weaknesses", []):
                            st.write(f"- {item}")

                    st.markdown("**Evidence**")
                    for item in verdict.get("evidence", []):
                        st.write(f"- {item}")

                    st.markdown("**Plain-English Recommendation**")
                    if verdict_label in {"Highly Promising", "Promising"}:
                        st.success(
                            "This looks worth more testing. Do not promote it yet; "
                            "validate it with a sweep and walk-forward test first."
                        )
                    elif verdict_label == "Not Recommended":
                        st.warning(
                            "Do not promote this version. The trade-off looks worse "
                            "than the baseline based on saved results."
                        )
                    else:
                        st.info(
                            "This needs more evidence before you treat it as better or worse."
                        )

                    st.markdown("**Suggested next experiment**")
                    st.write(verdict.get("suggested_next_experiment", "No suggestion available."))

            metrics_comparison = metric_table(selected_compare_experiments)
            responsive_table(
                metrics_comparison.style.apply(highlight_best_worst, axis=None),
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
                st.line_chart(overlay, width="stretch")
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
                    responsive_table(
                        selected_rule_diff,
                        hide_index=True,
                    )

if research_mode == "Run Parameter Sweep":
    st.divider()
    st.subheader("Parameter Sweep")
    st.caption(
        "Sweeps create normal Tested experiments in research/experiments.json. "
        "They do not modify production strategy, portfolio files, Supabase, or GitHub Actions."
    )

    if generate_parameter_combinations is None or run_parameter_sweep is None:
        st.info("Parameter sweep engine is unavailable.")
    else:
        sweep_name = st.text_input(
            "Sweep name",
            value=f"Sweep {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            key="sweep_name",
        )

        sweep_spec = {}

        st.write("Choose parameters")

        sweep_cols = responsive_columns(2)

        with sweep_cols[0]:
            use_threshold = st.checkbox(
                "Sweep technical_score_threshold",
                value=True,
                key="sweep_threshold_enabled",
            )
            threshold_mode = st.radio(
                "technical_score_threshold mode",
                ["Single", "Range"],
                horizontal=True,
                key="sweep_threshold_mode",
            )
            threshold_cols = responsive_columns(3)

            if threshold_mode == "Single":
                threshold_single = threshold_cols[0].number_input(
                    "technical_score_threshold",
                    min_value=schema_value("technical_score_threshold", "minimum", 0),
                    max_value=schema_value("technical_score_threshold", "maximum", 5),
                    value=schema_value("technical_score_threshold", "default", 3),
                    step=schema_value("technical_score_threshold", "step", 1),
                    key="sweep_threshold_single",
                )
                sweep_spec["technical_score_threshold"] = {
                    "enabled": use_threshold,
                    "mode": "Single",
                    "single": threshold_single,
                }
            else:
                sweep_spec["technical_score_threshold"] = {
                    "enabled": use_threshold,
                    "mode": "Range",
                    "start": threshold_cols[0].number_input(
                        "threshold start",
                        min_value=schema_value("technical_score_threshold", "minimum", 0),
                        max_value=schema_value("technical_score_threshold", "maximum", 5),
                        value=schema_value("technical_score_threshold", "minimum", 0),
                        step=schema_value("technical_score_threshold", "step", 1),
                        key="sweep_threshold_start",
                    ),
                    "end": threshold_cols[1].number_input(
                        "threshold end",
                        min_value=schema_value("technical_score_threshold", "minimum", 0),
                        max_value=schema_value("technical_score_threshold", "maximum", 5),
                        value=schema_value("technical_score_threshold", "maximum", 5),
                        step=schema_value("technical_score_threshold", "step", 1),
                        key="sweep_threshold_end",
                    ),
                    "step": threshold_cols[2].number_input(
                        "threshold step",
                        min_value=schema_value("technical_score_threshold", "step", 1),
                        max_value=schema_value("technical_score_threshold", "maximum", 5),
                        value=schema_value("technical_score_threshold", "step", 1),
                        step=schema_value("technical_score_threshold", "step", 1),
                        key="sweep_threshold_step",
                    ),
                }

            use_max_positions = st.checkbox(
                "Sweep max_positions",
                value=True,
                key="sweep_max_positions_enabled",
            )
            max_positions_mode = st.radio(
                "max_positions mode",
                ["Single", "Range"],
                horizontal=True,
                key="sweep_max_positions_mode",
            )
            max_position_cols = responsive_columns(3)

            if max_positions_mode == "Single":
                sweep_spec["max_positions"] = {
                    "enabled": use_max_positions,
                    "mode": "Single",
                    "single": max_position_cols[0].number_input(
                        "max_positions",
                        min_value=schema_value("max_positions", "minimum", 1),
                        max_value=schema_value("max_positions", "maximum", 50),
                        value=schema_value("max_positions", "default", 5),
                        step=schema_value("max_positions", "step", 1),
                        key="sweep_max_positions_single",
                    ),
                }
            else:
                sweep_spec["max_positions"] = {
                    "enabled": use_max_positions,
                    "mode": "Range",
                    "start": max_position_cols[0].number_input(
                        "max positions start",
                        min_value=schema_value("max_positions", "minimum", 1),
                        max_value=schema_value("max_positions", "maximum", 50),
                        value=3,
                        step=schema_value("max_positions", "step", 1),
                        key="sweep_max_positions_start",
                    ),
                    "end": max_position_cols[1].number_input(
                        "max positions end",
                        min_value=schema_value("max_positions", "minimum", 1),
                        max_value=schema_value("max_positions", "maximum", 50),
                        value=8,
                        step=schema_value("max_positions", "step", 1),
                        key="sweep_max_positions_end",
                    ),
                    "step": max_position_cols[2].number_input(
                        "max positions step",
                        min_value=schema_value("max_positions", "step", 1),
                        max_value=schema_value("max_positions", "maximum", 50),
                        value=schema_value("max_positions", "step", 1),
                        step=schema_value("max_positions", "step", 1),
                        key="sweep_max_positions_step",
                    ),
                }

            use_position_size = st.checkbox(
                "Sweep position_size",
                value=False,
                key="sweep_position_size_enabled",
            )
            position_size_mode = st.radio(
                "position_size mode",
                ["Single", "Range"],
                horizontal=True,
                key="sweep_position_size_mode",
            )
            position_size_cols = responsive_columns(3)

            if position_size_mode == "Single":
                sweep_spec["position_size"] = {
                    "enabled": use_position_size,
                    "mode": "Single",
                    "single": position_size_cols[0].number_input(
                        "position_size %",
                        min_value=schema_value("position_size", "minimum", 0.0),
                        max_value=schema_value("position_size", "maximum", 100.0),
                        value=5.0,
                        step=schema_value("position_size", "step", 1.0),
                        key="sweep_position_size_single",
                    ),
                }
            else:
                sweep_spec["position_size"] = {
                    "enabled": use_position_size,
                    "mode": "Range",
                    "start": position_size_cols[0].number_input(
                        "position size start %",
                        min_value=schema_value("position_size", "minimum", 0.0),
                        max_value=schema_value("position_size", "maximum", 100.0),
                        value=5.0,
                        step=schema_value("position_size", "step", 1.0),
                        key="sweep_position_size_start",
                    ),
                    "end": position_size_cols[1].number_input(
                        "position size end %",
                        min_value=schema_value("position_size", "minimum", 0.0),
                        max_value=schema_value("position_size", "maximum", 100.0),
                        value=15.0,
                        step=schema_value("position_size", "step", 1.0),
                        key="sweep_position_size_end",
                    ),
                    "step": position_size_cols[2].number_input(
                        "position size step %",
                        min_value=schema_value("position_size", "step", 1.0),
                        max_value=schema_value("position_size", "maximum", 100.0),
                        value=5.0,
                        step=schema_value("position_size", "step", 1.0),
                        key="sweep_position_size_step",
                    ),
                }

            use_min_volume = st.checkbox(
                "Sweep min_volume",
                value=False,
                key="sweep_min_volume_enabled",
            )
            min_volume_mode = st.radio(
                "min_volume mode",
                ["Single", "Range"],
                horizontal=True,
                key="sweep_min_volume_mode",
            )
            min_volume_cols = responsive_columns(3)

            if min_volume_mode == "Single":
                sweep_spec["min_volume"] = {
                    "enabled": use_min_volume,
                    "mode": "Single",
                    "single": min_volume_cols[0].number_input(
                        "min_volume",
                        min_value=schema_value("min_volume", "minimum", 0.0),
                        value=schema_value("min_volume", "default", 0.0),
                        step=schema_value("min_volume", "step", 1000.0),
                        key="sweep_min_volume_single",
                    ),
                }
            else:
                sweep_spec["min_volume"] = {
                    "enabled": use_min_volume,
                    "mode": "Range",
                    "start": min_volume_cols[0].number_input(
                        "min volume start",
                        min_value=schema_value("min_volume", "minimum", 0.0),
                        value=schema_value("min_volume", "default", 0.0),
                        step=schema_value("min_volume", "step", 1000.0),
                        key="sweep_min_volume_start",
                    ),
                    "end": min_volume_cols[1].number_input(
                        "min volume end",
                        min_value=schema_value("min_volume", "minimum", 0.0),
                        value=100000.0,
                        step=schema_value("min_volume", "step", 1000.0),
                        key="sweep_min_volume_end",
                    ),
                    "step": min_volume_cols[2].number_input(
                        "min volume step",
                        min_value=schema_value("min_volume", "step", 1000.0),
                        value=50000.0,
                        step=schema_value("min_volume", "step", 1000.0),
                        key="sweep_min_volume_step",
                    ),
                }

        with sweep_cols[1]:
            use_stop_loss = st.checkbox(
                "Sweep stop_loss_pct",
                value=False,
                key="sweep_stop_loss_enabled",
            )
            stop_loss_mode = st.radio(
                "stop_loss_pct mode",
                ["Single", "Range"],
                horizontal=True,
                key="sweep_stop_loss_mode",
            )
            stop_loss_cols = responsive_columns(3)

            if stop_loss_mode == "Single":
                sweep_spec["stop_loss_pct"] = {
                    "enabled": use_stop_loss,
                    "mode": "Single",
                    "single": stop_loss_cols[0].number_input(
                        "stop_loss_pct %",
                        min_value=schema_value("stop_loss_pct", "minimum", 0.0),
                        max_value=schema_value("stop_loss_pct", "maximum", 100.0),
                        value=4.0,
                        step=schema_value("stop_loss_pct", "step", 0.5),
                        key="sweep_stop_loss_single",
                    ),
                }
            else:
                sweep_spec["stop_loss_pct"] = {
                    "enabled": use_stop_loss,
                    "mode": "Range",
                    "start": stop_loss_cols[0].number_input(
                        "stop loss start %",
                        min_value=schema_value("stop_loss_pct", "minimum", 0.0),
                        max_value=schema_value("stop_loss_pct", "maximum", 100.0),
                        value=3.0,
                        step=schema_value("stop_loss_pct", "step", 0.5),
                        key="sweep_stop_loss_start",
                    ),
                    "end": stop_loss_cols[1].number_input(
                        "stop loss end %",
                        min_value=schema_value("stop_loss_pct", "minimum", 0.0),
                        max_value=schema_value("stop_loss_pct", "maximum", 100.0),
                        value=6.0,
                        step=schema_value("stop_loss_pct", "step", 0.5),
                        key="sweep_stop_loss_end",
                    ),
                    "step": stop_loss_cols[2].number_input(
                        "stop loss step %",
                        min_value=schema_value("stop_loss_pct", "step", 0.5),
                        max_value=schema_value("stop_loss_pct", "maximum", 100.0),
                        value=1.0,
                        step=schema_value("stop_loss_pct", "step", 0.5),
                        key="sweep_stop_loss_step",
                    ),
                }

            use_take_profit = st.checkbox(
                "Sweep take_profit_pct",
                value=False,
                key="sweep_take_profit_enabled",
            )
            take_profit_mode = st.radio(
                "take_profit_pct mode",
                ["Single", "Range"],
                horizontal=True,
                key="sweep_take_profit_mode",
            )
            take_profit_cols = responsive_columns(3)

            if take_profit_mode == "Single":
                sweep_spec["take_profit_pct"] = {
                    "enabled": use_take_profit,
                    "mode": "Single",
                    "single": take_profit_cols[0].number_input(
                        "take_profit_pct %",
                        min_value=schema_value("take_profit_pct", "minimum", 0.0),
                        max_value=schema_value("take_profit_pct", "maximum", 100.0),
                        value=8.0,
                        step=schema_value("take_profit_pct", "step", 0.5),
                        key="sweep_take_profit_single",
                    ),
                }
            else:
                sweep_spec["take_profit_pct"] = {
                    "enabled": use_take_profit,
                    "mode": "Range",
                    "start": take_profit_cols[0].number_input(
                        "take profit start %",
                        min_value=schema_value("take_profit_pct", "minimum", 0.0),
                        max_value=schema_value("take_profit_pct", "maximum", 100.0),
                        value=6.0,
                        step=schema_value("take_profit_pct", "step", 0.5),
                        key="sweep_take_profit_start",
                    ),
                    "end": take_profit_cols[1].number_input(
                        "take profit end %",
                        min_value=schema_value("take_profit_pct", "minimum", 0.0),
                        max_value=schema_value("take_profit_pct", "maximum", 100.0),
                        value=12.0,
                        step=schema_value("take_profit_pct", "step", 0.5),
                        key="sweep_take_profit_end",
                    ),
                    "step": take_profit_cols[2].number_input(
                        "take profit step %",
                        min_value=schema_value("take_profit_pct", "step", 0.5),
                        max_value=schema_value("take_profit_pct", "maximum", 100.0),
                        value=2.0,
                        step=schema_value("take_profit_pct", "step", 0.5),
                        key="sweep_take_profit_step",
                    ),
                }

            use_exit_mode = st.checkbox(
                "Sweep exit_mode",
                value=False,
                key="sweep_exit_mode_enabled",
            )
            exit_mode_values = st.multiselect(
                "exit_mode values",
                schema_value(
                    "exit_mode",
                    "options",
                    ["signals_and_stops", "stops_only", "signal_only"],
                ),
                default=[schema_value("exit_mode", "default", "signals_and_stops")],
                key="sweep_exit_mode_values",
            )
            sweep_spec["exit_mode"] = {
                "enabled": use_exit_mode,
                "values": exit_mode_values,
            }

        combinations = generate_parameter_combinations(sweep_spec)
        estimated_count = len(combinations)
        estimate_cols = responsive_columns(4)
        estimate_cols[0].metric("Estimated experiments", estimated_count)
        estimate_cols[1].metric("Completed count", 0)
        estimate_cols[2].metric("Safety limit", "500")
        estimate_cols[3].metric("Status", "Ready" if estimated_count else "No parameters")

        large_sweep = estimated_count > 500

        if large_sweep:
            st.warning(
                "This sweep exceeds 500 combinations. Confirm before running."
            )

        confirmed_large_sweep = st.checkbox(
            "I understand this sweep exceeds 500 experiments.",
            value=False,
            disabled=not large_sweep,
            key="confirm_large_sweep",
        )

        progress_bar = st.progress(0)
        current_placeholder = st.empty()
        completed_placeholder = st.empty()
        remaining_placeholder = st.empty()

        if st.button(
            "Start Sweep",
            disabled=(
                estimated_count == 0
                or (large_sweep and not confirmed_large_sweep)
                or run_from_saved_files is None
                or build_experiment_config is None
            ),
        ):
            created_ids = []

            def sweep_progress(update):
                created_ids.append(update["experiment"]["id"])
                progress_bar.progress(update["current"] / update["total"])
                current_placeholder.write(
                    f"Running {update['current']} / {update['total']}: "
                    f"{update['experiment']['name']}"
                )
                completed_placeholder.write(
                    f"Completed count: {update['current']}"
                )
                remaining_placeholder.write(
                    "Estimated remaining time: "
                    + format_seconds(update["remaining_seconds"])
                )

            created = run_parameter_sweep(
                live_config,
                sweep_spec,
                name_prefix=sweep_name.strip() or "Sweep",
                progress_callback=sweep_progress,
            )
            st.session_state["last_sweep_experiment_ids"] = [
                experiment["id"]
                for experiment in created
            ]
            st.success(f"Sweep complete. Created {len(created)} experiments.")
            experiments = load_experiments()

        ranked_experiments = [
            experiment
            for experiment in experiments
            if experiment.get("id") in st.session_state.get(
                "last_sweep_experiment_ids",
                [],
            )
        ]

        if not ranked_experiments:
            ranked_experiments = [
                experiment
                for experiment in experiments
                if experiment.get("status") in COMPARABLE_STATUSES
            ]

        st.subheader("Sweep Rankings")
        sort_metric = st.selectbox(
            "Sort all ranked results by",
            ["total_return", "sharpe_ratio", "max_drawdown", "profit_factor"],
            key="sweep_sort_metric",
        )
        sort_ascending = sort_metric == "max_drawdown"
        sorted_results = ranking_table(
            ranked_experiments,
            sort_metric,
            ascending=sort_ascending,
        )

        if sorted_results.empty:
            st.info("No sweep results available yet.")
        else:
            responsive_table(sorted_results, hide_index=True)

        rank_cols = responsive_columns(2)

        with rank_cols[0]:
            display_ranking(
                "Top 10 by Return",
                ranked_experiments,
                "total_return",
                "percent",
            )
            display_ranking(
                "Top 10 by Drawdown",
                ranked_experiments,
                "max_drawdown",
                "percent",
                ascending=True,
            )

        with rank_cols[1]:
            display_ranking(
                "Top 10 by Sharpe",
                ranked_experiments,
                "sharpe_ratio",
                "number",
            )
            display_ranking(
                "Top 10 by Profit Factor",
                ranked_experiments,
                "profit_factor",
                "number",
            )

if research_mode == "Validate Strategy":
    st.divider()
    st.subheader("Walk-Forward Testing")
    st.caption(
        "Walk-forward validation is informational only. It stores results inside "
        "research/experiments.json and does not change production trading."
    )

    tested_experiments = [
        experiment
        for experiment in experiments
        if experiment.get("status") in COMPARABLE_STATUSES
    ]

    if run_walk_forward_validation is None:
        st.info("Walk-forward engine is unavailable.")
    elif not tested_experiments:
        st.info("Run or create a Tested experiment before walk-forward validation.")
    else:
        wf_options = {
            experiment_label(experiment): experiment.get("id")
            for experiment in tested_experiments
        }
        wf_label = st.selectbox(
            "Experiment to validate",
            list(wf_options.keys()),
            key="walk_forward_experiment",
        )
        wf_experiment = experiment_by_id(experiments, wf_options[wf_label])
        wf_result = walk_forward_result(wf_experiment)
        wf_status = walk_forward_status(wf_experiment)

        wf_cols = responsive_columns(4)
        wf_cols[0].metric("Walk-Forward Status", wf_status)
        wf_cols[1].metric(
            "Date completed",
            wf_result.get("date_completed", "Not Run"),
        )
        wf_cols[2].metric(
            "Folds",
            len(wf_result.get("fold_results", [])),
        )
        wf_cols[3].metric(
            "Consistency",
            format_percent(
                wf_result.get("stability", {}).get("consistency_score", "Not available")
            ),
        )

        config_cols = responsive_columns(3)
        training_years = config_cols[0].number_input(
            "Training window (years)",
            min_value=1,
            max_value=10,
            value=3,
            step=1,
            key="wf_training_years",
        )
        testing_years = config_cols[1].number_input(
            "Testing window (years)",
            min_value=1,
            max_value=5,
            value=1,
            step=1,
            key="wf_testing_years",
        )
        rolling_mode = config_cols[2].toggle(
            "Rolling mode",
            value=True,
            key="wf_rolling_mode",
        )

        if st.button("Run Walk-Forward Validation"):
            wf_experiment["walk_forward"] = {
                "status": "Running",
                "date_completed": "",
                "summary": {},
            }
            save_experiments(experiments)

            with st.spinner("Running walk-forward validation..."):
                result = run_walk_forward_validation(
                    live_config,
                    wf_experiment,
                    training_years=training_years,
                    testing_years=testing_years,
                    rolling=rolling_mode,
                )

            wf_experiment["walk_forward"] = result
            save_experiments(experiments)
            st.success(f"Walk-forward validation {result['status'].upper()}.")
            wf_result = result
            wf_status = result["status"]

        if wf_result:
            st.subheader("Walk-Forward Summary")
            averages = wf_result.get("averages", {})
            stability = wf_result.get("stability", {})
            assessment = wf_result.get("assessment", {})

            summary_cols = responsive_columns(6)
            summary_cols[0].metric("Assessment", wf_status)
            summary_cols[1].metric(
                "Average Return",
                format_percent(stability.get("average_return", "Not available")),
            )
            summary_cols[2].metric(
                "Return Std Dev",
                format_percent(stability.get("return_std", "Not available")),
            )
            summary_cols[3].metric(
                "Sharpe Std Dev",
                format_number(stability.get("sharpe_std", "Not available")),
            )
            summary_cols[4].metric(
                "Best Fold",
                stability.get("best_fold", "Not available"),
            )
            summary_cols[5].metric(
                "Worst Fold",
                stability.get("worst_fold", "Not available"),
            )

            st.write("Reason")
            for reason in assessment.get("reasons", []):
                st.write(f"- {reason}")

            fold_table = walk_forward_fold_table(wf_result)

            st.subheader("Fold Results Table")
            display_walk_forward_table(fold_table)

            st.subheader("Equity Curve Per Fold")
            per_fold_curve = walk_forward_curve_frame(wf_result, per_fold=True)

            if per_fold_curve.empty:
                st.info("No per-fold equity curve available.")
            else:
                st.line_chart(per_fold_curve, width="stretch")

            st.subheader("Combined Equity Curve")
            combined_curve = walk_forward_curve_frame(wf_result, per_fold=False)

            if combined_curve.empty:
                st.info("No combined equity curve available.")
            else:
                st.line_chart(combined_curve, width="stretch")

            st.subheader("Metric Comparison Across Folds")
            metric_frame = metric_fold_frame(fold_table)

            if metric_frame.empty:
                st.info("No fold metric comparison available.")
            else:
                st.bar_chart(metric_frame, width="stretch")

            st.subheader("Performance Consistency Heatmap")

            if metric_frame.empty:
                st.info("No consistency heatmap available.")
            else:
                responsive_table(
                    metric_frame.style.background_gradient(cmap="RdYlGn", axis=0),
                )

            export_payload = json.dumps(wf_result, indent=2)
            st.download_button(
                "Export Summary",
                data=export_payload,
                file_name=(
                    wf_experiment.get("name", "experiment")
                    .replace(" ", "_")
                    .lower()
                    + "_walk_forward.json"
                ),
                mime="application/json",
            )
        else:
            st.info("Walk-forward status: Not Run.")

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
