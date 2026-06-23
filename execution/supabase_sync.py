import os
import pandas as pd
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

    holdings = pd.read_csv("holdings_report.csv")

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

        data = {
            "date": str(row["date"]),
            "portfolio_value": float(row["portfolio_value"]),
            "cash": float(row["cash"]),
            "realised_pnl": float(row["realised_pnl"]),
            "unrealised_pnl": float(row["unrealised_pnl"]),
            "updated_at": datetime.utcnow().isoformat()
        }

        supabase.table("paper_30_day_tracker").insert(data).execute()

    print("Supabase 30 day tracker synced.")