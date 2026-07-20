# Garner Quant Production-Readiness Review

Review date: 2026-07-20  
Reviewed branch/commit: `main` at `112dea9e90ce5337bb49b7b3b76288a2e86bab61`  
Scope: all tracked Python source, configuration, documentation, workflows,
deployment units, scripts, and the contracts of current ignored runtime artifacts.
Secrets were not read or reproduced.

## 1. Executive summary

Garner Quant is a capable systematic-research and autonomous paper-trading
platform, not a production live-trading system. Its strongest engineering is the
ledger-first accounting recovery work: canonical event IDs, FIFO reconstruction,
atomic multi-file publication, runtime locks, projection guards, immutable Scanner
generations, checksummed research reports, and read-only dashboard consumers all
have meaningful fixture validators.

The current accounting files reconcile exactly: five ledger positions equal five
portfolio positions and five holdings positions; ledger cash and realised P&L
equal broker values; holdings value plus cash equals broker equity. The stale local
runtime status still contains the earlier BTC-GBP/VWRL.L projection error and is
over three hours old, but fresh reconciliation proves that error no longer describes
the current files. The runtime needs a controlled restart/status refresh before
continued autonomous paper operation.

The platform cannot yet be trusted with live capital. Execution mixes listing
currencies without FX normalization, treats any open configured market (including
24/7 crypto) as permission to run the all-asset strategy, accepts arbitrarily stale
mark-to-market timestamps, has no execution-time portfolio loss/exposure circuit
breaker, and has no live broker/order/fill state machine. Paper results also omit
fees/slippage, and the legacy backtest has both current-fundamental look-ahead bias
and ineffective same-bar stop logic.

**Verdict: Experimental only. Overall readiness: 54/100.**

- Paper-trading readiness: **68/100**, conditional on supervised operation,
  restored runtime health, and treating results as non-currency-normalized.
- Limited-capital live readiness: **18/100**.
- Full production live readiness: **8/100**.
- Confidence: **high (0.88)** for repository architecture/accounting and **medium
  (0.70)** for deployed operations because the actual AWS process, firewall,
  secrets, Supabase policies, and broker environment were not accessible.

Finding count: **0 Critical, 11 High, 13 Medium, 4 Low**.

## 2. Architecture and repository inventory

### Major subsystems

| Area | Primary modules | Responsibility |
|---|---|---|
| Daily strategy | `main_v2.py`, `strategy/`, `indicators/`, `risk/` | Yahoo acquisition, signals, target weights, ATR stops, paper decisions |
| Paper execution | `execution/portfolio_manager.py` | Exit confirmation, entries/exits, atomic transaction construction |
| Canonical accounting | `execution/trade_ledger.py`, `execution/accounting.py`, `execution/trade_audit.py` | Event validation/idempotency, FIFO lots, cash, realised/open cost |
| Derived account state | `execution/mark_to_market.py`, reporting modules | Holdings, broker, tracker, audit and analytics projections |
| Runtime | `runtime/live_runtime.py`, `runtime/locks.py`, startup/health modules | Five-minute monitor/paper cycles, locks, recovery, health artifacts |
| Scanner v2 | `research/scanner_v2/` | Immutable universe, bars, features, intelligence, ranks and candidates |
| Research | `research/scanner_*`, experiment modules | Read-only Scanner history/outcomes and immutable reports; legacy experiments |
| Dashboard | `web_dashboard.py`, `dashboard/`, `pages/`, `ui/` | Authenticated read/presentation of accounting, Scanner and Research |
| Integrations | Yahoo, Supabase, Telegram/email, news URLs | Prices/fundamentals, remote dashboard projection, alerts/intelligence |
| Deployment | `.github/workflows/`, `deploy/`, `scripts/start_*` | AWS deployment, systemd processes, scheduled validation |

### Entry points and long-running processes

- `python main_v2.py`: one complete daily/paper pipeline.
- `python runtime/live_runtime.py [--once]`: five-minute long-running monitor and
  autonomous paper pipeline.
- `python -m streamlit run web_dashboard.py`: main dashboard; Streamlit discovers
  `pages/*.py`.
- `python -m research.scanner_v2.acquire` and
  `python -m research.scanner_v2.features`: Scanner producers.
- Research report/experiment modules and 42 `scripts/validate_*.py` commands.
- Legacy `main.py` is sandbox-guarded; `execution/scheduler.py`, news and market
  intelligence CLIs remain additional/manual entry points.
- Systemd dashboard/runtime units restart always; GitHub deploy runs on every push
  to `main`; scheduled CI runs daily.

### Persistent stores and authority

The runtime ownership graph is:

```text
trade_ledger_v1.csv (canonical events)
  -> FIFO open lots / realised P&L / expected cash
  -> paper_portfolio_v3.csv (operational open-position projection)
  -> holdings_report.csv (marked projection)
  -> broker_account.csv (cash + holdings value)
  -> paper_30_day_tracker.csv (historical account snapshots)
  -> dashboard / outbound Supabase projection
```

| Value | Authority | Notes |
|---|---|---|
| Positions | Clean ledger FIFO open lots | Portfolio/holdings must reconcile before execution |
| Cash | Starting cash plus clean ledger cashflows | Broker is derived |
| Orders/fills | **No canonical model** | Ledger records immediate paper BUY/SELL events only |
| Realised P&L | `execution.accounting.ledger_accounting()` FIFO matches | Audit and broker reconcile to it |
| Unrealised P&L | Marked holdings value minus ledger open cost | Only valid with complete current prices |
| Equity | Ledger cash plus complete marked holdings | Broker/tracker/dashboard are projections |
| Drawdown | Chronological tracker total-equity series | Dashboard uses the same series |

Scanner uses immutable acquisition and feature-generation directories plus an
atomic `current_generation.json` pointer and SHA-256 manifest. Research reads many
validated Scanner generations and publishes independent immutable checksummed
reports. Dashboard readers do not mutate either producer.

### Main flows

```text
Yahoo OHLCV + current fundamentals
  -> technical/fundamental signals
  -> ATR risk levels + risk-sized target weights
  -> paper portfolio decisions
  -> atomic ledger/portfolio/journal/transaction/snapshot commit
  -> FIFO accounting
  -> holdings/broker/tracker
  -> dashboard, reports and outbound Supabase
```

There is no signal-to-live-order or broker-fill flow. Market monitor alerts are
paper-only. Supabase is a remote projection, not an accounting authority.

### Duplicated/conflicting calculations

- `execution.portfolio_manager.calculate_cash()` retains legacy journal-based cash,
  while final broker accounting uses the ledger (`portfolio_manager.py:290-303` and
  `915-987`). The transaction guard reduces harm, but two models remain.
- Legacy `main.py`, `execution/paper_trader.py`, `research/global_scanner.py`, root
  `indicators.py`, and multiple old CSV/report paths coexist with canonical v2 code.
- Market-session definitions exist in both runtime and live monitor with different
  abstractions (`runtime/live_runtime.py:40-60`,
  `execution/live_market_monitor.py:84-130`).
- Backtest risk/cost semantics differ materially from paper execution.

## 3. Test report

### Existing validators

All 41 pre-existing validators ultimately passed. First execution in an archive
copy produced 35 passes and six non-code failures: missing Git index, missing ignored
research input, and Windows permission denial for atomic hidden-directory fixtures.
All six passed against the intended repository/fixture environment. Durations below
are from the first valid run for each validator (seconds, rounded).

| Validator | Result | Seconds | Protection |
|---|---:|---:|---|
| accounting reconciliation | Pass | 1.31 | Meaningful production-state invariant |
| artifact hygiene | Pass | 2.03 | Git/runtime ownership |
| atomic broker reconciliation | Pass | 1.13 | Failure rollback |
| atomic mark-to-market | Pass | 1.22 | Multi-file valuation commit |
| atomic notification/intelligence | Pass | 1.77 | JSON atomicity |
| atomic recovery | Pass | 0.26 | Recovery protocol |
| atomic runtime JSON | Pass | 2.20 | Corrupt/partial JSON safety |
| atomic trade state | Pass | 1.16 | Ledger/projection transaction |
| ATR exit strategy | Pass | 44.97 | Research strategy fixtures |
| authoritative trade reports | Pass | 1.39 | Ledger-report identity/P&L |
| backtest analytics | Pass | 1.26 | Analytics calculations |
| broker writer guard | Pass | 0.11 | Canonical writer boundary |
| challenge equity curve | Pass | 1.20 | Tracker presentation contract |
| dashboard authentication | Pass | 1.29 | Login/token/fail-closed paths |
| derived state refresh | Pass | 2.08 | Explicit-price repair |
| equity curve presentation | Pass | 1.77 | Remaining chart layers |
| experiment framework | Pass | 1.56 | Registry/reproducibility |
| Scanner acquisition | Pass | 3.50 | Batch/failure/bar contracts |
| Scanner phase 1 | Pass | 3.70 | Universe/determinism |
| Scanner phase 3 | Pass | 141.07 | 500/1,500 asset determinism/atomicity |
| ledger open lots | Pass | 1.27 | Five-way quantity reconciliation |
| legacy entrypoint isolation | Pass | 1.33 | Legacy writer boundary |
| missing ledger exit reconciliation | Pass | 1.57 | Recovery refusal/repair fixture |
| paper challenge dashboard | Pass | 1.90 | Cards/equity/drawdown boundaries |
| tracker projection repair | Pass | 1.86 | Latest-row-only repair |
| parameter grid | Pass | 2.52 | Research parameters |
| parameter sweep | Pass | 1.76 | Research sweep |
| portfolio append after exits | Pass | 1.18 | Sparse-index regression |
| portfolio projection rebuild | Pass | 2.67 | Ledger-to-projection recovery |
| realised P&L reconciliation | Pass | 1.54 | Exact FIFO/event/headline equality |
| research campaign 001 | Pass | 3.96 | Campaign fixture |
| Research Lab | Pass | 1.27 | Boundary/static contract |
| Research Lab v2 | Pass | 1.35 | Generated research inputs |
| runtime bootstrap | Pass | 2.16 | Missing-file safe seeds |
| runtime state ownership | Pass | 0.21 | Writer/deployment boundaries |
| Scanner dashboard reader | Pass | 1.40 | Hash/schema/read-only failures |
| Scanner Research phase 6 | Pass | 2.88 | Immutable history/reports/no leakage |
| Scanner phase 5 | Pass | 1.48 | Intelligence/bundle/reader compatibility |
| stale post-commit overwrite | Pass | 1.23 | Writer race regression |
| trade ledger | Pass | 1.22 | IDs/signatures/projection/report integrity |
| unified runtime lock | Pass | 3.26 | Multi-process lock/recovery |

### Added test

`python scripts/validate_execution_input_guards.py` passes nine assertions:
zero/negative shares, prices and values are refused; a duplicate batch is refused;
an unmatched SELL becomes an orphan; and missing runtime config blocks execution.
It is write-free and is now included in scheduled CI.

### Other commands

| Command/check | Result | Duration/notes |
|---|---|---|
| Python compile of all source areas | Pass | 0.60 s |
| `python -m pip check` | Pass | No broken installed requirements |
| `python -m pytest --version` | Blocked | pytest not installed; no pytest suite/config |
| Ruff, mypy, Bandit, pip-audit, Radon, Vulture | Blocked | Not installed/configured |
| `import main_v2` | Pass | 3.77 s |
| bare `import web_dashboard` | Pass but noisy/slow | 24.0 s, substantial top-level work |
| runtime health check | Fail operationally | stale heartbeat and stale historical error |
| runtime PowerShell process status | Blocked | local CIM permission denied |
| `git diff --check` | Pass | Before final regression |

No coverage percentage can be stated. The repository has validators rather than a
discoverable unit-test suite. The installed Python is 3.14 while CI uses 3.11 and
deployment documents 3.10+; compatibility is not tested as a matrix.

### Adversarial results

- Invalid/negative event values: safely refused.
- Duplicate events in one append: safely refused.
- Orphan SELL: detected and blocks canonical broker accounting.
- Missing runtime config: paper execution blocked.
- Sunday with configured LSE/US/CRYPTO: CRYPTO makes the market set open and permits
  the complete paper pipeline. Unsafe/confirmed.
- One-year-old monitor price: accepted as a successful mark-to-market and propagated
  to holdings, broker and tracker in an isolated fixture. Unsafe/confirmed.
- Atomic failure, stale overwrite, corrupt JSON, lock contention and restart
  bootstrap are covered by existing validators.
- Broker outage, partial/multiple fills, rejected/cancelled real orders, process death
  between broker submission and persistence, clock drift, delisting, splits, and
  large-account behavior are unsupported or untested because no broker/order model
  exists.

## 4. Findings register

### High

| ID | Category / location | Evidence and impact | Reproduction | Fix / priority / complexity | Blocks paper / live |
|---|---|---|---|---|---|
| H-01 | Currency/accounting; `config.py:20-107`, `portfolio_manager.py:728-807`, `accounting.py:35-180` | Listing currencies are recorded but values are summed directly into GBP cash. No FX rate or GBp normalization exists. Equity and risk are economically invalid across currencies. | Buy USD and GBP assets; ledger cash subtracts both notionals as the same unit. | Establish canonical GBP money type, immutable FX snapshots and listing-unit conversion before sizing/ledger append. Immediate; high complexity. | Yes / Yes |
| H-02 | Session/execution; `live_runtime.py:40-60,439,632-669,827-1000` | Any open market permits the all-asset `main_v2` pipeline. CRYPTO is always open, so equities can be acted on outside their sessions and confirmation counts advance every cycle. | Sunday fixture returns `['CRYPTO']` and `paper_execution_blocked_reason=None`. | Partition signals/execution by asset market and completed bar; once-per-bar idempotency. Immediate; high. | Yes / Yes |
| H-03 | Stale data; `live_market_monitor.py:211-275`, `mark_to_market.py:88-113,498-559` | Price timestamps are collected but never age-validated. Refresh stamps derived state with current time. | A 2025 timestamp produced successful 2026 holdings/broker/tracker refresh. | Add market-aware maximum age and source timestamp to holdings; block incomplete valuation. Immediate; medium. | Yes / Yes |
| H-04 | Capital protection; `risk_manager.py:39-73`, `portfolio_manager.py:451-879` | `MAX_DRAWDOWN` only changes backtests. Execution has no kill switch, daily loss, equity drawdown, gross/net exposure or portfolio position-count gate. | Search shows no execution caller of `apply_drawdown_limit`. | Central pre-trade risk engine with persisted daily baseline and fail-closed limits. Immediate; high. | Yes / Yes |
| H-05 | Signal failure semantics; `fundamentals.py:6-45`, `signals.py:8-42` | Any fundamental API exception becomes score zero, indistinguishable from a genuine failed screen; signal zero is interpreted as exit after confirmation. Provider failure can drive sells. | Mock `Ticker.info` exception; stock signal becomes zero. | Tri-state valid/invalid/unavailable inputs; unavailable must block decisions, not become SELL. Immediate; medium. | Yes / Yes |
| H-06 | Execution realism; `portfolio_manager.py:580-807`, `trade_ledger.py:137` | Paper events always use zero fees and exact close prices; no slippage/spread/commission model. Reported performance is optimistic and differs from backtest costs. | Inspect new ledger events: `fees` defaults to zero. | One versioned execution-cost model used by paper/backtest; publish assumptions. Near term; medium. | No / Yes |
| H-07 | Backtest leakage; `signals.py:12-35`, `fundamentals.py:6-39`, `main_v2.py:57-89` | Current Yahoo fundamentals are applied as a constant gate over the entire three-year historical signal frame. Backtest performance has look-ahead bias. | Mock current score and observe all historical rows change. | Point-in-time fundamental store or omit fundamentals from historical tests. Immediate; high. | No / Yes |
| H-08 | Backtest exits; `risk_manager.py:19-27`, `backtest/engine.py:8-43` | A same-day close is compared with stop/target calculated as that same close ± ATR, making close-only stop/target triggers structurally impossible for positive ATR. | For finite ATR, `close <= close-2ATR` and `close >= close+3ATR` are false. | Persist entry/trailing levels and evaluate next-bar OHLC with explicit gap rules. Immediate; medium. | No / Yes |
| H-09 | Live order lifecycle; repository-wide | There is no broker adapter, order ID/state machine, acknowledgement, partial fill, cancel/reject, retry reconciliation or recovery journal. Ledger events are immediate paper fills. | No order/fill models or broker API modules exist. | Shadow broker adapter, durable idempotent order state machine, broker reconciliation. Essential; very high. | No / Yes |
| H-10 | Corporate actions; `market_data.py:8-16`, portfolio/ledger modules | Historical prices are auto-adjusted, but open quantities/cost bases have no split, merger, delisting or symbol-change event handling. | No corporate-action event/model exists. | Canonical corporate-action feed/events and lot transformations with audit trail. Before live; high. | No / Yes |
| H-11 | Backup/DR; deploy workflow and runtime CSV ownership | Deploy backup is temporary and deleted after restore. No durable encrypted scheduled backup, restore drill or off-host ledger retention is defined. | Deployment workflow contains only transient `mktemp` preservation. | Versioned encrypted off-host snapshots, retention, checksums and restore tests. Immediate; medium. | Yes / Yes |

### Medium

| ID | Category / location | Evidence and impact | Recommended fix | Blocks paper / live |
|---|---|---|---|---|
| M-01 | Calendar; `live_runtime.py:40-60`, `live_market_monitor.py:84-130` | Fixed weekday/time windows ignore exchange holidays, early closes and Tokyo lunch. Use an exchange calendar and test DST/holidays. | No / Yes |
| M-02 | Position sizing; `strategy/portfolio.py:7-68`, `portfolio_manager.py:728` | Risk and notional use constant starting cash rather than current equity and do not reserve portfolio-level risk across existing holdings. Central risk budget from reconciled equity. | Yes / Yes |
| M-03 | Floating money; accounting/ledger | Binary floats and `1e-12` share thresholds are used for money/fees. Introduce currency-minor-unit Decimal rounding at boundaries while retaining high-precision quantities. | No / Yes |
| M-04 | Dependencies; `requirements.txt` | Nine direct dependencies are entirely unpinned; no lock/hash/audit. Reproducibility and supply-chain state are unknown. Pin supported ranges/lock, Dependabot and pip-audit. | No / Yes |
| M-05 | CI; `.github/workflows/daily_bot.yml` | Before this review CI ran only four validators; one guard was added, but most of the 42-command suite remains unenforced. Add tiered fast/full jobs and Python matrix. | No / Yes |
| M-06 | Test quality | No pytest, coverage, type, lint, security or dead-code tooling. Validator scripts are meaningful but not discoverable/isolated uniformly. Adopt pytest and coverage gates incrementally. | No / Yes |
| M-07 | Runtime config/docs; `live_runtime_config.json:1-12`, `DEPLOYMENT.md:5-40` | Checked-in config enables autonomous paper execution while docs say deployment-safe defaults are monitor-only. Make environment-specific config explicit and validate it at deploy. | Yes / Yes |
| M-08 | Auth/session; `ui/auth.py:227-260` | Shared password only; JS-set cookie cannot be HttpOnly. No users, roles, rate limiting or revocation. Put dashboard behind TLS identity-aware proxy; server-managed sessions/RBAC. | No / Yes |
| M-09 | Deployment hardening; service files, `DEPLOYMENT.md:80` | Binds `0.0.0.0`; service units specify no unprivileged user/sandbox hardening; public protection is advisory. Add reverse proxy/TLS/firewall and systemd hardening. | No / Yes |
| M-10 | Remote projection; `supabase_sync.py:34-66,141-279` | Multi-table sync is non-transactional, positional IDs can change, failures only warn, and trade rows are printed. Use stable event IDs, generation/version marker, redact logs, monitor partial sync. | No / Yes |
| M-11 | Error semantics; broad `except Exception` sites | Fundamentals fail silently; dashboard/Supabase/news often degrade to empty/default. Some are intentional boundaries, but status codes are inconsistent. Use typed failures and structured telemetry. | Yes / Yes |
| M-12 | Maintainability/performance; `web_dashboard.py` (3,410 lines), runtime (1,237), portfolio manager (831) | Large top-level modules couple loading/rendering; bare dashboard import took 24 s and emitted extensive side effects. Split page controllers and cache by canonical identity. | No / No |
| M-13 | Research validity; current universe files and historical research | No historical constituent universe is evident, so long-horizon research can have survivorship bias. Persist point-in-time membership and delisting outcomes. | No / Yes |

### Low

| ID | Finding | Recommendation |
|---|---|---|
| L-01 | Legacy modules and duplicate names remain (`main.py`, root `indicators.py`, legacy scanner/trader). | Maintain explicit deprecation inventory and remove only after caller proof. |
| L-02 | “30 day” filenames/functions remain after the 60-day UI migration. | Compatibility alias now; schedule a versioned rename/migration. |
| L-03 | Documentation/source output contains visible encoding mojibake in several labels/docs. | Normalize UTF-8 and add encoding check. |
| L-04 | Naming/style/type coverage is inconsistent and many public functions are untyped. | Formatter/linter/type baseline on new/critical modules first. |

## 5. What is working well

- Atomic CSV/JSON transaction and recovery protocols have failure-injection tests.
- Ledger IDs, natural signatures and legacy IDs provide layered duplicate protection.
- FIFO fees are proportionally allocated across partial closes and authoritative
  reports verify event identity.
- Projection mismatch blocks paper execution rather than silently trading onward.
- Runtime and writer locks have multi-process validation.
- Bootstrap creates only missing state and refuses overwrite.
- Scanner v2 generation publication is immutable, deterministic at 500/1,500 assets,
  checksummed and last-complete-pointer based.
- Dashboard Scanner/Research boundaries are read-only with explicit invalid states.
- Authentication fails closed when credentials are missing in production contexts.
- Deployment preserves ignored server state around source updates and runs startup
  validation before services restart.

## 6. Recommended fixes

### F-01: Canonical currency and money model

- Modules: `config.py`, market-data adapters, `portfolio_manager.py`, ledger schema,
  `accounting.py`, holdings/broker/reporting.
- Design: define account base currency GBP; capture quote currency, listing unit,
  FX pair/rate/source/timestamp on every valuation and fill; ledger stores both quote
  and base notional/fees. Never retrospectively rewrite historical events.
- Migration: additive schema plus explicit legacy conversion status; existing history
  remains auditable and “unverified FX” until reconstructed from pinned rates.
- Tests: USD/GBp/GBP positions, stale/missing FX, fee rounding, exact equity.
- Rollback: feature flag producer while readers accept old schema.
- Risk reduction: removes the largest economic-accounting error.

### F-02: Per-market, once-per-bar decision orchestration

- Modules: runtime sessions, `main_v2`, market data metadata, decision trace.
- Design: only assets whose exchange is open and whose canonical decision bar is new
  may generate an execution decision. Persist `(strategy_version,ticker,bar_time)`
  idempotency key. Signal confirmation counts distinct bars, not runtime cycles.
- Tests: weekend crypto with equities, DST, holiday/early close, repeated cycle, restart.
- Rollback: monitor-only mode.
- Risk reduction: prevents out-of-session/stale repeated trades.

### F-03: Data-quality circuit breaker

- Modules: `data.market_data`, fundamentals, live monitor, mark-to-market, runtime.
- Design: typed observation with source/event time/fetched time/status; market-aware
  maximum ages; incomplete input blocks decisions and produces alerts. Do not forward
  fill beyond a declared limit.
- Tests: stale/missing/negative/partial provider data and clock skew.
- Rollback: monitor-only while retaining diagnostics.

### F-04: Central risk engine

- Modules: new producer under `risk/`, called before atomic trade commit.
- Controls: kill switch, max daily loss/drawdown, per-position and aggregate risk,
  asset/sector/currency exposure, cash floor, max orders/trades, stale-data gate.
- Tests: every limit at boundary, concurrency, restart persistence, override audit.
- Rollback: deny new entries while still permitting risk-reducing exits.

### F-05: Trustworthy backtesting

- Modules: signal data contracts, `backtest/engine.py`, costs, research reports.
- Design: point-in-time inputs, next-bar execution, OHLC gap/stop rules, shared cost
  model, historical constituents, strategy/data version pinning.
- Tests: no-lookahead perturbation, known stop gaps, parity fixtures.

### F-06: Durable order lifecycle (before any live pilot)

- Add order intent, broker order, fill and reconciliation events with idempotency keys.
  Persist intent before submission; reconcile unknown outcomes after timeout/restart;
  only broker fills create canonical fill ledger entries.
- Tests: submit timeout, duplicate webhook/poll, partial/multiple fills, reject/cancel,
  restart at every transition, broker/local divergence.

### F-07: Operational baseline

- Durable encrypted backups and restore drills; deployment rollback artifact; health
  alerts for stale heartbeat/reconciliation/provider failure; structured redacted logs;
  pinned dependencies and full CI; TLS/reverse proxy/service hardening.

No production behavior was changed in this review because F-01 through F-07 require
explicit policy/schema choices. The only implemented change is the focused guard
validator and CI invocation.

## 7. Roadmap

### Immediate: before further live-trading work

1. Keep live broker execution nonexistent/disabled; restart paper runtime only after
   current health/status validation.
2. F-01 currency/FX model.
3. F-02 per-market/new-bar orchestration.
4. F-03 freshness/unavailable-data circuit breaker.
5. F-04 risk engine and kill switch.
6. F-05 remove backtest leakage/stop defects before using results for decisions.
7. Durable ledger backups and restore exercise.

Dependencies: currency/freshness precede risk sizing; new-bar orchestration precedes
reliable confirmation; broker order work depends on all three.

### Near term: next one to two cycles

- Shared paper/backtest execution-cost contract.
- Exchange calendars and corporate-action event model.
- Full CI tier, pytest migration, coverage, type/lint/security/dependency checks.
- Stable Supabase IDs/generation consistency and redacted logging.
- Runtime alerts for stale health, reconciliation and backup failures.

### Medium term

- Shadow-mode broker adapter and durable order state machine.
- Point-in-time universe/fundamental store and backtest-to-paper parity reports.
- Strategy/config versioning and signed deployment manifest/rollback.
- Break up dashboard/runtime/portfolio manager into typed services.

### Optional refinements

- Performance optimization only after measurement: canonical-version caches,
  incremental dashboard loading and partitioned long histories.
- Drift monitoring after a statistically valid point-in-time research baseline exists.

## 8. Crucial feature recommendations

| Feature | Need/risk reduced | Priority | Approach/tests | Cost |
|---|---|---|---|---|
| Central risk engine + kill switch | Caps loss/exposure and enables operator stop | Essential | Pre-commit decision service; boundary/restart tests | High |
| Stale-data circuit breaker | Prevents trades/valuations on old or unavailable inputs | Essential | Typed timestamps/status and per-market age; outage/clock tests | Medium |
| Per-market once-per-bar scheduler | Prevents crypto session from authorizing equity decisions | Essential | Bar idempotency journal; session/DST tests | High |
| Broker state reconciliation/order machine | Handles unknown/partial/repeated real order outcomes | Essential for live | Event-sourced transitions; failure-at-every-state tests | Very high |
| Canonical FX/listing-unit service | Makes cash, exposure and P&L economically meaningful | Essential | Pinned FX observations; multi-currency tests | High |
| Recovery journal | Resolves crash between intent/submission/persistence | Essential for live | Write-ahead intent + broker reconciliation | High |
| Automated backups/restore | Protects canonical ledger and runtime state | Essential | Encrypted off-host generations and restore drills | Medium |
| Health dashboard + structured alerts | Shortens stale runtime/reconciliation response | Recommended | Prometheus/log or current JSON plus alert routes | Medium |
| Shadow-mode live execution | Validates broker semantics without orders | Recommended | Compare hypothetical intent with broker quotes/state | Medium |
| Backtest-to-live parity | Detects semantic drift | Recommended | Versioned fixture replay across engines | Medium |
| Strategy/config versioning | Audits why each decision occurred | Recommended | Hash config/code/data IDs into events | Low-medium |
| Data/strategy drift monitoring | Detects input/outcome changes after valid baseline | Optional later | Versioned distributions and alert thresholds | Medium ongoing |

## 9. Readiness score

| Category | Score | Max | Evidence and deductions | To raise score |
|---|---:|---:|---|---|
| Trading/accounting correctness | 12 | 20 | Strong FIFO/atomic/reconciliation; currency mixing, paper costs, backtest defects | F-01 and F-05; cost parity |
| Risk/capital protection | 5 | 15 | Per-trade weights/stops exist; no execution risk engine/kill switch | F-04 |
| Reliability/recovery | 8 | 15 | Locks, atomic recovery, bootstrap strong; stale input/session/order/backup gaps | F-02/F-03/F-06/backups |
| Test quality/coverage | 9 | 15 | 42 meaningful validators; no coverage/framework/tooling and narrow CI | Full CI, pytest, coverage, adversarial broker/provider tests |
| Data integrity/reconciliation | 7 | 10 | Current five-position accounting exact; no FX/freshness/corporate actions | F-01/F-03/corporate actions |
| Security | 5 | 10 | Fail-closed auth/secrets ignored; shared password cookie and deployment hardening gaps | Proxy identity/TLS/RBAC/systemd/pip audit |
| Observability/operations | 3 | 5 | Runtime JSON, decision trace, alerts and health page; stale local health/no escalation SLA | Structured metrics/alerts/runbooks |
| Performance/scalability | 3 | 5 | Scanner scale fixture good; 24 s dashboard import and full CSV/Supabase reloads | Profile then incremental/version caches |
| Maintainability/docs | 2 | 5 | Architecture docs useful; giant modules, legacy duplication, config/docs drift | Modularization, deprecation, typing and doc correction |
| **Total** | **54** | **100** | **Experimental only** | Complete immediate roadmap |

## 10. Final readiness checklist

| Capability | Pass? | Reason |
|---|---|---|
| Continued supervised paper trading | **Conditional fail today** | Current accounting passes, but runtime health/status is stale; restart validation required. Currency/freshness/session limitations must be accepted explicitly. |
| Limited live pilot | **Fail** | No broker/order lifecycle, FX model, risk engine, freshness gate or recovery journal. |
| Unattended operation | **Fail** | No durable backup/restore proof, health escalation, market-aware execution or data circuit breaker. |
| Production live deployment | **Fail** | Multiple High blockers and no live execution architecture. |

## 11. Review changes and unresolved uncertainty

Changed by this review:

- Added `scripts/validate_execution_input_guards.py`.
- Added that validator to `.github/workflows/daily_bot.yml`.
- Added this report.

No strategy, Scanner, Research, dashboard, execution, accounting, ledger, runtime,
deployment service, configuration, or production data behavior was changed.

Unverified externally:

- Actual AWS service/process state, firewall/TLS/reverse proxy and systemd user.
- Supabase row-level security/schema/backups and which key role is deployed.
- Telegram/email delivery and alert escalation.
- Broker integration, because none exists in this repository.
- Current third-party vulnerabilities: dependencies are unpinned and `pip-audit` is
  unavailable, so only `pip check` was completed.
- Live Yahoo availability/latency was intentionally not exercised.
