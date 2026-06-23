import pandas as pd


def sma(series, period):
    return series.rolling(period).mean()


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()

    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()

    rs = gain / loss

    return 100 - (100 / (1 + rs))


def macd(series):
    ema12 = ema(series, 12)
    ema26 = ema(series, 26)

    macd_line = ema12 - ema26
    signal_line = ema(macd_line, 9)

    return macd_line, signal_line


def atr(high, low, close, period=14):
    high_low = high - low

    high_close = (
        high - close.shift()
    ).abs()

    low_close = (
        low - close.shift()
    ).abs()

    true_range = pd.concat(
        [
            high_low,
            high_close,
            low_close
        ],
        axis=1
    ).max(axis=1)

    return true_range.rolling(period).mean()


def technical_score(price, volume=None):
    ema20 = ema(price, 20)
    ema50 = ema(price, 50)
    rsi14 = rsi(price)
    macd_line, signal_line = macd(price)

    score = pd.Series(0, index=price.index)

    MA_THRESHOLD = 0.02

    price_above_ema20 = (
        price > ema20 * (1 + MA_THRESHOLD)
    )

    ema20_above_ema50 = (
        ema20 > ema50 * (1 + MA_THRESHOLD)
    )

    score += price_above_ema20.astype(int)
    score += ema20_above_ema50.astype(int)
    score += ((rsi14 > 45) & (rsi14 < 70)).astype(int)
    score += (macd_line > signal_line).astype(int)

    if volume is not None:
        volume_avg = volume.rolling(20).mean()
        score += (volume > volume_avg).astype(int)

    return score