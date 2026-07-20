from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canonical_accounting.currency import (
    CurrencyError, FxQuote, InstrumentMetadata, base_market_value,
    convert_amount_to_base, inverse_fx_quote, normalize_price_to_major_unit,
)
from canonical_accounting.gate import canonical_execution_block_reason
from canonical_accounting.generation import (
    LEDGER_COLUMNS, build_cash_only_generation, load_active_generation,
    load_generation, sha256_file,
)
from canonical_accounting.instruments import get_instrument_metadata
from canonical_accounting.ledger import CanonicalLedgerError, append_event, fifo_accounting
from canonical_accounting.valuation import portfolio_totals, value_position
from dashboard.accounting_reader import load_dashboard_accounting
from runtime.live_runtime import paper_execution_blocked_reason


NOW = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
MAX_AGE = timedelta(hours=3)
FUTURE = timedelta(minutes=5)


def check(condition, message, issues):
    if not condition:
        issues.append(message)
    print(("PASS" if condition else "FAIL") + f": {message}")


def expect_error(call, text, issues):
    try:
        call()
    except Exception:
        check(True, text, issues)
    else:
        check(False, text, issues)


def metadata(symbol="TEST", currency="USD", unit="USD", scale="1"):
    return InstrumentMetadata(symbol, "fixture", "fixture", symbol, currency, unit, unit,
                              Decimal(scale), "TEST", "24/7", currency != "GBP", True,
                              "fixture")


def quote(source="USD", target="GBP", rate="0.8", timestamp=NOW):
    return FxQuote(source, target, Decimal(rate), timestamp, "fixture", f"{source}->{target}")


def event(event_id, kind, quantity, native_price, rate, base_gross, fee="0", base_fee="0"):
    return {
        "event_id": event_id, "accounting_generation": "fixture", "schema_version": "2.0",
        "timestamp": NOW.isoformat(), "symbol": "USDTEST", "event_type": kind,
        "quantity": str(quantity), "native_execution_price": str(native_price),
        "instrument_currency": "USD", "provider_price_unit": "USD", "listing_unit": "USD",
        "price_scale": "1", "normalized_native_price": str(native_price),
        "native_gross_amount": str(Decimal(str(quantity)) * Decimal(str(native_price))),
        "fee_amount": str(fee), "fee_currency": "USD", "fx_rate_to_base": str(rate),
        "fx_timestamp": NOW.isoformat(), "fx_source": "fixture",
        "conversion_direction": "USD->GBP", "base_gross_amount": str(base_gross),
        "base_fee": str(base_fee), "base_cash_movement": "0", "base_realised_pnl": "0",
        "strategy_version": "fixture",
    }


def main():
    issues = []
    identity = convert_amount_to_base(Decimal("25"), "GBP", quote=None, as_of=NOW,
                                      max_age=MAX_AGE, future_tolerance=FUTURE)
    check(identity.converted_amount == Decimal("25") and identity.fx_rate == 1,
          "GBP identity conversion is exact", issues)
    usd = convert_amount_to_base(Decimal("250"), "USD", quote=quote(), as_of=NOW,
                                 max_age=MAX_AGE, future_tolerance=FUTURE)
    check(usd.converted_amount == Decimal("200"), "USD 250 at 0.80 equals GBP 200", issues)
    inv = inverse_fx_quote(quote("GBP", "USD", "1.25"))
    check(inv.rate == Decimal("0.8") and inv.source_currency == "USD",
          "FX inversion is directionally explicit and exact", issues)
    gbp_minor = metadata(currency="GBP", unit="GBp", scale="0.01")
    check(normalize_price_to_major_unit("12345", gbp_minor) == Decimal("123.45"),
          "GBp normalizes to GBP through metadata scale", issues)
    check(base_market_value("10", "12345", gbp_minor, quote=None, as_of=NOW,
                            max_age=MAX_AGE, future_tolerance=FUTURE).converted_amount == Decimal("1234.50"),
          "GBp quantity times normalized price equals GBP 1234.50", issues)
    gbp = metadata(currency="GBP", unit="GBP", scale="1")
    check(normalize_price_to_major_unit("100", gbp) == Decimal("100"),
          "GBP major-unit price is not scaled", issues)
    check(get_instrument_metadata("BTC-GBP", require_supported=False).provider_price_unit == "GBP",
          "GBP-quoted crypto has explicit major-unit metadata", issues)
    check(get_instrument_metadata("IUSA.L", require_supported=False).price_scale == Decimal("0.01"),
          "ticker metadata explicitly overrides suffix inference", issues)
    check(
        get_instrument_metadata("VWRL.L").provider_price_unit == "GBP"
        and get_instrument_metadata("VWRL.L").price_scale == Decimal("1"),
        "VWRL uses its explicitly provider-verified GBP unit, not suffix inference",
        issues,
    )
    expect_error(lambda: get_instrument_metadata("MISSING"), "missing instrument metadata blocks execution", issues)

    for bad, label in [(None, "missing"), ("0", "zero"), ("-1", "negative"),
                       ("NaN", "NaN"), ("Infinity", "infinite")]:
        q = None if bad is None else quote(rate=bad)
        expect_error(lambda q=q: convert_amount_to_base(1, "USD", quote=q, as_of=NOW,
                     max_age=MAX_AGE, future_tolerance=FUTURE), f"{label} FX rate fails closed", issues)
    expect_error(lambda: convert_amount_to_base(1, "JPY", quote=None, as_of=NOW,
                 max_age=MAX_AGE, future_tolerance=FUTURE), "unsupported currency fails closed", issues)
    expect_error(lambda: convert_amount_to_base(1, "USD", quote=quote(timestamp=NOW-timedelta(hours=4)),
                 as_of=NOW, max_age=MAX_AGE, future_tolerance=FUTURE), "stale FX fails closed", issues)
    expect_error(lambda: convert_amount_to_base(1, "USD", quote=quote(timestamp=NOW+timedelta(minutes=6)),
                 as_of=NOW, max_age=MAX_AGE, future_tolerance=FUTURE), "future FX fails closed", issues)
    expect_error(lambda: normalize_price_to_major_unit(1, metadata(unit="UNKNOWN")),
                 "ambiguous provider price unit fails closed", issues)

    frame = pd.DataFrame(columns=LEDGER_COLUMNS)
    buy_a = event("buy-a", "BUY", "10", "25", "0.8", "200", fee="1", base_fee="0.8")
    buy_b = event("buy-b", "BUY", "10", "25", "0.75", "187.5")
    sell = event("sell", "SELL", "15", "30", "0.7", "315", fee="2", base_fee="1.4")
    for item in (buy_a, buy_b, sell):
        frame = append_event(frame, item)
    result = fifo_accounting(frame)
    expected = (Decimal("210")-Decimal("0.9333333333333333333333333333")-Decimal("200.8")) + (Decimal("105")-Decimal("0.4666666666666666666666666667")-Decimal("93.75"))
    check(abs(result["base_realised_pnl"] - expected) < Decimal("1e-24"),
          "FIFO partial sale retains entry/exit FX and allocates fees once", issues)
    check(len(result["open_lots"]) == 1 and result["open_lots"][0]["remaining_quantity"] == Decimal("5"),
          "multiple fills with different FX retain correct open quantity", issues)
    expect_error(lambda: append_event(frame, sell), "duplicate canonical event is rejected", issues)
    check(usd.fx_timestamp == NOW and usd.fx_source == "fixture",
          "conversion metadata survives conversion result", issues)
    fee = convert_amount_to_base(Decimal("2.50"), "USD", quote=quote(), as_of=NOW,
                                 max_age=MAX_AGE, future_tolerance=FUTURE)
    check(fee.converted_amount == Decimal("2.000"), "native fee converts once to GBP", issues)
    positions = [
        value_position(symbol="GBP", quantity=2, raw_price=100, metadata=gbp,
                       base_cost_basis=180, quote=None, as_of=NOW,
                       max_age=MAX_AGE, future_tolerance=FUTURE),
        value_position(symbol="GBp", quantity=10, raw_price=12345, metadata=gbp_minor,
                       base_cost_basis=1200, quote=None, as_of=NOW,
                       max_age=MAX_AGE, future_tolerance=FUTURE),
        value_position(symbol="USD", quantity=10, raw_price=25, metadata=metadata(),
                       base_cost_basis=190, quote=quote(), as_of=NOW,
                       max_age=MAX_AGE, future_tolerance=FUTURE),
    ]
    totals = portfolio_totals(Decimal("1000"), positions)
    check(totals["base_positions_value"] == Decimal("1634.50")
          and totals["base_total_equity"] == Decimal("2634.50"),
          "mixed GBP, GBp, and USD portfolio totals only in base currency", issues)
    check(totals["base_unrealised_pnl"] == Decimal("64.50"),
          "base unrealised PnL uses current base value minus retained base cost", issues)

    root = ROOT / ".tmp" / "canonical_currency_validation"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        for name, content in {
            "trade_ledger_v1.csv": "timestamp,currency,value\n2026-01-01,USD,1\n",
            "paper_portfolio_v3.csv": "ticker,position_value\nAAPL,1\n",
            "holdings_report.csv": "date,market_value\n2026-01-01,1\n",
            "broker_account.csv": "cash,portfolio_value\n1,1\n",
            "paper_30_day_tracker.csv": "date,portfolio_value\n2026-01-01,1\n",
        }.items():
            (root/name).write_text(content, encoding="utf-8")
        before = {name: sha256_file(root/name) for name in content_files(root)}
        generation_path = root/"state"/"generations"/"fixture"
        manifest = build_cash_only_generation(generation_path, generation_id="fixture", legacy_root=root,
                                               activated_at=NOW)
        bundle = load_generation(generation_path, "fixture")
        check(len(bundle.ledger) == 1 and bundle.ledger.iloc[0]["event_type"] == "OPENING_CASH",
              "opening cash initializes generation without historical trades", issues)
        check(bundle.portfolio.empty and float(bundle.broker.iloc[0]["base_total_equity"]) == 10000,
              "cash-only opening state reconciles at GBP 10000", issues)
        check(manifest["performance_reset"] and float(bundle.tracker.iloc[0]["performance_from_activation_pct"]) == 0,
              "performance resets at generation activation", issues)
        after = {name: sha256_file(root/name) for name in content_files(root)}
        check(before == after, "legacy source hashes remain byte-identical", issues)
        classification = __import__("json").loads((generation_path/"legacy_classification.json").read_text())
        excluded = all(not row["included_in_canonical_accounting"] for row in classification["sources"])
        check(excluded, "legacy rows are excluded from canonical totals", issues)
        (root/"state"/"accounting_generation.json").write_text('{"generation_id":"fixture"}', encoding="utf-8")
        active = load_active_generation(root/"state")
        dashboard = load_dashboard_accounting(root/"state")
        check(active.generation_id == dashboard.generation_id == "fixture" and float(dashboard.broker.iloc[0]["portfolio_value"]) == 10000,
              "dashboard consumes only the active canonical generation", issues)
        expect_error(lambda: load_active_generation(root/"missing"), "missing active generation blocks execution", issues)
        block = canonical_execution_block_reason(state_root=root/"state", runtime_status_path=root/"missing-status.json")
        check(block is not None, "inactive execution-ready flag blocks paper execution", issues)
        ledger_path = generation_path/"trade_ledger_v2.csv"
        original = ledger_path.read_bytes()
        ledger_path.write_bytes(original+b"\n")
        expect_error(lambda: load_generation(generation_path, "fixture"), "artifact hash validation detects mutation", issues)
        ledger_path.write_bytes(original)
        check(load_generation(generation_path, "fixture").generation_id == "fixture",
              "restored generation reloads with conversion metadata", issues)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    source = (ROOT/"dashboard/accounting_reader.py").read_text(encoding="utf-8")
    check("to_csv" not in source and "atomic_write" not in source,
          "dashboard accounting reader is read-only", issues)
    runtime_source = (ROOT/"runtime/live_runtime.py").read_text(encoding="utf-8")
    check("canonical_execution_block_reason" in runtime_source,
          "runtime execution path invokes canonical accounting gate", issues)
    enabled_config = {
        "mode": "paper_execution", "allowed_modes": ["paper_execution"],
        "paper_execution_enabled": True, "_config_exists": True,
    }
    check("canonical accounting gate" in paper_execution_blocked_reason(
              enabled_config, ["CRYPTO"], execution_log={}, now=NOW
          ), "paper execution cannot bypass a missing active generation", issues)

    if issues:
        print(f"Canonical currency validation failed: {len(issues)} issue(s)")
        return 1
    print("Canonical currency and generation validation passed.")
    return 0


def content_files(root):
    return [path.name for path in Path(root).glob("*.csv")]


if __name__ == "__main__":
    raise SystemExit(main())
