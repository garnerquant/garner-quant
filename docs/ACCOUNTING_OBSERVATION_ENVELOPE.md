# Accounting observation envelope

The accounting observation envelope is observational only. Canonical accounting remains **INACTIVE**, and paper and live execution remain disabled.

## Lifecycle

The scheduler supplies an immutable completed-bar identity and timestamp. Strategy evaluation creates an order proposal. The central risk engine evaluates that proposal. In `monitor_only`, the observer combines the proposal, risk context, decision, instrument registry, and explicit replay-policy registry into one frozen envelope, validates it, appends it durably, and stops. It never calls an execution adapter, legacy accounting writer, successor-generation writer, or pointer publisher.

Invalid observations are not envelopes. A safe diagnostic is appended separately so Operations reports missing authoritative fields while the invalid payload is excluded from future replay.

## Schema and serialization

Schema `1.0` contains event/proposal/decision identity; strategy identity and version; instrument, venue, asset class, price units, precision and lot policy; native/base currencies; FX rate, time, and source; market, valuation, planned-execution, and creation times; fees and costs; cash/position impacts; projected exposure evidence; the complete risk decision; configuration version; inactive accounting status; scheduler bar; and monitor-only runtime state.

Decimals and UTC timestamps have canonical string representations. JSON keys are sorted with compact separators. SHA-256 covers the canonical serialization. Records are append-only and duplicate event IDs are idempotent only when their hashes match. Schema changes require a new version and a backwards-compatible reader.

## Producers

Current production producers are monitor-only BUY and SELL proposal evaluations in `execution.portfolio_manager`. No production producers presently exist for deposits, withdrawals, dividends, standalone fees, FX adjustments, or corporate actions. Those future producers must supply every field directly and use the same validation/store boundary; missing data must never be inferred.

Foreign-currency observations require an authoritative FX rate, timestamp, and named source. Until the production market-data path supplies those together, USD observations are recorded as validation failures rather than replayable envelopes. EUR instruments also remain blocked until explicit instrument and replay metadata exists.

## Future replay

Future canonical replay may consume only validated envelopes with recognized schema/configuration versions and complete metadata. An opening canonical snapshot, cash-flow producers, verified foreign FX provenance, and sustained observation coverage remain prerequisites. Envelope storage does not activate or publish any accounting generation.
