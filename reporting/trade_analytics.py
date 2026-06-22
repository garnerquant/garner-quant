import pandas as pd


def analyse_trade_journal(journal):

    if len(journal) == 0:

        return {

            "total_trades": 0,

            "win_rate": 0,

            "profit_factor": 0,

            "average_winner": 0,

            "average_loser": 0,

            "best_trade": 0,

            "worst_trade": 0,

            "realised_pnl": 0

        }

    winners = journal[

        journal["pnl"] > 0

    ]

    losers = journal[

        journal["pnl"] <= 0

    ]

    total_trades = len(journal)

    win_rate = (

        len(winners)

        /

        total_trades

    )

    gross_profit = winners["pnl"].sum()

    gross_loss = (

        losers["pnl"]

        .abs()

        .sum()

    )

    if gross_loss > 0:

        profit_factor = (

            gross_profit

            /

            gross_loss

        )

    else:

        profit_factor = 0

    average_winner = (

        winners["pnl"]

        .mean()

    )

    average_loser = (

        losers["pnl"]

        .mean()

    )

    best_trade = (

        journal["pnl"]

        .max()

    )

    worst_trade = (

        journal["pnl"]

        .min()

    )

    realised_pnl = (

        journal["pnl"]

        .sum()

    )

    return {

        "total_trades":

        total_trades,

        "win_rate":

        win_rate,

        "profit_factor":

        profit_factor,

        "average_winner":

        average_winner,

        "average_loser":

        average_loser,

        "best_trade":

        best_trade,

        "worst_trade":

        worst_trade,

        "realised_pnl":

        realised_pnl

    }


def print_trade_analytics(stats):

    print(

        "\n===== TRADE ANALYTICS ====="

    )

    print(

        f"Trades: "

        f"{stats['total_trades']}"

    )

    print(

        f"Win Rate: "

        f"{stats['win_rate']:.2%}"

    )

    print(

        f"Profit Factor: "

        f"{stats['profit_factor']:.2f}"

    )

    print(

        f"Average Winner: "

        f"£{stats['average_winner']:,.2f}"

    )

    print(

        f"Average Loser: "

        f"£{stats['average_loser']:,.2f}"

    )

    print(

        f"Best Trade: "

        f"£{stats['best_trade']:,.2f}"

    )

    print(

        f"Worst Trade: "

        f"£{stats['worst_trade']:,.2f}"

    )

    print(

        f"Realised PnL: "

        f"£{stats['realised_pnl']:,.2f}"

    )