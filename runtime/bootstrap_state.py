from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config import STARTING_CASH
from execution.atomic_io import atomic_write_csv_frames, atomic_write_json
from execution.portfolio_manager import (
    PORTFOLIO_COLUMNS,
    TRADE_JOURNAL_COLUMNS,
    TRADE_SNAPSHOT_COLUMNS,
    TRANSACTION_LOG_COLUMNS,
)
from execution.trade_ledger import LEDGER_COLUMNS
from market_intelligence.news_store import empty_store as empty_market_intelligence
from news.news_monitor import NEWS_MONITOR_ENABLED
from notifications.alert_notifier import _default_state as default_notification_state


BROKER_COLUMNS = [
    "cash",
    "buying_power",
    "positions_value",
    "portfolio_value",
    "realised_pnl",
    "unrealised_pnl",
]

HOLDINGS_COLUMNS = [
    "date",
    "ticker",
    "shares",
    "entry_price",
    "current_price",
    "market_value",
    "unrealised_pnl",
    "unrealised_pnl_percent",
]

SIGNAL_REPORT_COLUMNS = ["date", "ticker", "signal", "weight", "status"]
TRADE_AUDIT_COLUMNS = [
    "entry_event_id",
    "exit_event_id",
    "entry_legacy_row_number",
    "exit_legacy_row_number",
    "ticker",
    "entry_date",
    "exit_date",
    "shares",
    "entry_price",
    "exit_price",
    "pnl",
    "pnl_percent",
    "source",
]
TRADE_ANALYTICS_COLUMNS = [
    "total_trades",
    "win_rate",
    "profit_factor",
    "average_winner",
    "average_loser",
    "best_trade",
    "worst_trade",
    "realised_pnl",
    "closed_trades",
    "open_positions",
    "source",
]
TRACKER_COLUMNS = [
    "date",
    "portfolio_value",
    "cash",
    "realised_pnl",
    "unrealised_pnl",
    "benchmark_return",
    "alpha",
]


@dataclass
class BootstrapResult:
    planned: list[str]
    created: list[str]
    existing: list[str]


def empty_frame(columns):
    return pd.DataFrame(columns=list(columns))


def broker_seed_frame():
    cash = float(STARTING_CASH)
    return pd.DataFrame(
        [
            {
                "cash": cash,
                "buying_power": cash,
                "positions_value": 0.0,
                "portfolio_value": cash,
                "realised_pnl": 0.0,
                "unrealised_pnl": 0.0,
            }
        ],
        columns=BROKER_COLUMNS,
    )


def csv_seed_frames():
    return {
        "broker_account.csv": broker_seed_frame(),
        "holdings_report.csv": empty_frame(HOLDINGS_COLUMNS),
        "paper_30_day_tracker.csv": empty_frame(TRACKER_COLUMNS),
        "paper_portfolio_v3.csv": empty_frame(PORTFOLIO_COLUMNS),
        "portfolio_v2.csv": empty_frame(["date", "portfolio_value"]),
        "prices_v2.csv": pd.DataFrame(),
        "risk_levels_v2.csv": pd.DataFrame(),
        "signal_report_v2.csv": empty_frame(SIGNAL_REPORT_COLUMNS),
        "signals_v2.csv": pd.DataFrame(),
        "trade_analytics_v3.csv": pd.DataFrame(
            [
                {
                    "total_trades": 0,
                    "win_rate": 0,
                    "profit_factor": 0,
                    "average_winner": 0,
                    "average_loser": 0,
                    "best_trade": 0,
                    "worst_trade": 0,
                    "realised_pnl": 0,
                    "closed_trades": 0,
                    "open_positions": 0,
                    "source": "bootstrap",
                }
            ],
            columns=TRADE_ANALYTICS_COLUMNS,
        ),
        "trade_audit_trail.csv": empty_frame(TRADE_AUDIT_COLUMNS),
        "trade_journal_v3.csv": empty_frame(TRADE_JOURNAL_COLUMNS),
        "trade_ledger_v1.csv": empty_frame(LEDGER_COLUMNS),
        "trade_snapshots.csv": empty_frame(TRADE_SNAPSHOT_COLUMNS),
        "trade_transactions_v1.csv": empty_frame(TRANSACTION_LOG_COLUMNS),
        "v3_trades.csv": empty_frame(TRANSACTION_LOG_COLUMNS),
        "weights_v2.csv": pd.DataFrame(),
    }


def json_seed_documents():
    return {
        "data/live_monitor_runtime.json": {
            "enabled": True,
            "last_run_at": None,
            "holdings_monitored": 0,
            "alerts_found": 0,
            "errors": [],
        },
        "data/live_monitor_snapshot.json": {
            "generated_at": None,
            "holdings_monitored": 0,
            "alerts": [],
            "errors": [],
        },
        "data/live_runtime_execution_log.json": [],
        "data/live_runtime_status.json": {
            "status": "not_started",
            "mode": "paper_execution",
            "started_at": None,
            "last_cycle_at": None,
            "next_cycle_at": None,
            "cycle_count": 0,
            "markets_checked": [],
            "markets_open": [],
            "holdings_monitored": 0,
            "alerts_found": 0,
            "notifications_sent": 0,
            "last_error": None,
            "paper_only": True,
            "paper_execution_enabled": False,
        },
        "data/market_intelligence.json": empty_market_intelligence(),
        "data/news_events.json": {
            "generated_at": None,
            "monitor_enabled": NEWS_MONITOR_ENABLED,
            "items_count": 0,
            "items": [],
            "errors": [],
        },
        "data/notification_state.json": default_notification_state(),
        "data/runtime_decision_trace.json": {
            "generated_at": None,
            "decisions": [],
            "summary": {},
        },
        "data/runtime_operations_log.json": [],
    }


def _relative(path, root_dir):
    try:
        return str(Path(path).resolve().relative_to(Path(root_dir).resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def bootstrap_runtime_state(root_dir=".", *, apply=False):
    root = Path(root_dir)
    csv_frames = {}
    json_documents = {}
    existing = []

    for relative_path, frame in csv_seed_frames().items():
        path = root / relative_path
        if path.exists():
            existing.append(relative_path)
            continue
        csv_frames[path] = frame

    for relative_path, document in json_seed_documents().items():
        path = root / relative_path
        if path.exists():
            existing.append(relative_path)
            continue
        json_documents[path] = document

    planned = [
        _relative(path, root)
        for path in [*csv_frames.keys(), *json_documents.keys()]
    ]
    created = []

    if apply and csv_frames:
        atomic_write_csv_frames(csv_frames)
        created.extend(_relative(path, root) for path in csv_frames)

    if apply:
        for path, document in json_documents.items():
            atomic_write_json(document, path)
            created.append(_relative(path, root))

    return BootstrapResult(
        planned=sorted(planned),
        created=sorted(created),
        existing=sorted(existing),
    )
