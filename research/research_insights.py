import json
from datetime import datetime
from pathlib import Path

import pandas as pd


AUDIT_FILE = Path("trade_audit_trail.csv")
JOURNAL_FILE = Path("trade_journal_v3.csv")
EXPERIMENTS_FILE = Path("research/experiments.json")
INSIGHTS_FILE = Path("research/insights.json")


def _read_csv(path):
    path = Path(path)

    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _read_json(path, default):
    path = Path(path)

    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def _safe_float(value, default=0):
    try:
        value = float(value)
    except Exception:
        return default

    if pd.isna(value):
        return default

    return value


def _safe_percent(value):
    return f"{_safe_float(value):.2%}"


def _safe_number(value):
    return f"{_safe_float(value):,.2f}"


def _normalise_trades(audit, journal):
    if not audit.empty:
        trades = audit.copy()
        rename_map = {
            "symbol": "ticker",
            "open_time": "entry_date",
            "close_time": "exit_date",
            "holding_period": "holding_period",
            "pnl_pct": "return_pct",
            "pnl": "realised_pnl",
            "close_reason": "exit_reason",
            "entry_signal": "technical_score",
            "entry_value": "position_size",
            "entry_weight": "position_weight",
            "asset_type": "sector",
        }
        trades = trades.rename(
            columns={
                source: target
                for source, target in rename_map.items()
                if source in trades.columns
            }
        )
    else:
        trades = _completed_trades_from_journal(journal)

    if trades.empty:
        return trades

    if "ticker" not in trades.columns:
        trades["ticker"] = "Unknown"

    if "entry_date" in trades.columns:
        trades["entry_date"] = pd.to_datetime(
            trades["entry_date"],
            errors="coerce",
        )

    if "exit_date" in trades.columns:
        trades["exit_date"] = pd.to_datetime(
            trades["exit_date"],
            errors="coerce",
        )

    if "holding_period" in trades.columns:
        holding_delta = pd.to_timedelta(
            trades["holding_period"],
            errors="coerce",
        )
        trades["holding_days"] = holding_delta.dt.total_seconds() / 86400
    elif {"entry_date", "exit_date"}.issubset(trades.columns):
        trades["holding_days"] = (
            trades["exit_date"] - trades["entry_date"]
        ).dt.total_seconds() / 86400
    else:
        trades["holding_days"] = 0

    if "return_pct" not in trades.columns:
        trades["return_pct"] = 0

    if "realised_pnl" not in trades.columns:
        trades["realised_pnl"] = 0

    if "exit_reason" not in trades.columns:
        trades["exit_reason"] = "Unknown"

    for optional_column in [
        "technical_score",
        "position_size",
        "position_weight",
        "sector",
        "volatility",
        "atr",
        "market_direction",
        "drawdown",
    ]:
        if optional_column not in trades.columns:
            trades[optional_column] = pd.NA

    trades["return_pct"] = pd.to_numeric(
        trades["return_pct"],
        errors="coerce",
    ).fillna(0)
    trades["realised_pnl"] = pd.to_numeric(
        trades["realised_pnl"],
        errors="coerce",
    ).fillna(0)
    trades["holding_days"] = pd.to_numeric(
        trades["holding_days"],
        errors="coerce",
    ).fillna(0)
    trades["technical_score"] = pd.to_numeric(
        trades["technical_score"],
        errors="coerce",
    )
    trades["position_size"] = pd.to_numeric(
        trades["position_size"],
        errors="coerce",
    )
    trades["position_weight"] = pd.to_numeric(
        trades["position_weight"],
        errors="coerce",
    )
    trades["atr"] = pd.to_numeric(trades["atr"], errors="coerce")
    trades["volatility"] = pd.to_numeric(
        trades["volatility"],
        errors="coerce",
    )
    trades["drawdown"] = pd.to_numeric(trades["drawdown"], errors="coerce")
    trades["is_winner"] = trades["realised_pnl"] > 0
    trades["win_loss"] = trades["is_winner"].map({True: "Win", False: "Loss"})

    if "entry_date" in trades.columns:
        trades["entry_weekday"] = trades["entry_date"].dt.day_name().fillna("Unknown")
    else:
        trades["entry_weekday"] = "Unknown"

    trades["holding_bucket"] = pd.cut(
        trades["holding_days"],
        bins=[-0.01, 1, 3, 7, 14, 30, float("inf")],
        labels=["0-1d", "1-3d", "3-7d", "7-14d", "14-30d", "30d+"],
    ).astype(str)

    trades["technical_score_bucket"] = pd.cut(
        trades["technical_score"],
        bins=[-0.01, 1, 2, 3, 4, 5, float("inf")],
        labels=["0-1", "1-2", "2-3", "3-4", "4-5", "5+"],
    ).astype(str)
    trades.loc[trades["technical_score"].isna(), "technical_score_bucket"] = (
        "Unavailable"
    )

    return trades


def _completed_trades_from_journal(journal):
    if journal.empty or "action" not in journal.columns:
        return pd.DataFrame()

    rows = []
    open_positions = {}
    journal = journal.copy()

    if "date" in journal.columns:
        journal["date"] = pd.to_datetime(journal["date"], errors="coerce")

    for _, row in journal.sort_values("date").iterrows():
        ticker = row.get("ticker")
        action = str(row.get("action", "")).upper()

        if action == "BUY":
            open_positions[ticker] = row
        elif action == "SELL" and ticker in open_positions:
            entry = open_positions.pop(ticker)
            rows.append(
                {
                    "ticker": ticker,
                    "entry_date": entry.get("date"),
                    "exit_date": row.get("date"),
                    "return_pct": row.get("pnl_percent", 0),
                    "realised_pnl": row.get("pnl", 0),
                    "exit_reason": row.get("reason", "Unknown"),
                    "position_size": entry.get("value", 0),
                }
            )

    return pd.DataFrame(rows)


def _group_breakdown(trades, column):
    if trades.empty or column not in trades.columns:
        return pd.DataFrame()

    grouped = trades.groupby(column, dropna=False).agg(
        trades=("ticker", "count"),
        win_rate=("is_winner", "mean"),
        average_return=("return_pct", "mean"),
        average_pnl=("realised_pnl", "mean"),
        total_pnl=("realised_pnl", "sum"),
        average_holding_days=("holding_days", "mean"),
    )
    grouped = grouped.reset_index().sort_values(
        ["average_return", "total_pnl"],
        ascending=False,
    )
    return grouped


def _summary_metrics(trades, experiments):
    tested = [
        experiment
        for experiment in experiments
        if experiment.get("status") in {"Tested", "Candidate", "Production Ready"}
        and experiment.get("results", {}).get("summary")
    ]
    winners = trades[trades["is_winner"]] if not trades.empty else pd.DataFrame()

    return {
        "completed_trades": int(len(trades)),
        "winning_trades": int(len(winners)),
        "win_rate": float(trades["is_winner"].mean()) if not trades.empty else 0,
        "average_return": float(trades["return_pct"].mean())
        if not trades.empty
        else 0,
        "realised_pnl": float(trades["realised_pnl"].sum())
        if not trades.empty
        else 0,
        "tested_experiments": len(tested),
    }


def _winners_losers(trades):
    if trades.empty:
        return pd.DataFrame()

    rows = []

    for label, subset in [
        ("Winners", trades[trades["is_winner"]]),
        ("Losers", trades[~trades["is_winner"]]),
    ]:
        if subset.empty:
            rows.append(
                {
                    "Group": label,
                    "trades": 0,
                    "average_technical_score": pd.NA,
                    "average_holding_days": pd.NA,
                    "average_position_size": pd.NA,
                    "average_atr": pd.NA,
                    "average_volatility": pd.NA,
                    "average_return": pd.NA,
                    "largest_winner": pd.NA,
                    "largest_loser": pd.NA,
                    "average_drawdown": pd.NA,
                    "average_gain": pd.NA,
                    "average_loss": pd.NA,
                }
            )
            continue

        gains = subset[subset["realised_pnl"] > 0]["realised_pnl"]
        losses = subset[subset["realised_pnl"] < 0]["realised_pnl"]
        rows.append(
            {
                "Group": label,
                "trades": int(len(subset)),
                "average_technical_score": subset["technical_score"].mean(),
                "average_holding_days": subset["holding_days"].mean(),
                "average_position_size": subset["position_size"].mean(),
                "average_atr": subset["atr"].mean(),
                "average_volatility": subset["volatility"].mean(),
                "average_return": subset["return_pct"].mean(),
                "largest_winner": subset["realised_pnl"].max(),
                "largest_loser": subset["realised_pnl"].min(),
                "average_drawdown": subset["drawdown"].mean(),
                "average_gain": gains.mean() if not gains.empty else 0,
                "average_loss": losses.mean() if not losses.empty else 0,
            }
        )

    return pd.DataFrame(rows)


def _insight_card(title, observation, supporting_metric, sample_size):
    return {
        "title": title,
        "observation": observation,
        "supporting_metric": supporting_metric,
        "sample_size": int(sample_size),
    }


def _trade_insights(trades, breakdowns):
    cards = []

    if trades.empty:
        return cards

    winners = trades[trades["is_winner"]]
    losers = trades[~trades["is_winner"]]

    if not winners.empty and not losers.empty:
        winner_hold = winners["holding_days"].mean()
        loser_hold = losers["holding_days"].mean()
        winner_return = winners["return_pct"].mean()
        loser_return = losers["return_pct"].mean()
        cards.append(
            _insight_card(
                "Winners vs losers average holding period",
                (
                    f"Winners averaged {winner_hold:.2f} days, while losers "
                    f"averaged {loser_hold:.2f} days."
                ),
                f"Difference: {winner_hold - loser_hold:.2f} days",
                len(trades),
            )
        )
        cards.append(
            _insight_card(
                "Winners vs losers average return",
                (
                    f"Winners averaged {_safe_percent(winner_return)}, while "
                    f"losers averaged {_safe_percent(loser_return)}."
                ),
                f"Spread: {_safe_percent(winner_return - loser_return)}",
                len(trades),
            )
        )

    for title, key in [
        ("Return by exit reason", "exit_reason"),
        ("Return by holding period bucket", "holding_bucket"),
        ("Return by ticker", "ticker"),
        ("Return by weekday of entry", "entry_weekday"),
        ("Win rate by technical score bucket", "technical_score_bucket"),
    ]:
        table = breakdowns.get(key, pd.DataFrame())

        if table.empty:
            continue

        best = table.iloc[0]
        worst = table.sort_values("average_return").iloc[0]
        cards.append(
            _insight_card(
                title,
                (
                    f"Best group: {best[key]} with "
                    f"{_safe_percent(best['average_return'])}. Worst group: "
                    f"{worst[key]} with {_safe_percent(worst['average_return'])}."
                ),
                f"Groups analysed: {len(table)}",
                int(table["trades"].sum()),
            )
        )

    return cards


def _meaningful_sample(sample_size):
    return sample_size >= 5


def _pattern_confidence(sample_size, effect_size):
    if sample_size >= 30 and abs(effect_size) >= 0.03:
        return "High"

    if sample_size >= 10 and abs(effect_size) >= 0.015:
        return "Medium"

    return "Low"


def _numeric_pattern(trades, column, label):
    if trades.empty or column not in trades.columns:
        return None

    usable = trades.dropna(subset=[column])

    if len(usable) < 5:
        return None

    winners = usable[usable["is_winner"]]
    losers = usable[~usable["is_winner"]]

    if len(winners) < 2 or len(losers) < 2:
        return None

    winner_average = winners[column].mean()
    loser_average = losers[column].mean()
    effect = winner_average - loser_average

    if pd.isna(effect) or abs(effect) == 0:
        return None

    return {
        "title": f"{label} differs between winners and losers",
        "pattern": (
            f"Winning trades averaged {_safe_number(winner_average)}; "
            f"losing trades averaged {_safe_number(loser_average)}."
        ),
        "evidence": f"Difference: {_safe_number(effect)}",
        "sample_size": int(len(usable)),
        "confidence": _pattern_confidence(len(usable), effect),
    }


def _group_pattern(table, group_column, label):
    if table is None or table.empty or group_column not in table.columns:
        return None

    usable = table[table["trades"] >= 2].copy()

    if len(usable) < 2 or usable["trades"].sum() < 5:
        return None

    best = usable.sort_values("average_return", ascending=False).iloc[0]
    worst = usable.sort_values("average_return", ascending=True).iloc[0]
    spread = _safe_float(best["average_return"]) - _safe_float(
        worst["average_return"]
    )

    if abs(spread) < 0.005:
        return None

    return {
        "title": f"{label} shows return dispersion",
        "pattern": (
            f"Best group was {best[group_column]} at "
            f"{_safe_percent(best['average_return'])}; worst group was "
            f"{worst[group_column]} at {_safe_percent(worst['average_return'])}."
        ),
        "evidence": f"Return spread: {_safe_percent(spread)}",
        "sample_size": int(usable["trades"].sum()),
        "confidence": _pattern_confidence(int(usable["trades"].sum()), spread),
    }


def _detect_patterns(trades, breakdowns):
    patterns = []

    for column, label in [
        ("technical_score", "Technical score"),
        ("holding_days", "Holding period"),
        ("position_size", "Position size"),
        ("atr", "ATR"),
        ("volatility", "Volatility"),
    ]:
        pattern = _numeric_pattern(trades, column, label)

        if pattern:
            patterns.append(pattern)

    for key, label in [
        ("sector", "Sector"),
        ("exit_reason", "Exit reason"),
        ("holding_bucket", "Holding period bucket"),
        ("entry_weekday", "Entry weekday"),
        ("ticker", "Ticker"),
        ("market_direction", "Market direction"),
    ]:
        pattern = _group_pattern(breakdowns.get(key, pd.DataFrame()), key, label)

        if pattern:
            patterns.append(pattern)

    return patterns


def _experiment_rows(experiments):
    rows = []

    for experiment in experiments:
        summary = experiment.get("results", {}).get("summary", {})

        if not summary:
            continue

        row = {
            "name": experiment.get("name", "Untitled"),
            "status": experiment.get("status", "Draft"),
            "total_return": summary.get("total_return"),
            "sharpe_ratio": summary.get("sharpe_ratio"),
            "max_drawdown": summary.get("max_drawdown"),
            "profit_factor": summary.get("profit_factor"),
            "completed_trades": summary.get("completed_trades"),
        }
        row.update(experiment.get("parameters", {}))
        rows.append(row)

    return pd.DataFrame(rows)


def _experiment_patterns(experiment_df):
    if experiment_df.empty:
        return {
            "best_by_return": pd.DataFrame(),
            "best_by_sharpe": pd.DataFrame(),
            "best_by_drawdown": pd.DataFrame(),
            "repeated_top_parameters": pd.DataFrame(),
            "poor_parameter_values": pd.DataFrame(),
            "common_successful_combinations": pd.DataFrame(),
            "common_unsuccessful_combinations": pd.DataFrame(),
        }

    df = experiment_df.copy()

    for column in [
        "total_return",
        "sharpe_ratio",
        "max_drawdown",
        "profit_factor",
        "completed_trades",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    best_by_return = df.sort_values("total_return", ascending=False).head(10)
    best_by_sharpe = df.sort_values("sharpe_ratio", ascending=False).head(10)
    best_by_drawdown = df.sort_values("max_drawdown", ascending=False).head(10)
    cutoff = max(1, int(len(df) * 0.25))
    top = df.sort_values("total_return", ascending=False).head(cutoff)
    bottom = df.sort_values("total_return", ascending=True).head(cutoff)
    parameter_columns = [
        column
        for column in df.columns
        if column
        not in {
            "name",
            "status",
            "total_return",
            "sharpe_ratio",
            "max_drawdown",
            "profit_factor",
            "completed_trades",
        }
    ]

    repeated_rows = []
    poor_rows = []

    for column in parameter_columns:
        top_counts = top[column].value_counts(dropna=True)
        bottom_counts = bottom[column].value_counts(dropna=True)

        if not top_counts.empty:
            repeated_rows.append(
                {
                    "parameter": column,
                    "value": top_counts.index[0],
                    "top_experiment_count": int(top_counts.iloc[0]),
                    "top_share": float(top_counts.iloc[0] / len(top)),
                }
            )

        if not bottom_counts.empty:
            poor_rows.append(
                {
                    "parameter": column,
                    "value": bottom_counts.index[0],
                    "poor_experiment_count": int(bottom_counts.iloc[0]),
                    "poor_share": float(bottom_counts.iloc[0] / len(bottom)),
                }
            )

    def combination_rows(source, label):
        rows = []

        if source.empty or not parameter_columns:
            return rows

        signatures = source[parameter_columns].astype(str).agg(
            " | ".join,
            axis=1,
        )
        counts = signatures.value_counts()

        for signature, count in counts.head(10).items():
            rows.append(
                {
                    "combination": signature,
                    "count": int(count),
                    "share": float(count / len(source)),
                    "group": label,
                }
            )

        return rows

    return {
        "best_by_return": best_by_return,
        "best_by_sharpe": best_by_sharpe,
        "best_by_drawdown": best_by_drawdown,
        "repeated_top_parameters": pd.DataFrame(repeated_rows),
        "poor_parameter_values": pd.DataFrame(poor_rows),
        "common_successful_combinations": pd.DataFrame(
            combination_rows(top, "Top performers")
        ),
        "common_unsuccessful_combinations": pd.DataFrame(
            combination_rows(bottom, "Weak performers")
        ),
    }


def _confidence(sample_size, effect_size):
    if sample_size >= 30 and abs(effect_size) >= 0.03:
        return "High"

    if sample_size >= 10 and abs(effect_size) >= 0.015:
        return "Medium"

    return "Low"


def _suggestions(trades, breakdowns, experiment_patterns):
    suggestions = []

    def suggestion(title, why, evidence, sample_size, suggested_experiment, confidence):
        return {
            "title": title,
            "why": why,
            "evidence": evidence,
            "sample_size": int(sample_size),
            "suggested_experiment": suggested_experiment,
            "confidence": confidence,
            "reason": why,
            "supporting_metric": evidence,
            "suggested_experiment_parameter_range": suggested_experiment,
        }

    if not trades.empty:
        score_table = breakdowns.get("technical_score_bucket", pd.DataFrame())

        if (
            not score_table.empty
            and len(score_table) > 1
            and "Unavailable" not in set(score_table["technical_score_bucket"])
        ):
            best = score_table.iloc[0]
            overall = trades["return_pct"].mean()
            effect = _safe_float(best["average_return"]) - overall
            suggestions.append(
                suggestion(
                    "Raise Technical Score",
                    (
                        "Completed trades in stronger technical score buckets "
                        "showed better average returns than the overall sample."
                    ),
                    (
                        f"Best bucket {best['technical_score_bucket']}: "
                        f"{_safe_percent(best['average_return'])}"
                    ),
                    int(best["trades"]),
                    "technical_score_threshold: 3 to 5",
                    _confidence(len(trades), effect),
                )
            )

        holding_table = breakdowns.get("holding_bucket", pd.DataFrame())

        if not holding_table.empty:
            worst = holding_table.sort_values("average_return").iloc[0]
            suggestions.append(
                suggestion(
                    "Review Exit Logic",
                    (
                        "Holding-period buckets show uneven returns. This is a "
                        "pattern worth investigating, not a production change."
                    ),
                    (
                        f"Weakest bucket {worst['holding_bucket']}: "
                        f"{_safe_percent(worst['average_return'])}"
                    ),
                    int(worst["trades"]),
                    "exit_mode: signals_and_stops, stops_only, signal_only",
                    _confidence(
                        int(worst["trades"]),
                        _safe_float(worst["average_return"]),
                    ),
                )
            )

        ticker_table = breakdowns.get("ticker", pd.DataFrame())

        if not ticker_table.empty:
            worst_ticker = ticker_table.sort_values("average_return").iloc[0]
            suggestions.append(
                suggestion(
                    "Test Excluding Weak Groups",
                    (
                        "One or more tickers have materially weaker completed "
                        "trade outcomes."
                    ),
                    (
                        f"{worst_ticker['ticker']}: "
                        f"{_safe_percent(worst_ticker['average_return'])}"
                    ),
                    int(worst_ticker["trades"]),
                    "Create a Research Lab experiment excluding weak groups.",
                    _confidence(
                        int(worst_ticker["trades"]),
                        _safe_float(worst_ticker["average_return"]),
                    ),
                )
            )

        if "position_size" in trades.columns and trades["position_size"].notna().any():
            median_size = trades["position_size"].median()
            high_size = trades[trades["position_size"] > median_size]
            low_size = trades[trades["position_size"] <= median_size]

            if len(high_size) >= 2 and len(low_size) >= 2:
                effect = high_size["return_pct"].mean() - low_size["return_pct"].mean()
                if effect < 0:
                    suggestions.append(
                        suggestion(
                            "Test Smaller Position Size",
                            (
                                "Trades above the median position size produced "
                                "weaker average returns than smaller trades."
                            ),
                            (
                                "High-size average return "
                                f"{_safe_percent(high_size['return_pct'].mean())}; "
                                "low-size average return "
                                f"{_safe_percent(low_size['return_pct'].mean())}."
                            ),
                            len(trades),
                            "position_size: below current median, tested in sweep",
                            _confidence(len(trades), effect),
                        )
                    )

    repeated = experiment_patterns.get("repeated_top_parameters", pd.DataFrame())
    poor = experiment_patterns.get("poor_parameter_values", pd.DataFrame())

    if not repeated.empty:
        row = repeated.iloc[0]
        suggestions.append(
            suggestion(
                f"Retest strong {row['parameter']} values",
                (
                    "A parameter value appears repeatedly among top-performing "
                    "tested experiments."
                ),
                (
                    f"{row['value']} appeared in {_safe_percent(row['top_share'])} "
                    "of top experiments."
                ),
                int(row["top_experiment_count"]),
                f"{row['parameter']}: near {row['value']}",
                _confidence(
                    int(row["top_experiment_count"]),
                    _safe_float(row["top_share"]),
                ),
            )
        )

    if not poor.empty:
        row = poor.iloc[0]
        suggestions.append(
            suggestion(
                f"Stress test weak {row['parameter']} values",
                (
                    "A parameter value appears repeatedly among weaker tested "
                    "experiments."
                ),
                (
                    f"{row['value']} appeared in {_safe_percent(row['poor_share'])} "
                    "of weaker experiments."
                ),
                int(row["poor_experiment_count"]),
                f"Avoid or bracket {row['parameter']}={row['value']} in sweeps.",
                _confidence(
                    int(row["poor_experiment_count"]),
                    _safe_float(row["poor_share"]),
                ),
            )
        )

    return suggestions


def _serialise_table(df):
    if df is None or df.empty:
        return []

    result = df.copy()

    for column in result.columns:
        if pd.api.types.is_datetime64_any_dtype(result[column]):
            result[column] = result[column].astype(str)

    return result.where(pd.notna(result), None).to_dict("records")


def generate_research_insights(
    audit_file=AUDIT_FILE,
    journal_file=JOURNAL_FILE,
    experiments_file=EXPERIMENTS_FILE,
):
    audit = _read_csv(audit_file)
    journal = _read_csv(journal_file)
    experiments = _read_json(experiments_file, [])
    trades = _normalise_trades(audit, journal)
    breakdowns = {
        "ticker": _group_breakdown(trades, "ticker"),
        "exit_reason": _group_breakdown(trades, "exit_reason"),
        "holding_bucket": _group_breakdown(trades, "holding_bucket"),
        "entry_weekday": _group_breakdown(trades, "entry_weekday"),
        "sector": _group_breakdown(trades, "sector"),
        "market_direction": _group_breakdown(trades, "market_direction"),
        "technical_score_bucket": _group_breakdown(
            trades,
            "technical_score_bucket",
        ),
    }
    experiment_df = _experiment_rows(experiments)
    experiment_patterns = _experiment_patterns(experiment_df)
    cards = _trade_insights(trades, breakdowns)
    detected_patterns = _detect_patterns(trades, breakdowns)
    suggestions = _suggestions(trades, breakdowns, experiment_patterns)

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": _summary_metrics(trades, experiments),
        "trades": trades,
        "insight_cards": cards,
        "winners_vs_losers": _winners_losers(trades),
        "breakdowns": breakdowns,
        "patterns": detected_patterns,
        "experiment_table": experiment_df,
        "experiment_patterns": experiment_patterns,
        "suggestions": suggestions,
        "data_availability": {
            "audit_rows": len(audit),
            "journal_rows": len(journal),
            "normalised_completed_trades": len(trades),
            "experiments": len(experiments),
            "tested_experiments": len(experiment_df),
            "technical_score_available": (
                not trades.empty
                and "technical_score" in trades.columns
                and pd.to_numeric(
                    trades["technical_score"],
                    errors="coerce",
                ).notna().any()
            ),
        },
    }


def save_insights(insights, path=INSIGHTS_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialised = {
        "generated_at": insights["generated_at"],
        "summary": insights["summary"],
        "trades": _serialise_table(insights["trades"]),
        "insight_cards": insights["insight_cards"],
        "winners_vs_losers": _serialise_table(insights["winners_vs_losers"]),
        "breakdowns": {
            key: _serialise_table(value)
            for key, value in insights["breakdowns"].items()
        },
        "patterns": insights["patterns"],
        "experiment_table": _serialise_table(insights["experiment_table"]),
        "experiment_patterns": {
            key: _serialise_table(value)
            for key, value in insights["experiment_patterns"].items()
        },
        "suggestions": insights["suggestions"],
        "data_availability": insights["data_availability"],
    }

    with path.open("w", encoding="utf-8") as file:
        json.dump(serialised, file, indent=2)

    return path
