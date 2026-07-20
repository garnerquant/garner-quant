# Canonical Accounting v2

## Policy and boundary

Canonical Accounting v2 establishes a prospective GBP accounting boundary. The
portfolio base currency and paper-account currency are GBP. Existing flat-file
history remains byte-for-byte unchanged, is classified as legacy nominal history,
and is excluded from canonical totals because it lacks execution-time FX metadata
and consistent provider-price-unit metadata.

There is no performance continuity across this boundary. A new generation starts
with GBP 10,000 cash, no positions, zero realised P&L, and zero return. Existing
positions are not imported because their verified GBP cost bases are unavailable.

## Generation layout

```text
data/accounting_generations/
  accounting_generation.json
  generations/<generation_id>/
    state_manifest.json
    trade_ledger_v2.csv
    paper_portfolio_v4.csv
    holdings_report_v2.csv
    broker_account_v2.csv
    paper_tracker_v2.csv
    legacy_classification.json
    instrument_registry_snapshot.json
```

The pointer is the only activation marker. Readers validate pointer/manifest
identity, completion status, exact schemas, row counts, SHA-256 hashes, and GBP base
currency. They never combine generations. The manifest is written last. Activation
uses the existing atomic JSON writer and runtime write lock.

## Currency and price units

`instrument_currency` is the major currency in which the instrument is quoted.
`provider_price_unit` describes the actual numeric unit returned by the provider;
it is independent of the exchange convention. `listing_unit` records the declared
listing convention. `price_scale` converts provider price into the instrument's
major currency.

- GBP or USD major-unit prices use scale `1`.
- GBp prices use scale `0.01`.
- `12,345 GBp` therefore becomes `GBP 123.45`.
- No scale is inferred from `.L` or another symbol suffix.

All nine registry entries were verified against Yahoo `fast_info` and timestamped
history on 20 July 2026. VWRL.L explicitly reports GBP and is therefore configured
with provider unit GBP and scale 1; this is ticker-specific evidence, not `.L`
inference. USD execution additionally requires an acceptable current FX quote.
Unsupported assets fail closed.

## FX convention and freshness

Rates are expressed as target GBP per unit of source currency. A USD-to-GBP rate of
`0.80` means `USD 250 = GBP 200`. The configured Yahoo symbols are `USDGBP=X` and
`EURGBP=X`; inversion is explicit and retains an `inverse(...)` direction marker.

`FX_MAX_AGE_SECONDS` defaults to 10,800 seconds. Future timestamps may be no more
than `FX_FUTURE_TOLERANCE_SECONDS` (300 seconds) ahead of the valuation clock.
Provider timestamps are retained. Missing, stale, future-dated, zero, negative,
NaN, infinite, unsupported, or directionally incorrect quotes fail closed.

## Precision and accounting

Currency normalization and FX conversion use `Decimal` created from string values.
No quantization is applied during calculation, preserving conversion and FIFO
precision. Display may round to two decimals, but the existing GBP 0.01
reconciliation guard is not weakened. Quantities retain full precision.

Purchases retain native gross, native fee, entry FX, base gross, and base fee. FIFO
open cost basis is the execution-time base gross plus entry fee. Sales retain exit
FX and base proceeds. Partial closes allocate entry and exit fees proportionally
exactly once. Current market value uses valuation-time FX; historical cost basis is
never recomputed with current FX.

## Legacy classification

The dry-run tool emits a machine-readable sidecar containing each legacy file's
hash, schema, date range, row count, currencies, ambiguities, classification, and
exclusion reason. The ledger and tracker are classified `Ambiguous`, not corrupt:
their nominal arithmetic is internally consistent but economically unverified.

## Instrument registry and diagnostics

Add instruments only in `canonical_accounting/instruments.py`. Every entry must
declare symbol, provider symbol, provider, asset class, instrument currency,
provider price unit, listing unit, scale, exchange, market calendar, FX requirement,
support status, metadata source, and metadata version.

Run the read-only diagnostic before changing support status:

```powershell
python scripts/diagnose_instrument_currency.py AAPL MSFT
```

The diagnostic records provider currency/exchange, raw price, provider timestamp,
selected scale, normalized price, and metadata source. Provider failure leaves the
instrument unsupported.

## Dry run, activation, and rollback

Dry run creates and deletes isolated proposed state and rechecks legacy hashes:

```powershell
python scripts/prepare_accounting_generation.py --generation-id acct-v2-YYYYMMDDTHHMMSSZ
```

To retain a reviewed proposal, provide a path under the generation root:

```powershell
python scripts/prepare_accounting_generation.py --generation-id acct-v2-YYYYMMDDTHHMMSSZ --keep-dir data/accounting_generations/generations/acct-v2-YYYYMMDDTHHMMSSZ
```

Activation is a separate explicit operation:

```powershell
python scripts/prepare_accounting_generation.py --generation-id acct-v2-YYYYMMDDTHHMMSSZ --activate
```

Rollback removes the active pointer by moving it to a timestamped recoverable backup:

```powershell
python scripts/prepare_accounting_generation.py --deactivate
```

Do not activate while `execution_ready` is false. Activation does not import legacy
history and does not by itself enable paper execution.

## Operator checks

Before supervised paper execution resumes, verify:

1. Every tradable instrument is supported and provider-verified.
2. Every required FX quote is present, directionally correct, and fresh.
3. The generation is complete, hash-valid, and explicitly active.
4. Cash, positions, holdings, broker state, and tracker reconcile in GBP.
5. Dashboard reports the active generation ID and verified GBP labels.
6. Legacy history remains separately labelled and hash-identical.
7. Runtime health is current and successful.
8. `execution_ready` has been set only through an audited generation build.

## Troubleshooting

- “no active canonical accounting generation”: run a dry run and review it; do not
  bypass the pointer requirement.
- “instrument is not verified”: run the provider diagnostic and update registry
  metadata only from an authoritative result.
- “FX quote is stale”: obtain a new provider quote; never change its timestamp.
- Hash/schema mismatch: reject the generation and rebuild it; never repair published
  artifacts in place.
- Provider unavailable: remain monitor-only. Identity FX is permitted only for an
  exact source/target currency match.
