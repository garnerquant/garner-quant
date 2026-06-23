import pandas as pd
import yfinance as yf


TICKERS = ["AAPL", "MSFT", "NVDA", "IUSA.L", "VWRL.L"]
START_DATE = "2020-01-01"
STARTING_CASH = 10000
THRESHOLDS = [0.00, 0.01, 0.02, 0.03, 0.05]


def get_close_prices(ticker):
    data = yf.download(
        ticker,
        start=START_DATE,
        progress=False,
        auto_adjust=True
    )

    if data.empty:
        return pd.Series(dtype=float)

    close = data["Close"]

    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    close = close.dropna()

    return close


def run_backtest(ticker, threshold):
    close = get_close_prices(ticker)

    if close.empty:
        return None

    ema20 = close.ewm(span=20).mean()

    signal = pd.Series(
        0,
        index=close.index
    )

    signal[close > ema20 * (1 + threshold)] = 1
    signal[close < ema20 * (1 - threshold)] = 0

    market_return = close.pct_change()
    strategy_return = signal.shift(1).fillna(0) * market_return

    equity = (
        (1 + strategy_return.fillna(0)).cumprod()
        * STARTING_CASH
    )

    total_return = (equity.iloc[-1] / STARTING_CASH) - 1
    max_drawdown = (equity / equity.cummax() - 1).min()
    trades = signal.diff().abs().sum()

    return {
        "ticker": ticker,
        "threshold": threshold,
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "trades": int(trades),
        "ending_value": equity.iloc[-1]
    }


results = []

for ticker in TICKERS:
    for threshold in THRESHOLDS:
        result = run_backtest(ticker, threshold)

        if result:
            results.append(result)

results = pd.DataFrame(results)

results.to_csv(
    "threshold_backtest_results.csv",
    index=False
)

print("\n===== THRESHOLD BACKTEST RESULTS =====")
print(
    results.sort_values(
        ["ticker", "total_return"],
        ascending=[True, False]
    )
)