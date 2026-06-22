STARTING_CASH = 10000

MAX_DRAWDOWN = 0.30

RISK_PER_TRADE = 0.01

ASSETS = {

    # Global ETFs
    "VWRL.L": {
        "type": "etf",
        "max_weight": 0.25
    },

    "IUSA.L": {
        "type": "etf",
        "max_weight": 0.20
    },

    # Gold ETF
    "SGLN.L": {
        "type": "gold",
        "max_weight": 0.15
    },

    # Stocks
    "AAPL": {
        "type": "equity",
        "max_weight": 0.10
    },

    "MSFT": {
        "type": "equity",
        "max_weight": 0.10
    },

    "NVDA": {
        "type": "equity",
        "max_weight": 0.10
    },

    "TSLA": {
        "type": "equity",
        "max_weight": 0.08
    },

    # Crypto
    "BTC-GBP": {
        "type": "crypto",
        "max_weight": 0.10
    },

    "ETH-GBP": {
        "type": "crypto",
        "max_weight": 0.05
    }

}

TOTAL_CRYPTO_LIMIT = 0.15