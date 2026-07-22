# Central pre-trade risk engine

The `risk_engine` package is the single mandatory authorisation point for paper-order proposals. It is deterministic, has no execution side effects, and fails closed when any required input is missing, invalid, stale, contradictory, unverified, or cannot be durably audited. Live trading remains disabled and this implementation contains no live broker submission path.

## Lifecycle and architecture

```text
Completed-bar scheduler
  -> strategy (`main_v2`)
  -> typed `OrderProposal`
  -> `PreTradeRiskEngine.evaluate(proposal, context)`
  -> exact, unexpired APPROVED `RiskDecision`
  -> existing runtime and paper-execution gates
  -> atomic paper-ledger/portfolio adapter
```

Strategies still calculate signals and target allocations for compatibility, but they cannot authorise persistence. Immediately before a proposed BUY or SELL mutates order-related state, `execution.portfolio_manager.update_portfolio` builds the typed proposal and calls the central engine. `commit_trade_state` independently verifies that every ledger event has one approval for the exact proposal, configuration hash, quantity, side, symbol and price. Modified or expired approvals are rejected.

The only audited production caller of `update_portfolio` is `main_v2`; the runtime reaches it only through the completed-bar scheduler and existing execution gate. The older `execution.paper_trader` interface remains sandbox-only and default-denied. There is no real-order adapter.

## Decisions and pipeline

Decisions are `APPROVED`, `REJECTED`, `BLOCKED`, or `MONITOR_ONLY`, never a bare boolean. Each includes stable IDs and reason codes, timestamps and expiry, proposal/context/configuration fingerprints, findings, passed/failed/unavailable checks, observed values, limits, accounting generation, market-data timestamps, software/configuration versions, and correlation ID.

Checks run in this order:

1. Proposal identity, instrument registry metadata, market, side, Decimal quantity, order type, prices, time-in-force, currency and duplicate identity.
2. Operational gates: monitor-only, trading enabled, approved configuration, runtime/scheduler/adapter health and durable kill switch.
3. Completed-bar/session state, future timestamps, market/timeframe-specific price freshness, and currency-specific verified FX freshness.
4. Active, verified, reconciled canonical GBP accounting and complete portfolio inputs.
5. Projected cash, order and position notional, concentration, gross/net, open-position, strategy, venue and currency exposure.
6. Verified daily realised loss, daily total P&L loss, and portfolio drawdown.

Machine-readable codes are defined in `risk_engine/reason_codes.py`. An unavailable check never approves. `MONITOR_ONLY` is returned before monetary checks when the runtime is monitor-only. Runtime `LIVE` health is not trading authorisation.

## Configuration and units

`risk_engine/risk_config.json` is strict and versioned. Unknown or missing fields fail loading. Monetary limits are decimal GBP amounts; ratios are decimal fractions from zero to one; freshness and approval expiry are seconds. Freshness keys combine authoritative market calendar and strategy timeframe (for example `XLON:1d`); FX policies are keyed by instrument currency. Production defaults deliberately set both `trading_enabled` and `limits_approved` false. Current numeric limits are conservative safety placeholders, not approved business limits; an operator must review them before any future paper activation.

Configured controls include maximum order notional, instrument position notional and ratio, gross/net exposure, open positions, strategy/market/currency exposure, daily realised and total loss, portfolio drawdown, market/FX freshness, supported order types/time-in-force, approval expiry, and reduction policy. No sector, country, strategy-drawdown, consecutive-loss or cooldown control is inferred because authoritative inputs do not currently exist.

## Accounting, loss and drawdown

Production context consumes the authoritative canonical-accounting reader. Legacy nominal data is never interpreted as GBP. With no active verified generation, affordability/exposure checks are unavailable and execution is blocked. The implementation does not create or activate a generation.

Daily boundaries are the UTC dates supplied by the canonical tracker. Daily realised loss is the change in cumulative realised P&L from the first to latest record for that UTC date. Daily total P&L is the change in canonical portfolio equity over the same records. The high-water mark is the maximum verified canonical portfolio value in the generation's tracker. Deposits/withdrawals are not separately represented, so reliable adjusted drawdown cannot be claimed; missing or inadequate history fails closed. Unrealised P&L is reflected only through verified total equity. Strategy drawdown is unavailable and therefore not invented.

## Reductions and kill switch

SELL proposals cannot exceed verified holdings and short selling is not supported. A true reduction may bypass new-entry concentration/exposure breaches when configured, but structural, data, accounting, operational, audit and kill-switch checks still apply. No liquidation feature was added. The current kill-switch policy blocks all new orders, including reductions; cancellations are outside this ledger-based order path.

The durable state lives under ignored `data/risk_engine/`. Missing, malformed or unreadable state is active/fail-safe. `scripts/manage_risk_kill_switch.py` provides an internal CLI requiring actor, reason and correlation ID. Every transition is appended with its prior/new state and timestamp. There is no public endpoint, automatic reset, or trading enablement when cleared.

## Audit and diagnostics

Each evaluation is appended as deterministic JSONL with Decimal values preserved as strings and is flushed and fsynced under the repository runtime lock. It contains the proposal, risk context, full decision, kill/config implications and correlation metadata, but no credentials. If an approval cannot be audited, it becomes `BLOCKED / AUDIT_WRITE_FAILED`. Runtime audit and kill-switch files are ignored and registered as generated artifacts.

The existing admin health page has a compact read-only risk section backed by `load_risk_diagnostics`: engine/config/kill-switch status, decision counts, latest status/reason and time. It does not evaluate proposals or write state, and the existing compact accounting badge is unchanged.

## Operations and safe future activation

Keep runtime `monitor_only` and `paper_execution_enabled=false` while configuration and canonical accounting are incomplete. Investigate `ERROR` as malformed config, kill state or audit; investigate `BLOCKED` through the latest reason code. Do not repair audit/accounting data by hand.

For a future paper-only activation: validate and activate a canonical GBP generation through its existing controlled process; reconcile it; obtain explicit approval for every risk limit; validate market/FX inputs; initialize and inspect the kill switch; run the full validator suite and rejected-order dry runs; then separately change the existing paper runtime controls under operator change management. Clearing the kill switch alone never enables trading. Live trading remains unsupported and disabled.

Known limitations are deliberate fail-closed constraints: production strategy-level exposure is not yet available from canonical accounting, open-order state is only reliable for this synchronous paper adapter, no authoritative deposit/withdrawal adjustment exists, and no broker/live adapter is implemented. Consequently the default production state cannot approve an order.
