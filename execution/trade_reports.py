from __future__ import annotations

from pathlib import Path

import pandas as pd

from execution.trade_audit import (
    build_authoritative_trade_audit,
    ledger_open_positions,
)
from execution.trade_ledger import load_trade_ledger
from reporting.trade_analytics import analyse_authoritative_trades


AUDIT_FILE = "trade_audit_trail.csv"
ANALYTICS_FILE = "trade_analytics_v3.csv"
JOURNAL_FILE = "trade_journal_v3.csv"
LEDGER_FILE = "trade_ledger_v1.csv"

LEDGER_AUDIT_REQUIRED_COLUMNS = [
    "entry_event_id",
    "exit_event_id",
    "entry_legacy_row_number",
    "exit_legacy_row_number",
    "source",
]


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_legacy_journal(path=JOURNAL_FILE):
    return read_csv(path)


def ledger_has_clean_events(ledger):
    if ledger is None or ledger.empty:
        return False
    if "event_id" not in ledger.columns:
        return False
    return ledger["event_id"].fillna("").astype(str).str.strip().ne("").any()


def ensure_ledger_audit_contract(audit, ledger):
    if not ledger_has_clean_events(ledger):
        return audit

    if audit is None:
        audit = pd.DataFrame()

    audit = audit.copy()
    for column in LEDGER_AUDIT_REQUIRED_COLUMNS:
        if column not in audit.columns:
            if audit.empty:
                audit[column] = pd.Series(dtype=str)
            else:
                raise ValueError(
                    "Refusing to write legacy-shaped trade audit while "
                    f"{LEDGER_FILE} exists; missing column {column}."
                )

    if not audit.empty:
        source = audit["source"].fillna("").astype(str).str.strip()
        if not source.eq(LEDGER_FILE).all():
            raise ValueError(
                "Refusing to write trade audit because source is not "
                f"{LEDGER_FILE} for every row."
            )
        for column in ["entry_event_id", "exit_event_id"]:
            if not audit[column].fillna("").astype(str).str.strip().ne("").all():
                raise ValueError(
                    "Refusing to write trade audit with blank ledger event IDs."
                )

    return audit


def ensure_ledger_analytics_contract(analytics, ledger):
    if not ledger_has_clean_events(ledger):
        return analytics

    analytics = dict(analytics or {})
    source = str(analytics.get("source", "")).strip()
    if source != LEDGER_FILE:
        raise ValueError(
            "Refusing to write trade analytics because source is not "
            f"{LEDGER_FILE}."
        )
    return analytics


def build_authoritative_trade_reports(
    legacy_journal=None,
    ledger_path=LEDGER_FILE,
):
    ledger = load_trade_ledger(ledger_path)
    audit = build_authoritative_trade_audit(
        legacy_journal=legacy_journal,
        ledger_path=ledger_path,
    )
    audit = ensure_ledger_audit_contract(audit, ledger)
    open_positions = len(ledger_open_positions(ledger))
    analytics = analyse_authoritative_trades(
        legacy_journal,
        ledger_path=ledger_path,
        open_positions=open_positions,
    )
    analytics = ensure_ledger_analytics_contract(analytics, ledger)
    return audit, analytics


def write_authoritative_trade_reports(
    *,
    legacy_journal=None,
    audit_path=AUDIT_FILE,
    analytics_path=ANALYTICS_FILE,
    ledger_path=LEDGER_FILE,
):
    audit, analytics = build_authoritative_trade_reports(
        legacy_journal=legacy_journal,
        ledger_path=ledger_path,
    )
    Path(audit_path).parent.mkdir(parents=True, exist_ok=True)
    Path(analytics_path).parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(audit_path, index=False)
    pd.DataFrame([analytics]).to_csv(analytics_path, index=False)
    return audit, analytics
