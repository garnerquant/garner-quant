"""Configuration for the read-only news intelligence layer."""

NEWS_MONITOR_ENABLED = True
NEWS_ALERTS_ENABLED = False
NEWS_MAX_ITEMS = 50
NEWS_REQUEST_TIMEOUT_SECONDS = 8

NEWS_FEEDS = [
    {
        "source": "Google News",
        "url": "https://news.google.com/rss/search?q={query}%20stock%20OR%20market&hl=en-GB&gl=GB&ceid=GB:en",
    },
]

NEWS_QUERY_ALIASES = {
    "VWRL.L": "Vanguard FTSE All-World ETF",
    "IUSA.L": "iShares S&P 500 ETF",
    "SGLN.L": "iShares Physical Gold ETC",
    "BTC-GBP": "Bitcoin",
    "ETH-GBP": "Ethereum",
}
