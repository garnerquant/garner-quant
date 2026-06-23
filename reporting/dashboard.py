import matplotlib.pyplot as plt


def show_dashboard(portfolio, weights, report):

    if portfolio.empty:
        print("No portfolio data to chart.")
        return

    fig, axes = plt.subplots(3, 1, figsize=(14, 10))

    fig.suptitle(
        "Garner Quant Performance Dashboard",
        fontsize=16,
        fontweight="bold"
    )

    if "equity" in portfolio.columns and not portfolio["equity"].empty:
        portfolio["equity"].plot(
            ax=axes[0],
            title="Equity Curve"
        )
    else:
        axes[0].text(0.5, 0.5, "No equity data", ha="center")

    axes[0].set_ylabel("Portfolio Value £")
    axes[0].grid(True)

    if "drawdown" in portfolio.columns and not portfolio["drawdown"].empty:
        portfolio["drawdown"].plot(
            ax=axes[1],
            title="Drawdown"
        )
    else:
        axes[1].text(0.5, 0.5, "No drawdown data", ha="center")

    axes[1].set_ylabel("Drawdown")
    axes[1].grid(True)

    if not weights.empty:
        final_weights = weights.iloc[-1]
        final_weights = final_weights[final_weights > 0]
        final_weights = final_weights.sort_values(ascending=True)

        if not final_weights.empty:
            final_weights.plot(
                kind="barh",
                ax=axes[2],
                title="Final Portfolio Weights"
            )
        else:
            axes[2].text(0.5, 0.5, "No active weights", ha="center")
    else:
        axes[2].text(0.5, 0.5, "No weights data", ha="center")

    axes[2].set_xlabel("Weight")
    axes[2].grid(True)

    plt.tight_layout()
    plt.show()