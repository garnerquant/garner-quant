import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

supabase = create_client(url, key)

data = {
    "id": 1,
    "portfolio_value": 10001.55,
    "cash": 4499,
    "buying_power": 4499,
    "realised_pnl": 0,
    "unrealised_pnl": 2.56
}

response = (
    supabase
    .table("broker_account")
    .upsert(data)
    .execute()
)

print(response)