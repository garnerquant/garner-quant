# Verified canonical opening snapshot candidate

The candidate is inactive. Canonical accounting remains inactive. No production pointer is created, no production generation is published, and historical accounting is not rewritten. Validation and approval do not equal activation. Trading remains disabled.

## Production source audit

| Source | Classification | Evidence and limitation |
|---|---|---|
| `trade_ledger_v1.csv` | AUTHORITATIVE for accepted legacy fills only | Stable event IDs and FIFO evidence, but no historical strategy ID or execution-time FX; insufficient for a canonical opening state. |
| `trade_transactions_v1.csv` and journals | CORROBORATING | Legacy transaction evidence, same strategy/FX limitations. |
| `paper_portfolio_v3.csv` | DERIVED | Mutable projection, not lot authority. |
| `holdings_report.csv`, `broker_account.csv`, tracker | DERIVED | Runtime valuations/reconciliation outputs with mixed as-of times. |
| instrument and replay registries | AUTHORITATIVE metadata | Explicit symbols, currencies, units, scales, venues, calendars, and replay precision. |
| accounting observation envelopes | AUTHORITATIVE prospectively when valid | Current history is insufficient to reconstruct the legacy opening state. |
| reconciliation reports | DERIVED | Comparison evidence only. |
| repair scripts/artifacts | REPAIR_ONLY | Never ordinary opening evidence. |
| migration scripts/artifacts | MIGRATION_ONLY | Never ordinary trade/lot authority. |
| tests and fixtures | TEST_ONLY | Used only in isolated validation. |

There is no authoritative historical strategy-allocation record, acquisition-FX archive, dividend/fee/tax history, or approved opening allocation. Consequently no production candidate is built by this change.

## Cut-off and manifest

`CutOffContract` requires an operator-selected timezone-aware administrative, intraday, end-of-day, or end-of-session boundary. It records session/bar identity, each source as-of time, valuation time, FX policy, configuration and registry versions, and the exact source-manifest hash. Nothing chooses a production cut-off automatically.

The deterministic manifest contains only explicitly classified authoritative sources. Each entry records stable identity, schema, size, rows, modification/extraction times, content hash, event range, completeness, authority, and writer. Derived, repair, migration, test, corroborating, and unsupported sources cannot establish authority. Post-cut-off records and incomplete sources fail closed.

## Candidate semantics

The frozen schema separates cash by currency and settlement restriction; strategy-scoped positions; authoritative FIFO or explicitly classified opening-migration lots; realised/unrealised trading P&L; dividends; fees; withholding; external flows; realised/valuation FX; migration adjustments; and unknown historical P&L. Migration adjustments never become trading P&L. Unknown P&L remains an unresolved blocker.

Instrument identity and price scale come from the explicit registry. GBp is a price unit with scale `0.01`, never a currency. Foreign acquisition and valuation FX evidence are distinct and require rate, time, source, and unambiguous policy. GBP uses explicit identity conversion. Every position is strategy-scoped, lot quantities reconcile within strategy, and unattributed state blocks readiness.

## Reconciliation and readiness

Independent reconciliation records every compared metric, scope, values, absolute/percentage difference, currency, severity, classification, evidence, explanation, and blocking flag. Exact and tolerance-level rounding are recognized; material unexplained differences remain `UNKNOWN` and block freezing/readiness. Cash, positions, lots, cost, P&L components, exposure, strategy exposure, and equity are compared.

Readiness always remains `NOT_READY` while canonical accounting is inactive, sustained replay evidence is absent, approval is missing, attribution/FX coverage is incomplete, unresolved items exist, or reconciliation blocks.

## Approval and inactive artifacts

Approval records permit only `APPROVED_FOR_REPLAY_TESTING`, `REJECTED`, or `CHANGES_REQUIRED` and bind to exact candidate and reconciliation hashes. No production-activation decision exists. Operator identity cannot currently be authenticated through an approved offline mechanism, so no approval command is exposed.

Validated, non-blocking fixture candidates can be frozen into a separate content-addressed candidate directory. The API refuses overwrite and invalid/unreconciled candidates. Runtime accounting readers do not inspect this directory. There is no CLI, dashboard write control, pointer operation, successor publication, execution adapter, or broker integration.

The smallest safe next action is to obtain an approved strategy-allocation record and historical acquisition-FX/fee/dividend/tax evidence, choose an operator-approved quiescent cut-off, and run an authenticated dry-run review before persisting any production candidate.
