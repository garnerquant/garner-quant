# Runtime State Ownership

Runtime accounting files are server-owned mutable state and are not Git deployment
artifacts. The ownership direction is:

`trade_ledger_v1.csv` -> `paper_portfolio_v3.csv` -> `holdings_report.csv` ->
`broker_account.csv` -> `paper_30_day_tracker.csv`.

## Production Write Graph

| Trigger | Reader | Transformation | Writer | Destination | Ownership |
| --- | --- | --- | --- | --- | --- |
| Paper execution | ledger + portfolio + signals/prices | trade decisions and atomic trade-state frames | `portfolio_manager.commit_trade_state` | ledger, portfolio, journal, transactions, snapshots | canonical trade transaction |
| Pipeline reporting | returned portfolio + downloaded prices | `create_holdings_report` | `main_v2` atomic report write | holdings | derived from current portfolio |
| Pipeline accounting | clean ledger + in-memory holdings valuation | `broker_values_from_ledger_and_holdings` | `portfolio_summary` -> `update_account` | broker | derived from ledger and holdings |
| Pipeline challenge snapshot | broker + benchmark stats | `update_30_day_tracker` | atomic tracker append | tracker | derived from broker |
| Runtime monitor cycle | portfolio + complete monitor prices | `_build_valuation` | `mark_to_market_refresh` atomic derived-state commit | holdings, broker, tracker, portfolio report | derived only; cannot write portfolio |
| Runtime broker guard | clean ledger + holdings | `reconcile_broker_account_file` | canonical broker commit | broker | correction derived from ledger and holdings |
| Startup | existence checks | `bootstrap_runtime_state` | atomic seed writes | missing files only | never overwrites existing state |
| Manual projection rebuild | clean ledger + snapshots | `rebuild_portfolio_projection` | atomic replacement | portfolio | explicit operator recovery only |
| Manual derived refresh | portfolio + explicit prices + clean ledger | canonical holdings/broker helpers | atomic two-file commit | holdings, broker | explicit operator recovery only |
| Manual tracker repair | healthy accounting + tracker | current-row replacement | atomic tracker replacement | tracker | explicit operator recovery only |
| Dashboard | local/Supabase reads | presentation only | none | none | read-only |
| Supabase sync | local CSV reads | remote upsert | Supabase client | remote tables | outbound only; never writes local CSV |

## Deployment and Scheduled Jobs

Deployment stops the runtime, copies every existing path from
`runtime/generated_runtime_files.txt` to a temporary server backup, updates source
with Git, restores server state, and only then runs startup validation. Generated
runtime files are ignored and absent from the Git index, so later source resets cannot
replace them.

The GitHub daily workflow has read-only repository permission and runs accounting
validators only. It does not execute `main_v2.py`, receive Supabase credentials, or
publish an alternate accounting source. Production paper execution is owned by the
AWS runtime service.

## Removed Stale Writers

- Git no longer tracks generated runtime state.
- Deployment no longer exposes server state to `git reset --hard`.
- Daily Actions no longer commits generated state.
- Mark-to-market no longer writes `paper_portfolio_v3.csv`; valuation is downstream
  of the portfolio projection.
