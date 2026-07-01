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


def sync_holdings():
    client = get_supabase_client()

    try:
        holdings = pd.read_csv("holdings_report.csv")
    except pd.errors.EmptyDataError:
        client.table("holdings").delete().neq("id", 0).execute()
        print("No holdings to sync.")
        return

    client.table("holdings").delete().neq("id", 0).execute()

    for _, row in holdings.iterrows():

        data = {
            "ticker": row["ticker"],
            "shares": float(row["shares"]),
            "entry_price": float(row["entry_price"]),
            "current_price": float(row["current_price"]),
            "market_value": float(row["market_value"]),
            "unrealised_pnl": float(row["unrealised_pnl"]),
            "unrealised_pnl_percent": float(row["unrealised_pnl_percent"]),
            "updated_at": datetime.utcnow().isoformat()
        }

        client.table("holdings").insert(data).execute()

    print("Supabase holdings synced.")


def sync_30_day_tracker():
    client = get_supabase_client()

    tracker = pd.read_csv("paper_30_day_tracker.csv")

    client.table("paper_30_day_tracker").delete().neq("id", 0).execute()

    for _, row in tracker.iterrows():

        benchmark_return = row.get("benchmark_return", 0)
        alpha = row.get("alpha", 0)

        benchmark_return = 0 if pd.isna(benchmark_return) or not math.isfinite(float(benchmark_return)) else float(benchmark_return)
        alpha = 0 if pd.isna(alpha) or not math.isfinite(float(alpha)) else float(alpha)

        data = {
            "date": str(row["date"]),
            "portfolio_value": float(row["portfolio_value"]),
            "cash": float(row["cash"]),
            "realised_pnl": float(row["realised_pnl"]),
            "unrealised_pnl": float(row["unrealised_pnl"]),
            "benchmark_return": benchmark_return,
            "alpha": alpha,
            "updated_at": datetime.utcnow().isoformat()
        }

        client.table("paper_30_day_tracker").insert(data).execute()

    print("Supabase 30 day tracker synced.")

def sync_holdings_history():
    client = get_supabase_client()

    try:
        holdings = pd.read_csv("holdings_report.csv")
    except pd.errors.EmptyDataError:
        print("No holdings history to sync.")
        return

    today = datetime.utcnow().date().isoformat()

    client.table("holdings_history").delete().eq("date", today).execute()

    for _, row in holdings.iterrows():

        data = {
            "date": today,
            "ticker": row["ticker"],
            "shares": float(row["shares"]),
            "entry_price": float(row["entry_price"]),
            "current_price": float(row["current_price"]),
            "market_value": float(row["market_value"]),
            "unrealised_pnl": float(row["unrealised_pnl"]),
            "unrealised_pnl_percent": float(row["unrealised_pnl_percent"])
        }

        client.table("holdings_history").insert(data).execute()

    print("Supabase holdings history synced.")
    
def sync_trade_journal():
    client = get_supabase_client()

    trades = pd.read_csv("trade_journal_v3.csv")
    print(f"Trade journal rows loaded: {len(trades)}")
    print(trades.tail(20))

    client.table("trade_journal").delete().neq("id", 0).execute()

    for _, row in trades.iterrows():

        data = {
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
        }

        client.table("trade_journal").insert(data).execute()

    print("Supabase trade journal synced.")

def sync_signals():
    client = get_supabase_client()

    signals = pd.read_csv(
        "signal_report_v2.csv"
    )

    client.table(
        "signals"
    ).delete().neq(
        "id",
        0
    ).execute()

    for _, row in signals.iterrows():

        data = {
            "date": str(row["date"]),
            "ticker": row["ticker"],
            "signal": row["signal"],
            "weight": float(row["weight"]),
            "status": row["status"],
            "updated_at":
                datetime.utcnow().isoformat()
        }

        client.table(
            "signals"
        ).insert(data).execute()

    print("Supabase signals synced.")
