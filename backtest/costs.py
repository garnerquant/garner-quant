TRANSACTION_FEE = 0.001
SLIPPAGE = 0.0005


def apply_trading_costs(portfolio, weights):
    weight_changes = weights.diff().abs().sum(axis=1)

    total_cost = weight_changes * (
        TRANSACTION_FEE + SLIPPAGE
    )

    portfolio["trading_cost"] = total_cost

    portfolio["daily_return"] = (
        portfolio["daily_return"]
        - total_cost
    )

    portfolio["equity"] = (
        portfolio["equity"].iloc[0]
        * (1 + portfolio["daily_return"]).cumprod()
    )

    portfolio["peak"] = portfolio["equity"].cummax()

    portfolio["drawdown"] = (
        portfolio["equity"] / portfolio["peak"]
    ) - 1

    return portfolio