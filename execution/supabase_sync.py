import os
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


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