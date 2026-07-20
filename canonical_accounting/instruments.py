from __future__ import annotations

from decimal import Decimal

from canonical_accounting.currency import InstrumentMetadata


def _metadata(symbol, asset_class, currency, unit, scale, exchange, calendar, source, supported=True):
    return InstrumentMetadata(
        symbol=symbol,
        asset_class=asset_class,
        provider="yfinance",
        provider_symbol=symbol,
        instrument_currency=currency,
        provider_price_unit=unit,
        listing_unit=unit,
        price_scale=Decimal(scale),
        exchange=exchange,
        market_calendar=calendar,
        fx_required=currency != "GBP",
        supported=supported,
        metadata_source=source,
    )


# No entry is inferred from its suffix. VWRL.L is deliberately unsupported because
# repository history proves its configured GBp label conflicts with provider values.
INSTRUMENT_REGISTRY = {
    "BTC-GBP": _metadata("BTC-GBP", "Crypto", "GBP", "GBP", "1", "Crypto", "24/7", "yfinance fast_info/history verified 2026-07-20"),
    "ETH-GBP": _metadata("ETH-GBP", "Crypto", "GBP", "GBP", "1", "Crypto", "24/7", "yfinance fast_info/history verified 2026-07-20"),
    "IUSA.L": _metadata("IUSA.L", "ETF", "GBP", "GBp", "0.01", "LSE", "XLON", "yfinance fast_info/history verified 2026-07-20"),
    "VWRL.L": _metadata(
        "VWRL.L", "ETF", "GBP", "GBP", "1", "LSE", "XLON",
        "yfinance fast_info/history verified GBP provider unit 2026-07-20",
    ),
    "SGLN.L": _metadata("SGLN.L", "Commodity", "GBP", "GBp", "0.01", "LSE", "XLON", "yfinance fast_info/history verified 2026-07-20"),
    "AAPL": _metadata("AAPL", "Equity", "USD", "USD", "1", "NASDAQ", "XNAS", "yfinance fast_info/history verified 2026-07-20"),
    "MSFT": _metadata("MSFT", "Equity", "USD", "USD", "1", "NASDAQ", "XNAS", "yfinance fast_info/history verified 2026-07-20"),
    "NVDA": _metadata("NVDA", "Equity", "USD", "USD", "1", "NASDAQ", "XNAS", "yfinance fast_info/history verified 2026-07-20"),
    "TSLA": _metadata("TSLA", "Equity", "USD", "USD", "1", "NASDAQ", "XNAS", "yfinance fast_info/history verified 2026-07-20"),
}


def get_instrument_metadata(symbol: str, *, require_supported: bool = True) -> InstrumentMetadata:
    key = str(symbol or "").strip()
    if key not in INSTRUMENT_REGISTRY:
        raise KeyError(f"missing instrument metadata: {key}")
    metadata = INSTRUMENT_REGISTRY[key]
    metadata.validate()
    if require_supported and not metadata.supported:
        raise ValueError(f"instrument is not verified for canonical execution: {key}")
    return metadata


def validate_registry() -> dict:
    errors = {}
    for symbol, metadata in INSTRUMENT_REGISTRY.items():
        try:
            metadata.validate()
            if not metadata.supported:
                errors[symbol] = "unsupported pending provider verification"
        except Exception as exc:
            errors[symbol] = str(exc)
    return {"valid": not errors, "errors": errors, "symbols": len(INSTRUMENT_REGISTRY)}
