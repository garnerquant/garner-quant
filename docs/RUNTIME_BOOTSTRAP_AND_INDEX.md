# Runtime Bootstrap And Git Index Decision

Generated runtime files are local mutable state. They are ignored and absent from the
Git index. Production deployment preserves them before updating source code and
restores them before startup validation.

## Generated Files

The following tracked files are classified as generated artifacts by `.gitignore`:

| File group | Recommendation | Reason |
| --- | --- | --- |
| `broker_account.csv`, `paper_portfolio_v3.csv`, `trade_journal_v3.csv`, `trade_snapshots.csv`, `trade_audit_trail.csv`, `trade_analytics_v3.csv`, `holdings_report.csv`, `paper_30_day_tracker.csv` | Needs bootstrap/migration first, then untrack | They are production runtime state or derived reports. Preserve local copies, then remove from index. |
| `portfolio_v2.csv`, `signal_report_v2.csv`, `v3_trades.csv` | Safe to untrack after confirming dashboard bootstrap | Rebuildable runtime outputs; bootstrap now creates safe missing schemas. |
| `data/live_*.json`, `data/runtime_operations_log.json`, `data/market_intelligence.json`, `data/news_events.json`, `data/notification_state.json` | Needs bootstrap/migration first, then untrack | Runtime JSON state is local mutable state. Bootstrap now creates parseable defaults when missing. |
| `research/report_exports/campaign_reports/*.md` | Safe to untrack now | Generated research report exports; research source remains tracked. |

No generated runtime artifact is required as Git-tracked seed state after bootstrap
is available.

## Bootstrap Process

`runtime.bootstrap_state.bootstrap_runtime_state()` creates missing runtime files
only. It never overwrites existing files.

Safe seed behavior:

- Broker account starts with `STARTING_CASH`, zero positions, zero PnL.
- Portfolio, journal, transaction, snapshot, ledger, holdings, audit, signal, and
  tracker CSVs are created with expected schemas or safe empty frames.
- Runtime, notification, market intelligence, and news JSON files are created with
  parseable empty/default structures.
- Startup validation runs atomic recovery first, then bootstraps missing files, then
  validates generated artifacts.

Manual dry run:

```powershell
python scripts\bootstrap_runtime_state.py
```

Manual apply:

```powershell
python scripts\bootstrap_runtime_state.py --apply
```

The index cleanup is complete. Do not re-add generated state with `git add -f`.
