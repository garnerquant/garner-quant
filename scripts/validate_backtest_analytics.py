import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.backtest_analytics import load_backtest_analytics


def main():
    analytics = load_backtest_analytics()
    summary = analytics["summary"]
    availability = analytics["availability"]

    print("Backtest analytics validation")
    print(f"Portfolio rows: {availability['portfolio_rows']}")
    print(f"Trade rows: {summary['trade_count']}")
    print(f"Total return: {summary['total_return']:.4f}")
    print(f"CAGR: {summary['cagr']:.4f}")
    print(f"Sharpe ratio: {summary['sharpe_ratio']:.4f}")
    print(f"Benchmark source: {availability['benchmark_source'] or 'none'}")


if __name__ == "__main__":
    main()
