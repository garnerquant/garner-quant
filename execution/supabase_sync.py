import os
import json
import pandas as pd
import math
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime
from pathlib import Path

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = None


def warn_sync_failed(name, exc):
    print(f"Warning: {name} Supabase sync failed: {exc}")


def safe_float(value, default=0.0):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default

    if not math.isfinite(numeric):
        return default

    return numeric


def upsert_rows(client, table_name, rows):
    if not rows:
        return

    client.table(table_name).upsert(rows).execute()


def remote_ids(client, table_name, filters=None):
    query = client.table(table_name).select("id")
    for column, value in filters or []:
        query = query.eq(column, value)

    response = query.execute()
    return {
        row.get("id")
        for row in (response.data or [])
        if row.get("id") is not None
    }


def delete_stale_rows(client, table_name, desired_ids, filters=None):
    stale_ids = remote_ids(client, table_name, filters=filters) - set(desired_ids)

    for stale_id in stale_ids:
        query = client.table(table_name).delete()
        for column, value in filters or []:
            query = query.eq(column, value)
        query.eq("id", stale_id).execute()


def replace_rows_after_upsert(client, table_name, rows, filters=None):
    desired_ids = [row["id"] for row in rows]
    upsert_rows(client, table_name, rows)
    delete_stale_rows(client, table_name, desired_ids, filters=filters)


def get_supabase_client():
    global supabase

    if supabase is not None:
        return supabase

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase credentials are not configured.")

    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_KEY
    )
    return supabase


def sync_runtime_status(status_path="data/live_runtime_status.json"):
    try:
        path = Path(status_path)
        if not path.exists():
            print(f"Warning: runtime status sync skipped; missing {status_path}.")
            return False

        status = json.loads(path.read_text(encoding="utf-8"))
        data = {
            "id": "live",
            "status": status.get("status"),
            "mode": status.get("mode"),
            "started_at": status.get("started_at"),
            "last_cycle_at": status.get("last_cycle_at"),
            "next_cycle_at": status.get("next_cycle_at"),
            "cycle_count": status.get("cycle_count"),
            "markets_checked": status.get("markets_checked"),
            "markets_open": status.get("markets_open"),
            "current_strategy_stage": status.get("current_strategy_stage"),
            "latest_runtime_event": status.get("latest_runtime_event"),
            "execution_summary": status.get("execution_summary"),
            "latest_paper_trade": status.get("latest_paper_trade"),
            "last_error": status.get("last_error"),
            "updated_at": datetime.utcnow().isoformat(),
        }

        get_supabase_client().table("runtime_status").upsert(data).execute()
        return True
    except Exception as exc:
        print(f"Warning: runtime status Supabase sync failed: {exc}")
        return False


def sync_broker_account():
    try:
        client = get_supabase_client()

        broker = pd.read_csv("broker_account.csv")
        row = broker.iloc[0]

        data = {
            "id": 1,
            "portfolio_value": float(row["portfolio_value"]),
            "cash": float(row["cash"]),
            "buying_power": float(row["buying_power"]),
            "realised_pnl": float(row["realised_pnl"]),
            "unrealised_pnl": float(row["unrealised_pnl"]),
            "updated_at": datetime.utcnow().isoformat()
        }

        client.table("broker_account").upsert(data).execute()

        print("Supabase broker account synced.")
        return True
    except Exception as exc:
        warn_sync_failed("broker account", exc)
        return False


def sync_holdings():
    try:
        client = get_supabase_client()
        holdings = pd.read_csv("holdings_report.csv")
    except pd.errors.EmptyDataError:
        holdings = pd.DataFrame()
    except Exception as exc:
        warn_sync_failed("holdings", exc)
        return False

    try:
        rows = []
        for _, row in holdings.iterrows():
            rows.append({
                "id": int(len(rows) + 1),
                "ticker": row["ticker"],
                "shares": float(row["shares"]),
                "entry_price": float(row["entry_price"]),
                "current_price": float(row["current_price"]),
                "market_value": float(row["market_value"]),
                "unrealised_pnl": float(row["unrealised_pnl"]),
                "unrealised_pnl_percent": float(row["unrealised_pnl_percent"]),
                "updated_at": datetime.utcnow().isoformat()
            })
        replace_rows_after_upsert(client, "holdings", rows)
        print("Supabase holdings synced.")
        return True
    except Exception as exc:
        warn_sync_failed("holdings", exc)
        return False


def sync_30_day_tracker():
    try:
        client = get_supabase_client()
        tracker = pd.read_csv("paper_30_day_tracker.csv")
    except Exception as exc:
        warn_sync_failed("30 day tracker", exc)
        return False

    try:
        rows = []
        for _, row in tracker.iterrows():
            benchmark_return = row.get("benchmark_return", 0)
            alpha = row.get("alpha", 0)

            benchmark_return = safe_float(benchmark_return)
            alpha = safe_float(alpha)

            rows.append({
                "id": int(len(rows) + 1),
                "date": str(row["date"]),
                "portfolio_value": float(row["portfolio_value"]),
                "cash": float(row["cash"]),
                "realised_pnl": float(row["realised_pnl"]),
                "unrealised_pnl": float(row["unrealised_pnl"]),
                "benchmark_return": benchmark_return,
                "alpha": alpha,
                "updated_at": datetime.utcnow().isoformat()
            })
        replace_rows_after_upsert(client, "paper_30_day_tracker", rows)
        print("Supabase 30 day tracker synced.")
        return True
    except Exception as exc:
        warn_sync_failed("30 day tracker", exc)
        return False


def sync_holdings_history():
    try:
        client = get_supabase_client()
        holdings = pd.read_csv("holdings_report.csv")
    except pd.errors.EmptyDataError:
        holdings = pd.DataFrame()
    except Exception as exc:
        warn_sync_failed("holdings history", exc)
        return False

    today = datetime.utcnow().date().isoformat()
    try:
        rows = []
        for _, row in holdings.iterrows():
            rows.append({
                "id": int(datetime.utcnow().strftime("%Y%m%d")) * 1000 + len(rows) + 1,
                "date": today,
                "ticker": row["ticker"],
                "shares": float(row["shares"]),
                "entry_price": float(row["entry_price"]),
                "current_price": float(row["current_price"]),
                "market_value": float(row["market_value"]),
                "unrealised_pnl": float(row["unrealised_pnl"]),
                "unrealised_pnl_percent": float(row["unrealised_pnl_percent"])
            })
        replace_rows_after_upsert(
            client,
            "holdings_history",
            rows,
            filters=[("date", today)],
        )
        print("Supabase holdings history synced.")
        return True
    except Exception as exc:
        warn_sync_failed("holdings history", exc)
        return False

def sync_trade_journal():
    try:
        client = get_supabase_client()
        trades = pd.read_csv("trade_journal_v3.csv")
        print(f"Trade journal rows loaded: {len(trades)}")
        print(trades.tail(20))
    except Exception as exc:
        warn_sync_failed("trade journal", exc)
        return False

    try:
        rows = []
        for _, row in trades.iterrows():
            rows.append({
                "id": int(len(rows) + 1),
                "date": str(row.get("date", row.get("exit_date", ""))),
                "time": str(row.get("time", "")),
                "ticker": str(row.get("ticker", "")),
                "action": str(row.get("action", "SELL")),
                "shares": float(row.get("shares", 0)),
                "price": float(row.get("price", row.get("exit_price", 0))),
                "value": float(row.get("value", row.get("exit_price", 0) * row.get("shares", 0))),
                "pnl": float(row.get("pnl", 0)),
                "reason": str(row.get("reason", "")),
                "updated_at": datetime.utcnow().isoformat()
            })
        replace_rows_after_upsert(client, "trade_journal", rows)
        print("Supabase trade journal synced.")
        return True
    except Exception as exc:
        warn_sync_failed("trade journal", exc)
        return False


def sync_signals():
    try:
        client = get_supabase_client()
        signals = pd.read_csv(
            "signal_report_v2.csv"
        )
    except Exception as exc:
        warn_sync_failed("signals", exc)
        return False

    try:
        rows = []
        for _, row in signals.iterrows():
            rows.append({
                "id": int(len(rows) + 1),
                "date": str(row["date"]),
                "ticker": row["ticker"],
                "signal": row["signal"],
                "weight": float(row["weight"]),
                "status": row["status"],
                "updated_at":
                    datetime.utcnow().isoformat()
            })
        replace_rows_after_upsert(client, "signals", rows)
        print("Supabase signals synced.")
        return True
    except Exception as exc:
        warn_sync_failed("signals", exc)
        return False
