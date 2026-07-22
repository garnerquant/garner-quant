# Opening Snapshot Evidence Pack

The evidence pack is a read-only, deterministic inventory and gap analysis for a possible future canonical opening snapshot. It does not create an opening snapshot candidate, FIFO migration lot, accounting generation, or active pointer. Canonical accounting remains inactive and trading remains disabled.

## Evidence hierarchy

Evidence is classified as authoritative, corroborating, derived, partial, or unavailable. The legacy trade ledger is authoritative for recorded fill events only. Runtime portfolio, holdings, broker, tracker, and reconciliation reports are derived corroboration and cannot independently prove canonical cash, cost, FX, or strategy attribution. Instrument and currency registries prove metadata policy, not historical prices or FX rates. Prospective observation envelopes do not prove events before their introduction.

The inventory records each source's identity, classification, authority, schema fingerprint, writer, update time, content hash, coverage period, and limitations. Its timestamp is explicitly supplied by the caller; identical inputs and timestamp produce identical serialization and hashes.

## Position, FIFO, FX, and strategy evidence

Current positions are compared with reconstructable FIFO quantities from source fills. This analysis records lot evidence but never creates lots. A position is `PROVEN` only when identity, quantity, cost basis, FIFO, valuation, strategy, and FX evidence are all authoritative; `PARTIAL` has some authoritative evidence; `UNPROVEN` cannot reconcile a core fact.

Historical fills do not contain authoritative `strategy_id`, acquisition FX source/timestamp, or quote convention. Registry GBP/GBp policy is not historical FX evidence: GBp is a price unit, while currency remains GBP. Foreign-currency acquisitions require timestamped, directionally explicit source quotes. No FX value is inferred.

## Non-fill and cash-flow evidence

Deposits, withdrawals, dividends, standalone fees, tax/withholding, FX adjustments, and corporate actions require complete source events. Current cash differences, holdings, or fill history are never used to invent them. Fill fee columns do not establish completeness of standalone fees. Dividend entitlement is not inferred from current holdings.

## Gap register and coverage

Each immutable gap has a content-derived ID, severity, affected positions/value/strategies/currencies, required evidence, possible source, operator-action and migration flags, and separate opening-snapshot/replay blockers. Coverage percentages use only fully proven items; partial evidence is deliberately not counted as complete. Overall completeness is the equal-weight mean of position, strategy, FX, FIFO, cash, dividend, fee, and tax coverage.

Readiness is fail-closed and remains `NOT_READY` while blocking evidence gaps exist. Missing evidence requires an authoritative source and explicit operator review. Migration, attribution, or approval work must occur in a separate controlled workflow; this subsystem supplies no approval or mutation interface.

## Operator workflow

Operators review the compact read-only Operations status, investigate critical gaps, obtain authoritative broker/transfer/FX/strategy evidence, and rerun the report with an explicit cut-off time. Future candidate construction may consume separately reviewed evidence only after all blocking gaps are resolved. The evidence pack itself never persists production state.

Canonical accounting remains **INACTIVE**. No event changes cash, positions, P&L, or equity. No production pointer is created or modified. Paper and live trading remain disabled.
