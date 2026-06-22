import matplotlib.pyplot as plt


def show_dashboard(portfolio, weights, report):
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))

    fig.suptitle(
        "Garner Quant Performance Dashboard",
        fontsize=16,
        fontweight="bold"
    )

    portfolio["equity"].plot(
        ax=axes[0],
        title="Equity Curve"
    )
    axes[0].set_ylabel("Portfolio Value £")
    axes[0].grid(True)

    portfolio["drawdown"].plot(
        ax=axes[1],
        title="Drawdown"
    )
    axes[1].set_ylabel("Drawdown")
    axes[1].grid(True)

    final_weights = weights.iloc[-1]
    final_weights = final_weights[final_weights > 0]
    final_weights = final_weights.sort_values(ascending=True)

    final_weights.plot(
        kind="barh",
        ax=axes[2],
        title="Current Portfolio Allocation"
    )
    axes[2].set_xlabel("Weight")
    axes[2].grid(True)

    metrics_text = (
        f"Starting Cash: £{report['starting_cash']:,.2f}\n"
        f"Final Value: £{report['final_value']:,.2f}\n"
        f"Total Return: {report['total_return']:.2%}\n"
        f"Max Drawdown: {report['max_drawdown']:.2%}\n"
        f"Sharpe Ratio: {report['sharpe_ratio']:.2f}"
    )

    fig.text(
        0.78,
        0.82,
        metrics_text,
        fontsize=10,
        bbox=dict(facecolor="white", alpha=0.9)
    )

    plt.tight_layout()
    plt.show()