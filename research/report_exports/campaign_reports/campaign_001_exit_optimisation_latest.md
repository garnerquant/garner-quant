# Research Campaign 001 - Exit Optimisation

Campaign ID: campaign_001_exit_optimisation_38504693-4616-43d4-8887-62adefbc3a50
Mode: real historical simulation
Runs: 6 completed=6 failed=0 unsupported=0
Evidence split: real=6 dry_run=0

## Best Strategies
- Best Sharpe: Current binary exit (current_binary_exit)
- Best CAGR: Current binary exit (current_binary_exit)
- Best Drawdown: Time exit 10 days (time_exit)
- Best Profit Factor: Fixed stop loss 3% (fixed_stop_loss)

## Real Simulated Results
- Current binary exit: Sharpe=1.388, CAGR=12.277%, Drawdown=-5.631%, Profit Factor=1.653
- Time exit 10 days: Sharpe=1.383, CAGR=11.745%, Drawdown=-5.491%, Profit Factor=1.496
- Partial exit 50%: Sharpe=1.304, CAGR=9.945%, Drawdown=-5.598%, Profit Factor=1.499
- Trailing stop 5%: Sharpe=1.231, CAGR=11.974%, Drawdown=-10.174%, Profit Factor=1.990
- Confirmation exit 2 days: Sharpe=1.184, CAGR=11.308%, Drawdown=-8.564%, Profit Factor=1.617
- Fixed stop loss 3%: Sharpe=0.535, CAGR=8.837%, Drawdown=-19.880%, Profit Factor=3.365

## Unsupported Variants
- None.

## Dry-Run Validation Results
- None.

## What Improved
- Time exit 10 days: improved drawdown.
- Partial exit 50%: improved drawdown.
- Trailing stop 5%: improved profit factor.
- Fixed stop loss 3%: improved profit factor.

## What Became Worse
- Time exit 10 days: weaker Sharpe, CAGR, profit factor.
- Partial exit 50%: weaker Sharpe, CAGR, profit factor.
- Trailing stop 5%: weaker Sharpe, CAGR, drawdown.
- Confirmation exit 2 days: weaker Sharpe, CAGR, drawdown, profit factor.
- Fixed stop loss 3%: weaker Sharpe, CAGR, drawdown.

## Walk-Forward Candidates
- Current binary exit
- Time exit 10 days
- Fixed stop loss 3%
