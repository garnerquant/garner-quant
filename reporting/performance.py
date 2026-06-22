from config import STARTING_CASH


def calculate_performance(portfolio):
    final_value = portfolio["equity"].iloc[-1]
    total_return = (final_value / STARTING_CASH) - 1
    max_drawdown = portfolio["drawdown"].min()

    daily_returns = portfolio["daily_return"]
    average_daily_return = daily_returns.mean()
    volatility = daily_returns.std()

    if volatility != 0:
        sharpe_ratio = (average_daily_return / volatility) * (252 ** 0.5)
    else:
        sharpe_ratio = 0

    return {
        "starting_cash": STARTING_CASH,
        "final_value": final_value,
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio
    }


def print_performance(report):
    print("\n===== ADVANCED PERFORMANCE REPORT =====")
    print(f"Starting cash: £{report['starting_cash']:,.2f}")
    print(f"Final value:   £{report['final_value']:,.2f}")
    print(f"Total return:  {report['total_return']:.2%}")
    print(f"Max drawdown:  {report['max_drawdown']:.2%}")
    print(f"Sharpe ratio:  {report['sharpe_ratio']:.2f}")