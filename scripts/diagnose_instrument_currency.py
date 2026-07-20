from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canonical_accounting.currency import normalize_price_to_major_unit
from canonical_accounting.instruments import INSTRUMENT_REGISTRY


def diagnose(symbol, downloader=None):
    metadata = INSTRUMENT_REGISTRY[symbol]
    if downloader is None:
        import yfinance as yf
        cache_dir = ROOT / ".tmp" / "yfinance-currency-diagnostic"
        cache_dir.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache_dir))
        ticker = yf.Ticker(metadata.provider_symbol)
        history = ticker.history(period="5d", interval="1h", auto_adjust=True)
        provider = ticker.fast_info
        provider_currency = provider.get("currency")
        provider_exchange = provider.get("exchange")
    else:
        history, provider_currency, provider_exchange = downloader(metadata.provider_symbol)
    if history.empty:
        raise RuntimeError(f"no provider price for {symbol}")
    raw_price = history["Close"].dropna().iloc[-1]
    timestamp = history["Close"].dropna().index[-1]
    result = {
        "symbol": symbol, "provider_symbol": metadata.provider_symbol,
        "provider_reported_currency": provider_currency,
        "provider_reported_exchange": provider_exchange,
        "raw_provider_price": float(raw_price), "price_timestamp": str(timestamp),
        "selected_price_scale": str(metadata.price_scale),
        "metadata_source": metadata.metadata_source,
        "supported": metadata.supported,
    }
    try:
        result["normalized_major_unit_price"] = str(
            normalize_price_to_major_unit(raw_price, metadata)
        )
    except Exception as exc:
        result["normalized_major_unit_price"] = None
        result["verification_error"] = str(exc)
        result["supported"] = False
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only provider currency/unit diagnostic.")
    parser.add_argument("symbols", nargs="*", default=sorted(INSTRUMENT_REGISTRY))
    args = parser.parse_args(argv)
    results = []
    for symbol in args.symbols:
        try:
            results.append(diagnose(symbol))
        except Exception as exc:
            results.append({"symbol": symbol, "error": str(exc), "supported": False})
    print(json.dumps(results, indent=2))
    return 0 if all(
        "error" not in item and "verification_error" not in item
        for item in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
