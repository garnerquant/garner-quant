from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from canonical_accounting.currency import FxQuote, canonical_currency, inverse_fx_quote


FX_SYMBOLS = {
    ("USD", "GBP"): ("USDGBP=X", "USD->GBP"),
    ("EUR", "GBP"): ("EURGBP=X", "EUR->GBP"),
}


class FxProviderError(RuntimeError):
    pass


class YFinanceFxProvider:
    source = "yfinance"

    def quote(self, source_currency: str, target_currency: str, *, downloader=None) -> FxQuote:
        source = canonical_currency(source_currency)
        target = canonical_currency(target_currency)
        if source == target:
            now = datetime.now(timezone.utc)
            return FxQuote(source, target, Decimal("1"), now, "identity", f"{source}->{target}")
        direct = FX_SYMBOLS.get((source, target))
        inverse = False
        if direct is None:
            direct = FX_SYMBOLS.get((target, source))
            inverse = direct is not None
        if direct is None:
            raise FxProviderError(f"no configured FX symbol for {source}->{target}")
        symbol, direction = direct
        if downloader is None:
            import yfinance as yf
            downloader = yf.download
        frame = downloader(
            symbol, period="5d", interval="1h", auto_adjust=True,
            progress=False, threads=False,
        )
        if frame is None or frame.empty:
            raise FxProviderError(f"no FX data returned for {symbol}")
        close = frame["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = pd.to_numeric(close, errors="coerce").dropna()
        if close.empty:
            raise FxProviderError(f"no usable FX close for {symbol}")
        timestamp = pd.Timestamp(close.index[-1])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        quote = FxQuote(
            direct and (target if inverse else source),
            direct and (source if inverse else target),
            Decimal(str(close.iloc[-1])), timestamp.to_pydatetime(),
            self.source, direction,
        )
        return inverse_fx_quote(quote) if inverse else quote
