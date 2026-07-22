# Transactional canonical accounting

Canonical accounting remains **INACTIVE**. Paper and live execution remain disabled. This architecture is an inert, fail-closed foundation for a future, separately approved activation.

## Generation lifecycle

An accepted immutable `AccountingEvent` references the currently published generation. Under one accounting writer lock, the transaction loads and verifies that generation, replays its event journal plus the new event in memory, and creates a successor in a staging directory. The successor contains the canonical snapshot, event journal, FIFO lots, equity history, dual-run comparison, projections, and an immutable manifest containing every artifact hash, its parent, lineage depth, manifest hash, and validation hash.

The staging generation is loaded and validated before its directory is atomically renamed. Publication is a separate atomic pointer replacement and is disabled by default. A crash before pointer replacement leaves the previous generation active; a fully written but unpublished successor is inert and can be inspected or explicitly published later. Existing generations are never edited.

## Event model and idempotency

Events support `BUY_FILL`, `SELL_FILL`, `DEPOSIT`, `WITHDRAWAL`, `FEE`, `DIVIDEND`, `FX_ADJUSTMENT`, and future-compatible `CORPORATE_ACTION` records. Each record carries an event ID, UTC timestamp, authoritative strategy ID, instrument, currency, amount, quantity, reference generation, correlation ID, source, and explicit FX evidence when conversion is required.

Event IDs are idempotency keys. An exact replay returns the existing result and creates no generation. Reusing an ID with different immutable content fails closed. Stale generation references fail closed.

## Snapshot and strategy identity

`CanonicalPortfolioSnapshot` is the sole projection produced by event replay. It exposes cash, positions, FIFO lots, cost basis, market value, realised and unrealised P&L, equity, gross and net exposure, currency exposure, authoritative strategy exposure, FX metadata, generation identity, and valuation time. Strategy IDs propagate through events, lots, positions, exposure, ledger projections, risk context, and the read-only Operations page; `strategy_version` is retained only as a compatibility projection.

## Cash-flow and performance semantics

- Deposits increase cash and equity but are external flow, not performance.
- Withdrawals decrease cash and equity but are external flow, not performance.
- Buy and sell fills exchange cash and positions; realised market P&L is FIFO-derived.
- Fees reduce cash, equity, and performance and are separately accumulated.
- Dividends increase cash, equity, and performance and are separately accumulated.
- FX adjustments revalue foreign exposure and are separated from market movement.
- Corporate actions currently accept an explicit split operation; unsupported actions fail closed.

Equity history stores external cash flow separately and records flow-adjusted equity. Future drawdown must use a flow-adjusted equity series so deposits and withdrawals cannot masquerade as investment gain or loss.

## Dual run, recovery, and activation

Each successor records a read-only legacy-versus-canonical comparison. Differences are evidence only and are never auto-corrected. Readers validate the selected generation and observe either the old complete generation or the new complete generation—never staging content.

Future activation requires a separate operator-controlled change: sustained dual-run agreement, complete FX and valuation inputs, approved risk limits, successful lineage/manifest validation, and explicit integration of accepted paper fills with the transaction writer. The active pointer must not be changed until those gates pass. No component in this change activates accounting or enables order submission.
