# Garner Quant

Garner Quant is a systematic equity trading platform for automated research, paper trading, and strategy validation.

The platform includes automated signal generation, portfolio construction, risk management, a paper/live trading workflow, trade auditing, strategy research and experimentation, performance analytics, and automated daily execution.

---

## Current Features

### Trading Engine

- Signal generation using technical and fundamental inputs.
- Portfolio construction from generated signals and weights.
- Risk management using stop-loss and take-profit levels.
- Position sizing and cash-aware portfolio updates.
- Daily execution through `main_v2.py`.
- Trade journal, transaction log, broker account, holdings, and paper portfolio updates.

### Dashboard

Garner Quant includes a Streamlit dashboard for monitoring the trading system and reviewing historical activity.

Current dashboard areas include:

- Portfolio overview
- Holdings
- Performance
- Trade Journal
- Trade Audit
- Trade Replay
- System Health
- Research Lab

### Research Lab

The Research Lab is isolated from production trading and is used to review, test, and compare strategy experiments safely.

It currently includes:

- Experiment registry stored separately in `research/experiments.json`
- Experiment drafts
- Research-only parameter overrides
- Live-rule backtesting
- Experiment lifecycle management
- Experiment comparison
- Saved experiment history

Research Lab never modifies the production strategy, live configuration, paper portfolio state, Supabase sync, or GitHub Actions workflow.

### Automation

Garner Quant supports automated daily execution through GitHub Actions.

Automation covers:

- Scheduled execution
- Daily portfolio processing
- Regeneration of trading outputs
- Automatic dashboard data updates

### Data

The project data flow is:

```text
Market Data
↓
Signal Generation
↓
Risk Levels
↓
Portfolio Construction
↓
Execution
↓
Dashboard
↓
Research
```

---

## Project Structure

- `/execution` - Paper trading execution, portfolio manager, broker account updates, trade audit, snapshots, and Supabase sync.
- `/research` - Research-only experiment configuration, experiment registry, and live-rule backtesting.
- `/pages` - Streamlit dashboard pages, including Trade Audit, Research Lab, and Admin/System Health.
- `/dashboard` - Dashboard support modules.
- `/data` - Market data and fundamental data helpers.
- `/strategy` - Signal and portfolio weight construction.
- `/risk` - Risk level generation.
- `/backtest` - Backtesting utilities for portfolio simulation.
- `/indicators` - Technical indicator implementations.
- `/reporting` - Reporting and analytics helpers.
- `web_dashboard.py` - Main Streamlit dashboard entry point.
- `main_v2.py` - Main daily trading pipeline.
- `config.py` - Production strategy configuration.

---

## Development Principles

- Production strategy remains isolated from research tooling.
- Research never mutates production configuration.
- Experiments should be reproducible and saved separately from live trading state.
- Changes should be modular and scoped to the relevant subsystem.
- Prefer configuration over hardcoded strategy behavior.
- Every new strategy should be validated in Research Lab before production consideration.

---

## Run Manually

```bash
python main_v2.py
```

To run the dashboard locally:

```bash
python -m streamlit run web_dashboard.py
```

---

## Current Roadmap

- ✅ Trading Engine
- ✅ Dashboard
- ✅ Trade Audit
- ✅ Trade Replay
- ✅ System Health
- ✅ Research Lab V2
- ✅ Experiment Comparison
- 🔲 Parameter Sweeps
- 🔲 Walk-Forward Testing
- 🔲 Portfolio Optimisation

---

## Future Vision

Garner Quant is evolving into a professional quantitative research and trading platform where strategy ideas progress through a controlled lifecycle:

```text
Idea
↓
Experiment
↓
Backtest
↓
Candidate
↓
Paper Trading
↓
Production
```

The goal is to keep research flexible while ensuring production trading remains stable, auditable, and deliberate.
