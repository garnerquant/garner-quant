import os
import pandas as pd
import math
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


def sync_broker_account():

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

    supabase.table("broker_account").upsert(data).execute()

    print("Supabase broker account synced.")


def sync_holdings():

    try:
        holdings = pd.read_csv("holdings_report.csv")
    except pd.errors.EmptyDataError:
        supabase.table("holdings").delete().neq("id", 0).execute()
        print("No holdings to sync.")
        return

    supabase.table("holdings").delete().neq("id", 0).execute()

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

        supabase.table("holdings").insert(data).execute()

    print("Supabase holdings synced.")


def sync_30_day_tracker():

    tracker = pd.read_csv("paper_30_day_tracker.csv")

    supabase.table("paper_30_day_tracker").delete().neq("id", 0).execute()

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

        supabase.table("paper_30_day_tracker").insert(data).execute()

    print("Supabase 30 day tracker synced.")

def sync_holdings_history():

    try:
        holdings = pd.read_csv("holdings_report.csv")
    except pd.errors.EmptyDataError:
        print("No holdings history to sync.")
        return

    today = datetime.utcnow().date().isoformat()

    supabase.table("holdings_history").delete().eq("date", today).execute()

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

        supabase.table("holdings_history").insert(data).execute()

    print("Supabase holdings history synced.")
    
def sync_trade_journal():

    trades = pd.read_csv("trade_journal_v3.csv")

    supabase.table("trade_journal").delete().neq("id", 0).execute()

    for _, row in trades.iterrows():

        data = {
            "date": str(row.get("date", "")),
            "ticker": str(row.get("ticker", "")),
            "action": str(row.get("action", "")),
            "shares": float(row.get("shares", 0)),
            "price": float(row.get("price", 0)),
            "value": float(row.get("value", 0)),
            "pnl": float(row.get("pnl", 0)),
            "reason": str(row.get("reason", "")),
            "updated_at": datetime.utcnow().isoformat()
        }

        supabase.table("trade_journal").insert(data).execute()

    print("Supabase trade journal synced.")

def sync_signals():

    signals = pd.read_csv(
        "signal_report_v2.csv"
    )

    supabase.table(
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

        supabase.table(
            "signals"
        ).insert(data).execute()

    print("Supabase signals synced.")