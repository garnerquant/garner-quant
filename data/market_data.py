import yfinance as yf

from data.yfinance_cache import configure_yfinance_cache_for_ci


def download_market_data(tickers, period="3y"):
    configure_yfinance_cache_for_ci()
    data = yf.download(
        tickers,
        period=period,
        interval="1d",
        auto_adjust=True,
        progress=False
    )

    return data.ffill()


def get_price_field(data, field):
    field_data = data[field]

    if hasattr(field_data, "columns"):
        return field_data.dropna(how="all").ffill()

    return field_data.to_frame().dropna(how="all").ffill()
