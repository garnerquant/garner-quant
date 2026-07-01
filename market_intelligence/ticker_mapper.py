from pathlib import Path

import pandas as pd


SIGNAL_REPORT_FILE = Path("signal_report_v2.csv")


ASSET_ALIASES = {
    "VWRL.L": ["vwrl", "vanguard ftse all-world", "ftse all-world"],
    "IUSA.L": ["iusa", "s&p 500", "sp 500", "ishares s&p 500"],
    "SGLN.L": ["sgln", "gold", "physical gold"],
    "AAPL": ["aapl", "apple"],
    "MSFT": ["msft", "microsoft"],
    "NVDA": ["nvda", "nvidia"],
    "TSLA": ["tsla", "tesla"],
    "BTC-GBP": ["btc", "bitcoin"],
    "ETH-GBP": ["eth", "ethereum"],
    "SPY": ["spy", "s&p 500", "sp 500"],
}


def _unique(values):
    result = []
    seen = set()
    for value in values:
        value = str(value or "").strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def current_holdings():
    try:
        from execution.portfolio_manager import load_portfolio

        portfolio = load_portfolio()
        if portfolio.empty or "ticker" not in portfolio.columns:
            return []
        return _unique(portfolio["ticker"].dropna().astype(str).tolist())
    except Exception:
        return []


def todays_signals():
    if not SIGNAL_REPORT_FILE.exists():
        return []

    try:
        signals = pd.read_csv(SIGNAL_REPORT_FILE)
    except Exception:
        return []

    if "ticker" not in signals.columns:
        return []
    return _unique(signals["ticker"].dropna().astype(str).tolist())


def watchlist():
    try:
        from config import ASSETS, BENCHMARK_TICKER

        return _unique(list(ASSETS.keys()) + [BENCHMARK_TICKER])
    except Exception:
        return []


def intelligence_context():
    holdings = current_holdings()
    signals = todays_signals()
    watch = watchlist()
    return {
        "current_holdings": holdings,
        "todays_signals": signals,
        "watchlist": watch,
        "all_tickers": _unique(holdings + signals + watch),
    }


def query_for_ticker(ticker):
    aliases = ASSET_ALIASES.get(str(ticker).upper(), [])
    return aliases[0] if aliases else str(ticker)


def match_story_to_tickers(story, tickers):
    text = f"{story.get('headline', '')} {story.get('summary', '')}".lower()
    matched = []
    for ticker in tickers:
        ticker_key = str(ticker).upper()
        aliases = ASSET_ALIASES.get(ticker_key, []) + [ticker_key.lower()]
        if any(alias.lower() in text for alias in aliases):
            matched.append(ticker_key)
    return _unique(matched)

