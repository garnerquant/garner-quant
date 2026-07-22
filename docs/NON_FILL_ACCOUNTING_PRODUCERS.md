# Observational non-fill accounting producers

These producers are observational only. Canonical accounting remains **INACTIVE**. No event changes cash, positions, P&L, or equity. No production pointer is created or modified. Paper and live trading remain disabled.

## Audit and architecture

The repository has no authoritative production source for deposits, withdrawals, dividends, standalone fees, FX conversions/revaluations, or corporate actions. Existing reconciliation, migration, repair, report, and dashboard paths are not event producers and are deliberately excluded. The sole registered producer, `controlled-non-fill-import` version `1.0`, is internal-only and has `production_source_available=False`. There is no scheduled job, public endpoint, Streamlit control, broker importer, or automatic inference path.

An authorised caller constructs a frozen `NonFillEventRequest`. Validation resolves the explicit producer registry and replay instrument policy, creates the existing schema-1.0 `AccountingObservationEnvelope`, appends it to the existing observation store, and stops. Invalid requests are excluded from the valid store and written as diagnostics when their received timestamp and storage are usable.

## Shared contract and authority

Every request carries stable source-event, producer, source-system, reference, correlation, strategy, instrument, currency, amount/quantity, effective/source/received/valuation, FX, reason, configuration, runtime, and schema fields. Supporting metadata is normalized to an immutable sorted tuple of scalar pairs. Decimal values must be finite; timestamps must be timezone-aware UTC; unknown constructor fields fail through the typed API.

Authority requires a registered producer ID/version, explicit source system and reference, and a description of how authority was established. Identical source IDs are idempotent; different content under the same ID conflicts and fails closed.

## Event semantics

- `DEPOSIT`: positive absolute input, positive cash impact, zero position impact, external flow—not performance.
- `WITHDRAWAL`: positive absolute input, derived negative cash impact, zero position impact, external flow—not loss.
- `DIVIDEND`: explicit strategy/allocation and entitlement reference; gross equals net plus separately recorded withholding. Net cash is performance. Withholding is not a standalone fee.
- `FEE`: positive absolute input and derived negative cash impact. Category and portfolio/strategy attribution are mandatory. Fill-linked fees are rejected to prevent duplication.
- `FX_ADJUSTMENT`: `REALISED_CONVERSION` records from/to amounts and an explicit `TO_PER_FROM` executed rate; amounts must reconcile. `VALUATION_ONLY` records no cash amounts or movement. Neither mutates balances.
- `CORPORATE_ACTION`: typed split, reverse split, symbol change, merger, spin-off, return of capital, stock dividend, or delisting. Ratios and destination instruments are mandatory where applicable. `OTHER_UNSUPPORTED` and incomplete terms produce diagnostics, never valid envelopes.

GBP uses identity FX. Foreign-currency requests require rate, timestamp, and source. Rates are never inferred from balances. Strategy attribution is explicit: `ACCOUNT` for portfolio cash flows, `PORTFOLIO`/`STRATEGY` for fees, and `STRATEGY`/`EXPLICIT_ALLOCATION` plus entitlement evidence for dividends.

## Storage and invocation

The API has no update or delete method. Canonical serialization and SHA-256 hashing are deterministic. Valid records append durably; conflicts fail closed. A storage failure fails only the explicitly invoked observation operation and can never authorize execution or mutate accounting. Operations reports degraded health when persisted invalid diagnostics exist.

There is intentionally no production CLI because no approved source exists. A future administrative importer must default to dry-run, show the envelope and hash before an explicit observation-only append, authenticate its operator/source, and remain wholly separate from accounting publication and execution.

Future replay additionally requires approved production sources, sustained envelope coverage, verified foreign FX provenance, and an opening canonical snapshot. No producer in this subsystem publishes or activates a generation.
