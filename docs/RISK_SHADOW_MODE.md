# Risk engine shadow mode

Shadow mode provides operational evidence from the real completed-bar strategy path while remaining non-executing. Trading remains disabled.

```text
Completed-bar scheduler
  -> production strategy and proposal adapter
  -> full central risk evaluation
  -> append-only decision audit
  -> read-only operations history, metrics and readiness
  X  no trade-state commit, notification, remote sync or broker order
```

The runtime invokes shadow evaluation only while its configured mode is `monitor_only`. It uses the same `update_portfolio` BUY/SELL proposal construction as paper mode, with `shadow_mode=True`. Every constructed proposal receives a structured decision. The engine continues all safely available operational, market, accounting and projected-portfolio checks, but `execution_eligible` is always false and the status remains `MONITOR_ONLY`. An unexpected approval raises and fails the shadow cycle closed. The paper execution gate remains separate and unchanged.

## Operator workflow

The Admin Health page contains a compact Risk Operations section. It shows engine, trading, kill-switch and accounting status; latest proposal/decision/reason; daily counts; monitor-only count; configuration version; evaluation latency; searchable read-only history; rolling metrics; configuration health; and activation blockers. Filters cover strategy, symbol, decision, reason and UTC date.

History is the existing append-only JSONL risk audit under ignored `data/risk_engine/`. Records retain proposals, live input context, findings, projections, decision latency and configuration identity. The reader never edits the audit. Metrics include approval/rejection/block rates, reasons, latency, highest projected exposure, affordability shortfall, stale/FX/scheduler/runtime failures, kill-switch activations and configuration-version changes.

The readiness report always answers “No” while any blocker exists. Current deliberate blockers include inactive canonical accounting, unapproved limits, disabled trading control, fail-safe kill switch, unavailable canonical strategy exposure and an incomplete deposit/withdrawal-adjusted drawdown model. Recommended actions are evidence gathering and controlled validation only; they do not enable trading.

## Configuration and activation checklist

Configuration health loads the strict versioned configuration and reports every field, value and unit. GBP amounts, decimal ratios, seconds, counts and policy fields are distinguished. There are no implicit overrides; unknown or missing fields fail loading.

Before any future paper activation, independently resolve every readiness blocker, validate a canonical GBP generation through the existing accounting process, approve all risk limits, add authoritative strategy attribution and cash-flow-adjusted drawdown, exercise shadow mode over a representative period, review audit completeness, and rerun every validator. Clearing the kill switch does not enable trading. Live trading and broker submission remain unsupported.
