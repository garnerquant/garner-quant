from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from runtime.bar_scheduler import (
    ExchangeCalendarAdapter,
    ProcessedBarStore,
    evaluate_completed_bar,
    market_policies,
)


def download_daily_closes(symbols, downloader=None):
    if downloader is None:
        import yfinance as yf
        downloader = yf.download
    data = downloader(
        list(symbols), period="10d", interval="1d", auto_adjust=True,
        progress=False, threads=False,
    )
    if data is None or data.empty:
        raise ValueError("scheduler market-data provider returned no bars")
    close = data["Close"] if "Close" in data else data
    if isinstance(close, pd.Series):
        close = close.to_frame(name=list(symbols)[0])
    return close.copy(deep=True)


def completed_bar_timestamps(close_frame, *, now, policies=None, calendar_adapter=None):
    """Map raw daily session labels to explicit completed UTC bar closes.

    Daily provider indices are treated as session labels, not event timestamps.
    Intraday/event timestamp APIs remain required to provide timezone-aware values.
    """
    policies = policies or market_policies()
    adapter = calendar_adapter or ExchangeCalendarAdapter()
    current = pd.Timestamp(now)
    if current.tzinfo is None:
        raise ValueError("runtime clock must be timezone-aware")
    current = current.tz_convert("UTC")
    results = {}
    failures = {}
    for symbol, policy in policies.items():
        if symbol not in close_frame.columns:
            failures[symbol] = "market data column is missing"
            continue
        values = pd.to_numeric(close_frame[symbol], errors="coerce").dropna()
        if values.empty:
            failures[symbol] = "no valid daily close observations"
            continue
        candidates = []
        for label in values.index:
            session_label = pd.Timestamp(label)
            if policy.continuous_market:
                date = session_label.date()
                close = pd.Timestamp(date, tz="UTC") + pd.Timedelta(days=1)
            else:
                calendar = adapter.loader(policy.calendar_id)
                date = session_label.date()
                day = pd.Timestamp(date)
                if not calendar.is_session(day):
                    continue
                close = calendar.session_close(day).tz_convert("UTC")
            if close <= current:
                candidates.append(close)
        if not candidates:
            failures[symbol] = "no fully completed daily bar"
        else:
            results[symbol] = max(candidates)
    return results, failures


def schedule_completed_bars(
    close_frame,
    *,
    now,
    strategy_version,
    configuration_version,
    data_source="yfinance",
    store=None,
    execution_block_reason=None,
    policies=None,
    calendar_adapter=None,
):
    policies = policies or market_policies()
    adapter = calendar_adapter or ExchangeCalendarAdapter()
    timestamps, failures = completed_bar_timestamps(
        close_frame, now=now, policies=policies, calendar_adapter=adapter
    )
    store = store or ProcessedBarStore()
    decisions = []
    claimed = []
    for symbol in policies:
        if symbol in failures:
            decisions.append({
                "symbol": symbol, "eligible": False, "status": "FAILED_FINAL",
                "reason": failures[symbol], "identity": None,
            })
            continue
        decision = evaluate_completed_bar(
            symbol, timestamps[symbol], now=now,
            strategy_version=strategy_version,
            configuration_version=configuration_version,
            data_source=data_source, policies=policies, calendar_adapter=adapter,
        )
        item = asdict(decision)
        item["identity"] = asdict(decision.identity) if decision.identity else None
        if not decision.eligible:
            decisions.append(item)
            continue
        acquired, record = store.claim(decision, decision_timestamp=now)
        if not acquired:
            item.update({"eligible": False, "status": "DUPLICATE_SUPPRESSED",
                         "reason": "completed bar was already claimed or processed"})
            decisions.append(item)
            continue
        if execution_block_reason:
            store.transition(
                decision.identity, "EXECUTION_BLOCKED", timestamp=now,
                execution_result="blocked", failure_reason=execution_block_reason,
            )
            item.update({"eligible": False, "status": "EXECUTION_BLOCKED",
                         "reason": execution_block_reason})
        else:
            store.transition(decision.identity, "VALIDATED", timestamp=now)
            claimed.append(decision)
            item["status"] = "VALIDATED"
        decisions.append(item)
    return {
        "decisions": decisions,
        "claimed": claimed,
        "eligible_symbols": [decision.symbol for decision in claimed],
        "bar_identities": {
            decision.symbol: decision.identity.key for decision in claimed
        },
        "bar_timestamps": {
            decision.symbol: decision.identity.bar_close_utc for decision in claimed
        },
        "health": store.health(),
    }
