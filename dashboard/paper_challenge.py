"""Read-only validation and analytics for paper-challenge presentation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


RECONCILIATION_TOLERANCE = 0.01
MALFORMED_OBSERVATION_STATUSES = frozenset({"ACTIVE", "CLEARED", "QUARANTINED", "UNRESOLVED"})
KNOWN_LEGACY_MISSING_VALUATIONS = frozenset({"2026-07-02 13:21:44"})


@dataclass(frozen=True)
class MalformedEquityObservation:
    instrument: str
    observation_type: str
    source: str
    source_record_id: str
    timestamp: str
    raw_fields: tuple[tuple[str, str], ...]
    normalized_fields: tuple[tuple[str, str], ...]
    failed_rules: tuple[str, ...]
    failure_reason: str
    exception_type: str | None
    classification: str
    first_seen: str
    last_seen: str
    occurrence_count: int
    status: str
    recommended_action: str


@dataclass(frozen=True)
class PaperChallengeSeries:
    data: pd.DataFrame
    current_day: int
    completed: bool
    malformed_observations: int
    incomplete_valuations: int
    reconciliation_error: str | None = None
    malformed_details: tuple[MalformedEquityObservation, ...] = ()


def _safe_text(value):
    if value is None or pd.isna(value):
        return "Missing"
    return str(value)[:160]


def _malformed_details(working, valid, *, source):
    details = []
    for index, row in working.loc[~valid].iterrows():
        rules = []
        if pd.isna(row["timestamp"]):
            rules.append("timestamp must be parseable")
        if pd.isna(row["total_equity"]) or not np.isfinite(row["total_equity"]):
            rules.append("portfolio_value must be finite")
        elif row["total_equity"] <= 0:
            rules.append("portfolio_value must be positive")
        timestamp = _safe_text(row.get("date"))
        legacy_nan_valuation = (
            rules == ["portfolio_value must be finite"]
            and pd.notna(row["timestamp"])
            and pd.isna(pd.to_numeric(row.get("unrealised_pnl"), errors="coerce"))
            and "paper_30_day_tracker" in str(source)
            and timestamp in KNOWN_LEGACY_MISSING_VALUATIONS
        )
        classification = "STALE_LEGACY_RECORD" if legacy_nan_valuation else "SOURCE_DATA_INVALID"
        action = (
            "Keep excluded; retain the historical row as evidence. Current writers already reject incomplete valuations."
            if legacy_nan_valuation else
            "Keep excluded and inspect the named source writer before retrying or quarantining the record."
        )
        details.append(MalformedEquityObservation(
            "Not recorded", "EQUITY", source, f"row-{int(index) + 2}", timestamp,
            (("date", _safe_text(row.get("date"))), ("portfolio_value", _safe_text(row.get("portfolio_value")))),
            (("timestamp", _safe_text(row.get("timestamp"))), ("total_equity", _safe_text(row.get("total_equity")))),
            tuple(rules), "; ".join(rules), None, classification, timestamp, timestamp, 1,
            "ACTIVE", action,
        ))
    return tuple(details)


@dataclass(frozen=True)
class RealisedPnlSeries:
    data: pd.DataFrame
    event_count: int
    malformed_events: int
    reconciliation_error: str | None = None


@dataclass(frozen=True)
class AttributionResult:
    data: pd.DataFrame
    beginning_date: pd.Timestamp | None
    ending_date: pd.Timestamp | None
    equity_change: float | None
    status: str
    message: str


def build_paper_challenge_series(
    tracker: pd.DataFrame,
    initial_capital: float,
    challenge_days: int,
    *,
    today=None,
    displayed_current_balance=None,
    source="paper_30_day_tracker.csv",
) -> PaperChallengeSeries:
    columns = [
        "timestamp", "date", "challenge_day", "challenge_day_label", "cash_balance",
        "open_market_value", "total_equity", "portfolio_value", "return_from_start_pct",
        "return_pct", "running_peak", "drawdown_pct", "is_recorded", "recorded_run",
        "recorded_point_value",
    ]
    if tracker is None or tracker.empty or "date" not in tracker or "portfolio_value" not in tracker:
        return PaperChallengeSeries(pd.DataFrame(columns=columns), 0, False, 0, 0)
    if challenge_days <= 0:
        raise ValueError("Challenge duration must be positive")
    starting = pd.to_numeric(initial_capital, errors="coerce")
    if pd.isna(starting) or not np.isfinite(float(starting)) or float(starting) <= 0:
        raise ValueError("Challenge starting balance must be finite and positive")

    working = tracker.copy(deep=True).reset_index(drop=True)
    working["_source_order"] = np.arange(len(working))
    working["timestamp"] = pd.to_datetime(working["date"], errors="coerce")
    working["total_equity"] = pd.to_numeric(working["portfolio_value"], errors="coerce")
    working["cash_balance"] = pd.to_numeric(
        working["cash"] if "cash" in working else pd.Series(np.nan, index=working.index),
        errors="coerce",
    )
    valid = (
        working["timestamp"].notna()
        & np.isfinite(working["total_equity"])
        & working["total_equity"].gt(0)
    )
    malformed = int((~valid).sum())
    malformed_details = _malformed_details(working, valid, source=source)
    working = working.loc[valid].copy()
    if working.empty:
        return PaperChallengeSeries(pd.DataFrame(columns=columns), 0, False, malformed, 0,
                                    malformed_details=malformed_details)
    working["date"] = working["timestamp"].dt.normalize()
    working = working.sort_values(["timestamp", "_source_order"], kind="stable")
    daily = working.groupby("date", sort=True, as_index=False).tail(1).copy()
    daily = daily.sort_values("timestamp", kind="stable")

    first_recorded = daily["date"].iloc[0]
    baseline_date = first_recorded - pd.Timedelta(days=1)
    reference = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    elapsed = max(int((reference - baseline_date).days), 0)
    current_day = min(elapsed, challenge_days)
    daily["challenge_day"] = (daily["date"] - baseline_date).dt.days
    daily = daily[daily["challenge_day"].between(1, challenge_days)].copy()

    baseline = pd.DataFrame([{
        "timestamp": baseline_date, "date": baseline_date, "challenge_day": 0,
        "cash_balance": np.nan, "total_equity": float(starting), "is_recorded": False,
    }])
    daily["is_recorded"] = True
    series = pd.concat([baseline, daily], ignore_index=True, sort=False)
    series = series.sort_values(["challenge_day", "timestamp"], kind="stable").reset_index(drop=True)
    series["open_market_value"] = series["total_equity"] - series["cash_balance"]
    incomplete = int(series.loc[series["is_recorded"], "cash_balance"].isna().sum())
    series["portfolio_value"] = series["total_equity"]
    series["challenge_day_label"] = series["challenge_day"].map(lambda value: f"Day {int(value)}")
    series["return_from_start_pct"] = (series["total_equity"] / float(starting) - 1) * 100
    series["return_pct"] = series["return_from_start_pct"]
    series["running_peak"] = series["total_equity"].cummax()
    series["drawdown_pct"] = (series["total_equity"] / series["running_peak"] - 1) * 100
    series["recorded_point_value"] = series["total_equity"].where(series["is_recorded"])
    series["recorded_run"] = 1

    mismatch = None
    displayed = pd.to_numeric(displayed_current_balance, errors="coerce")
    if pd.notna(displayed) and abs(float(series.iloc[-1]["total_equity"]) - float(displayed)) > RECONCILIATION_TOLERANCE:
        mismatch = (
            f"Latest equity {float(series.iloc[-1]['total_equity']):.2f} does not reconcile "
            f"to displayed balance {float(displayed):.2f}."
        )
    return PaperChallengeSeries(
        series[columns].copy(deep=True), current_day, elapsed >= challenge_days,
        malformed, incomplete, mismatch, malformed_details,
    )


def build_realised_pnl_series(
    audit: pd.DataFrame,
    displayed_realised_pnl,
    *,
    starting_balance,
    challenge_start_date,
    display_end_date,
    through=None,
    tolerance: float = RECONCILIATION_TOLERANCE,
) -> RealisedPnlSeries:
    columns = [
        "date", "event_id", "daily_realised_pnl", "cumulative_realised_pnl",
        "realised_equity", "has_realisation_event", "is_baseline", "display_state",
    ]
    starting = pd.to_numeric(starting_balance, errors="coerce")
    start_date = pd.to_datetime(challenge_start_date, errors="coerce")
    end_date = pd.to_datetime(display_end_date, errors="coerce")
    if pd.isna(starting) or not np.isfinite(float(starting)) or float(starting) <= 0:
        return RealisedPnlSeries(
            pd.DataFrame(columns=columns), 0, 0,
            "Realised equity requires a finite positive challenge starting balance.",
        )
    if pd.isna(start_date):
        return RealisedPnlSeries(
            pd.DataFrame(columns=columns), 0, 0,
            "Realised equity requires a valid challenge start date.",
        )
    start_date = pd.Timestamp(start_date).normalize()
    if pd.isna(end_date) or pd.Timestamp(end_date).normalize() < start_date:
        return RealisedPnlSeries(
            pd.DataFrame(columns=columns), 0, 0,
            "Realised equity requires a valid display end date on or after the challenge start.",
        )
    end_date = pd.Timestamp(end_date).normalize()
    if audit is None or audit.empty or "close_time" not in audit or "pnl" not in audit:
        headline = pd.to_numeric(displayed_realised_pnl, errors="coerce")
        mismatch = (
            f"No realised events are available but the headline is {float(headline):.2f}."
            if pd.notna(headline) and abs(float(headline)) > tolerance
            else None
        )
        return RealisedPnlSeries(pd.DataFrame(columns=columns), 0, 0, mismatch)
    events = audit.copy(deep=True).reset_index(drop=True)
    events["_source_order"] = np.arange(len(events))
    events["timestamp"] = pd.to_datetime(events["close_time"], errors="coerce")
    events["realised_pnl_delta"] = pd.to_numeric(events["pnl"], errors="coerce")
    if through is not None:
        events = events[events["timestamp"].le(pd.Timestamp(through))].copy()
    exit_ids = events.get("exit_event_id", pd.Series("", index=events.index)).fillna("").astype(str).str.strip()
    entry_ids = events.get("entry_event_id", pd.Series("", index=events.index)).fillna("").astype(str).str.strip()
    valid = (
        events["timestamp"].notna()
        & np.isfinite(events["realised_pnl_delta"])
        & exit_ids.ne("")
        & entry_ids.ne("")
    )
    malformed = int((~valid).sum())
    events = events.loc[valid].copy()
    if events.empty:
        headline = pd.to_numeric(displayed_realised_pnl, errors="coerce")
        mismatch = (
            f"No realised events are available but the headline is {float(headline):.2f}."
            if pd.notna(headline) and abs(float(headline)) > tolerance
            else None
        )
        return RealisedPnlSeries(pd.DataFrame(columns=columns), 0, malformed, mismatch)
    events["event_id"] = exit_ids.loc[events.index]
    events["_lot_key"] = events["event_id"] + "|" + entry_ids.loc[events.index]
    events = events.sort_values(["timestamp", "_source_order"], kind="stable").drop_duplicates("_lot_key", keep="first")
    events = events.groupby(["timestamp", "event_id"], sort=True, as_index=False)["realised_pnl_delta"].sum()
    events = events.sort_values(["timestamp", "event_id"], kind="stable").reset_index(drop=True)
    event_count = len(events)
    events["date"] = events["timestamp"].dt.normalize()
    daily = events.groupby("date", sort=True, as_index=False).agg(
        daily_realised_pnl=("realised_pnl_delta", "sum"),
        event_id=("event_id", lambda values: " | ".join(values.astype(str))),
    )
    daily = daily.sort_values("date", kind="stable").reset_index(drop=True)
    if not daily.empty and daily.iloc[0]["date"] <= start_date:
        return RealisedPnlSeries(
            pd.DataFrame(columns=columns), event_count, malformed,
            "A realised event is not later than the challenge baseline date.",
        )
    if not daily.empty and daily.iloc[-1]["date"] > end_date:
        return RealisedPnlSeries(
            pd.DataFrame(columns=columns), event_count, malformed,
            "A realised event falls after the requested display date range.",
        )
    calendar = pd.DataFrame({"date": pd.date_range(start_date, end_date, freq="D")})
    result = calendar.merge(daily, on="date", how="left", validate="one_to_one")
    result["has_realisation_event"] = result["event_id"].notna()
    result["event_id"] = result["event_id"].fillna("")
    result["daily_realised_pnl"] = result["daily_realised_pnl"].fillna(0.0)
    result["cumulative_realised_pnl"] = result["daily_realised_pnl"].cumsum()
    result["realised_equity"] = float(starting) + result["cumulative_realised_pnl"]
    result["is_baseline"] = result["date"].eq(start_date)
    result["display_state"] = np.select(
        [result["is_baseline"], result["has_realisation_event"]],
        ["Challenge baseline", "Realisation date"],
        default="Carried forward",
    )
    result = result[columns]
    mismatch = None
    headline = pd.to_numeric(displayed_realised_pnl, errors="coerce")
    if pd.notna(headline) and abs(float(result.iloc[-1]["cumulative_realised_pnl"]) - float(headline)) > tolerance:
        mismatch = (
            f"Realised events total {float(result.iloc[-1]['cumulative_realised_pnl']):.2f} "
            f"but the headline is {float(headline):.2f}."
        )
    return RealisedPnlSeries(result.copy(deep=True), event_count, malformed, mismatch)


def build_day_over_day_attribution(
    holdings_history: pd.DataFrame,
    tracker: pd.DataFrame,
    *,
    tolerance: float = RECONCILIATION_TOLERANCE,
) -> AttributionResult:
    empty = pd.DataFrame(columns=["component", "beginning_value", "ending_value", "attribution"])
    required_holdings = {"date", "ticker", "market_value"}
    required_tracker = {"date", "portfolio_value", "cash"}
    if holdings_history is None or holdings_history.empty:
        return AttributionResult(empty, None, None, None, "unavailable", "No canonical holdings history is available.")
    if not required_holdings.issubset(holdings_history.columns) or tracker is None or not required_tracker.issubset(tracker.columns):
        return AttributionResult(empty, None, None, None, "malformed", "Holdings or account history is missing required valuation fields.")
    holdings = holdings_history.copy(deep=True)
    holdings["date"] = pd.to_datetime(holdings["date"], errors="coerce").dt.normalize()
    holdings["market_value"] = pd.to_numeric(holdings["market_value"], errors="coerce")
    holdings["ticker"] = holdings["ticker"].fillna("").astype(str).str.strip().str.upper()
    holdings = holdings.dropna(subset=["date", "market_value"])
    holdings = holdings[holdings["ticker"].ne("")]
    account = tracker.copy(deep=True).reset_index(drop=True)
    account["timestamp"] = pd.to_datetime(account["date"], errors="coerce")
    account["date"] = account["timestamp"].dt.normalize()
    for column in ("portfolio_value", "cash"):
        account[column] = pd.to_numeric(account[column], errors="coerce")
    account = account.dropna(subset=["timestamp", "date", "portfolio_value", "cash"])
    account = account.sort_values("timestamp", kind="stable").groupby("date", as_index=False).tail(1)
    common = sorted(set(holdings["date"]) & set(account["date"]))
    if len(common) < 2:
        return AttributionResult(empty, None, None, None, "unavailable", "Attribution begins after two comparable holdings and account snapshots exist.")
    beginning, ending = common[-2], common[-1]
    start = holdings[holdings["date"].eq(beginning)].groupby("ticker")["market_value"].sum()
    finish = holdings[holdings["date"].eq(ending)].groupby("ticker")["market_value"].sum()
    tickers = sorted(set(start.index) | set(finish.index))
    rows = [{
        "component": ticker, "beginning_value": float(start.get(ticker, 0.0)),
        "ending_value": float(finish.get(ticker, 0.0)),
        "attribution": float(finish.get(ticker, 0.0) - start.get(ticker, 0.0)),
    } for ticker in tickers]
    start_account = account[account["date"].eq(beginning)].iloc[-1]
    end_account = account[account["date"].eq(ending)].iloc[-1]
    rows.append({
        "component": "Cash / flows and realised activity",
        "beginning_value": float(start_account["cash"]), "ending_value": float(end_account["cash"]),
        "attribution": float(end_account["cash"] - start_account["cash"]),
    })
    result = pd.DataFrame(rows)
    equity_change = float(end_account["portfolio_value"] - start_account["portfolio_value"])
    difference = float(result["attribution"].sum() - equity_change)
    if abs(difference) > tolerance:
        return AttributionResult(result, beginning, ending, equity_change, "mismatch", f"Attribution does not reconcile to account equity change (difference £{difference:,.2f}).")
    return AttributionResult(result, beginning, ending, equity_change, "available", "Attribution reconciles to the corresponding account equity change.")
