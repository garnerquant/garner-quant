# Artifact Classification

This repository separates source code from mutable local outputs. Generated files may
exist in a developer checkout, but production packaging should treat them as local
state unless explicitly listed as source or fixture data below.

## Track

| Class | Examples | Reason |
| --- | --- | --- |
| source code | `main_v2.py`, `execution/`, `runtime/`, `dashboard/`, `pages/`, `strategy/`, `research/*.py` | Required to run, validate, and deploy the system. |
| deployment/config examples | `requirements.txt`, `deploy/`, `.env.example`, `.streamlit/secrets.toml.example` | Required setup material without local secrets. |
| documentation/manifests | `docs/`, `runtime/generated_runtime_files.txt` | Explains operational ownership and packaging. |
| fixture/test universe data | `data/universes/*.csv` | Small static inputs used by scanner/research workflows. |

## Ignore

| Class | Examples | Reason |
| --- | --- | --- |
| production runtime state | `broker_account.csv`, `paper_portfolio_v3.csv`, `trade_journal_v3.csv`, `trade_ledger_v1.csv`, `data/live_runtime_status.json` | Mutable local state; committing it causes stale state and merge conflicts. |
| generated reports | `data/accounting_reconciliation_report.json`, `data/*reconciliation*.json`, `trade_audit_trail.csv`, `trade_analytics_v3.csv` | Rebuildable outputs from validators/runtime. |
| research artifacts | `research/experiments/`, `research/report_exports/`, `data/global_scanner/` | Generated experiment registries, campaign reports, and scanner output. |
| legacy/archive outputs | `old_files/`, `data/legacy_sandbox/`, `portfolio.csv`, `paper_portfolio.csv` | Deprecated or sandboxed compatibility material. |
| local machine artifacts | `.env`, `.streamlit/secrets.toml`, `logs/`, `.tmp/`, `__pycache__/`, `venv/` | Secrets, logs, scratch files, build/cache output. |

## Existing Tracked Runtime Files

Some generated runtime files are already tracked from earlier history. This pass does
not untrack or delete them. They should be removed from the index only in an explicit
data-migration commit after confirming how production bootstrap should seed initial
state.
