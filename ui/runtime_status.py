import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client


ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNTIME_STATUS = ROOT / "data" / "live_runtime_status.json"

load_dotenv()


def _supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None

    try:
        return create_client(url, key)
    except Exception:
        return None


def _load_supabase_runtime_status():
    client = _supabase_client()
    if client is None:
        return {}

    try:
        response = (
            client.table("runtime_status")
            .select("*")
            .eq("id", "live")
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else {}
    except Exception:
        return {}


def _load_local_runtime_status(path=LOCAL_RUNTIME_STATUS):
    path = Path(path)
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_runtime_status():
    status = _load_supabase_runtime_status()
    if status:
        status["_runtime_source"] = "supabase"
        return status

    status = _load_local_runtime_status()
    status["_runtime_source"] = "local_json"
    return status


def runtime_status_updated_at(status):
    if status.get("_runtime_source") == "supabase":
        value = status.get("updated_at")
        if not value:
            return ""
        try:
            return pd.to_datetime(value, utc=True).tz_convert(None)
        except Exception:
            return value

    if LOCAL_RUNTIME_STATUS.exists():
        return pd.Timestamp.fromtimestamp(LOCAL_RUNTIME_STATUS.stat().st_mtime)

    return ""
