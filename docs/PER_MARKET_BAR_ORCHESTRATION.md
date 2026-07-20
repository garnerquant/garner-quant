# Per-market completed-bar orchestration

## Why this exists

Previously, the five-minute runtime treated `open_markets(...)` as a global
authorization switch. Because crypto is continuously open, CRYPTO could make the
switch true on weekends and `main_v2` would then evaluate every configured asset.
Exit confirmation used a wall-clock run timestamp, so repeated polling could count
the same daily strategy observation more than once.

The runtime now separates four facts:

1. whether a market is open for monitoring;
2. whether an instrument has a new completed strategy bar;
3. whether that exact versioned bar has been claimed and evaluated;
4. whether execution is permitted by configuration and canonical accounting.

Market-open status is informational and never authorizes another instrument.

## Instrument policies

Policies are built from the canonical instrument registry. No calendar is inferred
from a suffix.

| Instruments | Calendar | Daily completion |
|---|---|---|
| IUSA.L, VWRL.L, SGLN.L | XLON | Official exchange session close |
| AAPL, MSFT, NVDA, TSLA | XNAS | Official exchange session close |
| BTC-GBP, ETH-GBP | 24/7 | 00:00 UTC, closing the previous UTC day |

`exchange-calendars` supplies holidays, early closes, DST-aware opens/closes and
session membership. Equity/ETF bars must match an official session close exactly.
The maximum scheduling lag is six hours for exchange-traded instruments and
twelve hours for crypto; stale missed bars fail closed instead of being replayed
on a later weekend. Crypto availability is continuous, but strategy evaluation
remains once per completed UTC daily bar.

Daily provider indices are interpreted only as session labels by the acquisition
adapter. They are mapped to explicit UTC close timestamps. APIs accepting actual
bar timestamps reject timezone-naive values.

## Bar identity

Every identity contains:

- symbol;
- timeframe;
- UTC bar-close timestamp;
- strategy version;
- configuration version;
- data source;
- optional data revision.

The canonical key is a SHA-256 hash of the sorted identity fields. A strategy or
configuration version change intentionally creates a new identity.

## Durable processing state

State is stored at `data/runtime/processed_strategy_bars.json`, protected by the
unified runtime write lock and the atomic JSON writer. It is runtime state and is
not committed.

Statuses are:

- `DISCOVERED`
- `VALIDATED`
- `SIGNAL_COMPUTED`
- `NO_ACTION`
- `EXECUTION_BLOCKED`
- `EXECUTED`
- `FAILED_RETRYABLE`
- `FAILED_FINAL`

Terminal and in-progress identities cannot be claimed again. A failed pre-execution
bar can be retried only after an explicit `FAILED_RETRYABLE` transition. Prepared
execution records retain deterministic related event IDs; the ledger remains the
final duplicate-event guard. Lock contention fails closed, so concurrent runtime
instances cannot both own the same bar.

## Confirmation semantics

The exit-confirmation check ID is now the versioned bar-identity key supplied by the
scheduler. Repeated five-minute polls and restarts therefore do not increment a
daily confirmation. There is no separate entry-confirmation counter in the current
strategy; entry evaluation is protected by the same durable bar claim.

## Runtime and dashboard

Runtime health publishes per-instrument scheduler decisions, eligible symbols,
last status, duplicate suppression counts, scheduler lag, next evaluation time,
strategy/config versions, and failure reasons. The dashboard reads this state
without writes and distinguishes scheduler state from market-open state.

Monitor-only operation records `EXECUTION_BLOCKED` decisions without submitting
trades. Paper execution remains disabled. `main_v2` refuses the old unscoped
all-asset call and accepts only scheduler-selected symbols and bar identities.

## Failure policy

An instrument fails closed for missing policy or registry metadata, unsupported
calendar/timeframe, timezone-naive/future/incomplete/stale bars, corrupt state,
lock failure, or missing versions. A missing bar for one instrument does not make
another symbol eligible. Corruption of the shared state file blocks scheduling until
the atomic recovery procedure restores a valid document.
