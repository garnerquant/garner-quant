from datetime import datetime, time
from pathlib import Path
import json
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from execution.portfolio_manager import load_portfolio


SNAPSHOT_FILE = Path("data/live_monitor_snapshot.json")
RUNTIME_FILE = Path("data/live_monitor_runtime.json")
LONDON_TZ = ZoneInfo("Europe/London")

ALERT_STOP_LOSS = "STOP_LOSS_HIT"
ALERT_TAKE_PROFIT = "TAKE_PROFIT_HIT"
ALERT_PRICE_FETCH_FAILED = "PRICE_FETCH_FAILED"
ALERT_POSITION_DATA_MISSING = "POSITION_DATA_MISSING"

REQUIRED_POSITION_FIELDS = [
    "ticker",
    "entry_price",
    "shares",
    "position_value",
    "stop_loss",
    "take_profit",
]


def _timestamp():
    return datetime.now().isoformat(timespec="seconds")


def _runtime_timestamp(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")

    return str(value)


def _safe_float(value):
    numeric_value = pd.to_numeric(value, errors="coerce")

    if pd.isna(numeric_value):
        return None

    return float(numeric_value)


def classify_market(tickers):
    ticker_values = {
        str(ticker).strip().upper()
        for ticker in tickers
        if str(ticker).strip()
    }

    if not ticker_values:
        return "uncertain"

    uk_tickers = {
        ticker
        for ticker in ticker_values
        if ticker.endswith(".L")
    }
    us_tickers = {
        ticker
        for ticker in ticker_values
        if "." not in ticker
    }

    if uk_tickers and not us_tickers and len(uk_tickers) == len(ticker_values):
        return "uk"

    if us_tickers and not uk_tickers and len(us_tickers) == len(ticker_values):
        return "us"

    return "mixed"


def load_current_holding_tickers():
    portfolio = load_portfolio()

    if portfolio.empty or "ticker" not in portfolio.columns:
        return []

    return portfolio["ticker"].dropna().astype(str).tolist()


def get_market_status(now=None, tickers=None):
    now = now or datetime.now(LONDON_TZ)

    if now.tzinfo is None:
        now = now.replace(tzinfo=LONDON_TZ)
    else:
        now = now.astimezone(LONDON_TZ)

    tickers = load_current_holding_tickers() if tickers is None else tickers
    market = classify_market(tickers)

    if now.weekday() >= 5:
        return {
            "is_open": False,
            "status": "Market Closed",
            "market": market,
            "warning": "Weekend. Live-Time Mode will not auto-refresh.",
            "timezone": "Europe/London",
        }

    windows = {
        "uk": (time(8, 0), time(16, 30)),
        "us": (time(14, 30), time(21, 0)),
        "mixed": (time(14, 30), time(16, 30)),
        "uncertain": (time(8, 0), time(16, 30)),
    }
    start, end = windows.get(market, windows["uncertain"])
    current_time = now.time()
    is_open = start <= current_time <= end

    warning = ""
    if market == "mixed":
        warning = (
            "Mixed or uncertain holdings detected. Using conservative overlap "
            "window of 14:30-16:30 London time."
        )
    elif market == "uncertain":
        warning = (
            "No recognised holding market detected. Using London monitoring "
            "hours."
        )

    return {
        "is_open": is_open,
        "status": "Market Open" if is_open else "Outside Monitoring Hours",
        "market": market,
        "warning": warning,
        "timezone": "Europe/London",
        "window_start": start.strftime("%H:%M"),
        "window_end": end.strftime("%H:%M"),
    }


def is_market_open(now=None):
    return get_market_status(now=now)["is_open"]


def _alert(
    ticker,
    alert_type,
    severity,
    message,
    current_price=None,
    trigger_price=None,
    unrealised_pnl=None,
):
    return {
        "ticker": ticker,
        "alert_type": alert_type,
        "severity": severity,
        "message": message,
        "current_price": current_price,
        "trigger_price": trigger_price,
        "unrealised_pnl": unrealised_pnl,
        "timestamp": _timestamp(),
    }


def _latest_close_series(data):
    if data.empty:
        return pd.Series(dtype=float)

    if isinstance(data.columns, pd.MultiIndex):
        for field in ["Close", "Adj Close"]:
            if field in data.columns.get_level_values(0):
                field_data = data.xs(field, axis=1, level=0)
                if isinstance(field_data, pd.DataFrame):
                    field_data = field_data.iloc[:, 0]
                return pd.to_numeric(field_data, errors="coerce").dropna()

            if field in data.columns.get_level_values(-1):
                field_data = data.xs(field, axis=1, level=-1)
                if isinstance(field_data, pd.DataFrame):
                    field_data = field_data.iloc[:, 0]
                return pd.to_numeric(field_data, errors="coerce").dropna()

        return pd.Series(dtype=float)

    price_columns = [
        column
        for column in ["Close", "Adj Close"]
        if column in data.columns
    ]

    if not price_columns:
        return pd.Series(dtype=float)

    return pd.to_numeric(data[price_columns[0]], errors="coerce").dropna()


def get_latest_price(ticker):
    """
    Fetch the latest available market price for a ticker.

    Returns a dictionary instead of raising so dashboard callers can display
    per-ticker failures without breaking the whole page.
    """
    if ticker is None or str(ticker).strip() == "":
        return {
            "ticker": ticker,
            "price": None,
            "timestamp": None,
            "error": "Missing ticker",
        }

    ticker = str(ticker).strip()

    try:
        data = yf.download(
            ticker,
            period="5d",
            interval="1m",
            auto_adjust=True,
            progress=False,
            threads=False,
        )

        if data.empty:
            data = yf.download(
                ticker,
                period="10d",
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False,
            )

        if data.empty:
            return {
                "ticker": ticker,
                "price": None,
                "timestamp": None,
                "error": "No market data returned",
            }

        prices = _latest_close_series(data)

        if prices.empty:
            return {
                "ticker": ticker,
                "price": None,
                "timestamp": None,
                "error": "No usable close price data returned",
            }

        latest_time = prices.index[-1]

        return {
            "ticker": ticker,
            "price": float(prices.iloc[-1]),
            "timestamp": str(latest_time),
            "error": None,
        }
    except Exception as exc:
        return {
            "ticker": ticker,
            "price": None,
            "timestamp": None,
            "error": str(exc),
        }


def _missing_fields(position):
    missing = []

    for field in REQUIRED_POSITION_FIELDS:
        if field not in position.index:
            missing.append(field)
            continue

        value = position[field]
        if pd.isna(value) or str(value).strip() == "":
            missing.append(field)

    return missing


def _monitor_position(position, timestamp):
    ticker = str(position.get("ticker", "")).strip()
    alerts = []
    errors = []

    missing = _missing_fields(position)
    if missing:
        message = (
            f"{ticker or 'Unknown position'} is missing required position data: "
            f"{', '.join(missing)}."
        )
        alerts.append(
            _alert(
                ticker or "UNKNOWN",
                ALERT_POSITION_DATA_MISSING,
                "medium",
                message,
            )
        )
        errors.append(message)
        return None, alerts, errors

    entry_price = _safe_float(position["entry_price"])
    shares = _safe_float(position["shares"])
    original_value = _safe_float(position["position_value"])
    stop_loss = _safe_float(position["stop_loss"])
    take_profit = _safe_float(position["take_profit"])

    if None in [entry_price, shares, original_value, stop_loss, take_profit]:
        message = f"{ticker} has non-numeric position data."
        alerts.append(
            _alert(
                ticker,
                ALERT_POSITION_DATA_MISSING,
                "medium",
                message,
            )
        )
        errors.append(message)
        return None, alerts, errors

    price_result = get_latest_price(ticker)

    if price_result["price"] is None:
        message = f"{ticker} latest price could not be fetched."
        alerts.append(
            _alert(
                ticker,
                ALERT_PRICE_FETCH_FAILED,
                "medium",
                message,
            )
        )
        errors.append(
            f"{ticker}: {price_result['error'] or 'Unknown price fetch error'}"
        )
        return {
            "ticker": ticker,
            "entry_price": entry_price,
            "shares": shares,
            "original_position_value": original_value,
            "current_price": None,
            "price_timestamp": price_result["timestamp"],
            "market_value": None,
            "unrealised_pnl": None,
            "unrealised_pnl_percent": None,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": "price_fetch_failed",
        }, alerts, errors

    current_price = price_result["price"]
    market_value = current_price * shares
    unrealised_pnl = market_value - original_value
    unrealised_pnl_percent = (current_price / entry_price) - 1

    if current_price <= stop_loss:
        alerts.append(
            _alert(
                ticker,
                ALERT_STOP_LOSS,
                "high",
                (
                    f"{ticker} is below its stop loss level. "
                    "Would exit now if live execution was enabled."
                ),
                current_price,
                stop_loss,
                unrealised_pnl,
            )
        )

    if current_price >= take_profit:
        alerts.append(
            _alert(
                ticker,
                ALERT_TAKE_PROFIT,
                "high",
                (
                    f"{ticker} is above its take profit level. "
                    "Would exit now if live execution was enabled."
                ),
                current_price,
                take_profit,
                unrealised_pnl,
            )
        )

    return {
        "ticker": ticker,
        "entry_price": entry_price,
        "shares": shares,
        "original_position_value": original_value,
        "current_price": current_price,
        "price_timestamp": price_result["timestamp"],
        "market_value": market_value,
        "unrealised_pnl": unrealised_pnl,
        "unrealised_pnl_percent": unrealised_pnl_percent,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "status": "ok",
        "monitored_at": timestamp,
    }, alerts, errors


def run_live_market_monitor(save_snapshot=True):
    """
    Monitor open paper holdings using latest available market prices.

    This is paper-alert only. It never places orders and never modifies the
    paper portfolio, trade journal, transaction log, or strategy config.
    """
    timestamp = _timestamp()
    portfolio = load_portfolio()

    monitored_holdings = []
    latest_prices = {}
    alerts = []
    errors = []

    if portfolio.empty:
        result = {
            "timestamp": timestamp,
            "holdings_monitored": 0,
            "latest_prices": latest_prices,
            "live_portfolio_value_estimate": 0.0,
            "live_unrealised_pnl": 0.0,
            "alerts": alerts,
            "errors": errors,
            "positions": monitored_holdings,
            "paper_only": True,
        }
        if save_snapshot:
            save_monitor_snapshot(result)
        return result

    for _, position in portfolio.iterrows():
        monitored, position_alerts, position_errors = _monitor_position(
            position,
            timestamp,
        )

        alerts.extend(position_alerts)
        errors.extend(position_errors)

        if monitored is not None:
            monitored_holdings.append(monitored)
            latest_prices[monitored["ticker"]] = {
                "price": monitored["current_price"],
                "timestamp": monitored["price_timestamp"],
            }

    live_value = sum(
        position["market_value"] or 0.0
        for position in monitored_holdings
    )
    live_pnl = sum(
        position["unrealised_pnl"] or 0.0
        for position in monitored_holdings
    )

    result = {
        "timestamp": timestamp,
        "holdings_monitored": len(monitored_holdings),
        "latest_prices": latest_prices,
        "live_portfolio_value_estimate": live_value,
        "live_unrealised_pnl": live_pnl,
        "alerts": alerts,
        "errors": errors,
        "positions": monitored_holdings,
        "paper_only": True,
    }

    if save_snapshot:
        save_monitor_snapshot(result)

    return result


def save_monitor_snapshot(snapshot, path=SNAPSHOT_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2),
        encoding="utf-8",
    )


def load_monitor_snapshot(path=SNAPSHOT_FILE):
    path = Path(path)

    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_monitor_runtime(path=RUNTIME_FILE):
    path = Path(path)

    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_monitor_runtime(runtime, path=RUNTIME_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    clean_runtime = dict(runtime)
    for key in ["last_refresh", "next_refresh", "updated_at"]:
        if key in clean_runtime:
            clean_runtime[key] = _runtime_timestamp(clean_runtime[key])

    path.write_text(
        json.dumps(clean_runtime, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    print(json.dumps(run_live_market_monitor(), indent=2))
