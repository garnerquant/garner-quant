# Runtime Bootstrap And Git Index Decision

Generated runtime files are local mutable state. They should be ignored for future
changes and removed from the Git index in a dedicated data-index cleanup commit.
This pass does not untrack or delete local data.

## Tracked Generated Files

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

## Recommended Manual Untrack Command

Run this only in a deliberate data-index cleanup commit after confirming local
runtime files are backed up:

```powershell
git rm --cached broker_account.csv holdings_report.csv paper_30_day_tracker.csv paper_portfolio_v3.csv portfolio_v2.csv signal_report_v2.csv trade_analytics_v3.csv trade_audit_trail.csv trade_journal_v3.csv trade_snapshots.csv v3_trades.csv data/live_monitor_runtime.json data/live_monitor_snapshot.json data/live_runtime_execution_log.json data/live_runtime_status.json data/market_intelligence.json data/news_events.json data/notification_state.json data/runtime_operations_log.json research/report_exports/campaign_reports/campaign_001_exit_optimisation_38504693-4616-43d4-8887-62adefbc3a50.md research/report_exports/campaign_reports/campaign_001_exit_optimisation_latest.md
```
