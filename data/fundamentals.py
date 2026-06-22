import yfinance as yf


def get_fundamental_score(ticker, asset_type):
    if asset_type in ["etf", "gold", "crypto"]:
        return 3

    try:
        info = yf.Ticker(ticker).info

        score = 0

        pe = info.get("trailingPE")
        profit_margin = info.get("profitMargins")
        debt_equity = info.get("debtToEquity")
        roe = info.get("returnOnEquity")
        revenue_growth = info.get("revenueGrowth")
        earnings_growth = info.get("earningsGrowth")
        free_cashflow = info.get("freeCashflow")

        if pe is not None and pe < 35:
            score += 1

        if profit_margin is not None and profit_margin > 0.05:
            score += 1

        if debt_equity is not None and debt_equity < 200:
            score += 1

        if roe is not None and roe > 0.10:
            score += 1

        if revenue_growth is not None and revenue_growth > 0:
            score += 1

        if earnings_growth is not None and earnings_growth > 0:
            score += 1

        if free_cashflow is not None and free_cashflow > 0:
            score += 1

        return score

    except Exception:
        return 0


def fundamental_pass(ticker, asset_type):
    score = get_fundamental_score(ticker, asset_type)

    if asset_type in ["etf", "gold", "crypto"]:
        return True

    return score >= 4