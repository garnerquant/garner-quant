import pandas as pd


def format_currency(value):
    try:
        return f"£{float(value):,.2f}"
    except Exception:
        return "£0.00"


def format_percent(value):
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "0.00%"


def format_date(value):
    try:
        return pd.to_datetime(
            value,
            format="mixed",
            errors="coerce"
        ).strftime("%Y-%m-%d")
    except Exception:
        return ""