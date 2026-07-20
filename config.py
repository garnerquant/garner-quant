STARTING_CASH = 10000

PAPER_TRADING_CHALLENGE_DAYS = 60

MAX_DRAWDOWN = 0.30

RISK_PER_TRADE = 0.01

SELL_CONFIRMATION_RUNS = 2

MIN_HOLD_DAYS_FOR_SIGNAL_EXIT = 3

MA_THRESHOLD = 0.01

ETF_MA_THRESHOLD = 0.00
STOCK_MA_THRESHOLD = 0.01
CRYPTO_MA_THRESHOLD = 0.03
DEFAULT_MA_THRESHOLD = 0.01

ASSETS = {

    # Global ETFs
    "VWRL.L": {
        "type": "etf",
        "asset_class": "ETF",
        "exposure_region": "Global",
        "exchange": "LSE",
        "listing_currency": "GBp",
        "max_weight": 0.25
    },

    "IUSA.L": {
        "type": "etf",
        "asset_class": "ETF",
        "exposure_region": "US",
        "exchange": "LSE",
        "listing_currency": "GBp",
        "max_weight": 0.20
    },

    # Gold ETF
    "SGLN.L": {
        "type": "gold",
        "asset_class": "Commodity",
        "exposure_region": "Global",
        "exchange": "LSE",
        "listing_currency": "GBp",
        "max_weight": 0.15
    },

    # Stocks
    "AAPL": {
        "type": "equity",
        "asset_class": "equity",
        "exposure_region": "US",
        "exchange": "NASDAQ",
        "listing_currency": "USD",
        "max_weight": 0.10
    },

    "MSFT": {
        "type": "equity",
        "asset_class": "equity",
        "exposure_region": "US",
        "exchange": "NASDAQ",
        "listing_currency": "USD",
        "max_weight": 0.10
    },

    "NVDA": {
        "type": "equity",
        "asset_class": "equity",
        "exposure_region": "US",
        "exchange": "NASDAQ",
        "listing_currency": "USD",
        "max_weight": 0.10
    },

    "TSLA": {
        "type": "equity",
        "asset_class": "equity",
        "exposure_region": "US",
        "exchange": "NASDAQ",
        "listing_currency": "USD",
        "max_weight": 0.08
    },

    # Crypto
    "BTC-GBP": {
        "type": "crypto",
        "asset_class": "Crypto",
        "exposure_region": "Global",
        "exchange": "Crypto",
        "listing_currency": "GBP",
        "max_weight": 0.10
    },

    "ETH-GBP": {
        "type": "crypto",
        "asset_class": "Crypto",
        "exposure_region": "Global",
        "exchange": "Crypto",
        "listing_currency": "GBP",
        "max_weight": 0.05
    }

}

TOTAL_CRYPTO_LIMIT = 0.15

BENCHMARK_TICKER = "SPY"
