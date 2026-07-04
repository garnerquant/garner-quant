import pandas as pd

from execution.trade_audit import build_trade_audit_trail_from_ledger
from execution.trade_ledger import load_trade_ledger


def empty_trade_stats(source="none"):
    return {
        "total_trades": 0,
        "win_rate": 0,
        "profit_factor": 0,
        "average_winner": 0,
        "average_loser": 0,
        "best_trade": 0,
        "worst_trade": 0,
        "realised_pnl": 0,
        "closed_trades": 0,
        "open_positions": 0,
        "source": source,
    }


def analyse_closed_trades(closed_trades, source="trade_ledger_v1.csv", open_positions=0):
    if closed_trades is None or closed_trades.empty:
        stats = empty_trade_stats(source=source)
        stats["open_positions"] = open_positions
        return stats

    trades = closed_trades.copy()
    trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)

    winners = trades[trades["pnl"] > 0]
    losers = trades[trades["pnl"] <= 0]
    total_trades = len(trades)
    gross_profit = winners["pnl"].sum()
    gross_loss = losers["pnl"].abs().sum()

    return {
        "total_trades": total_trades,
        "win_rate": len(winners) / total_trades if total_trades else 0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else 0,
        "average_winner": winners["pnl"].mean() if not winners.empty else 0,
        "average_loser": losers["pnl"].mean() if not losers.empty else 0,
        "best_trade": trades["pnl"].max() if not trades.empty else 0,
        "worst_trade": trades["pnl"].min() if not trades.empty else 0,
        "realised_pnl": trades["pnl"].sum(),
        "closed_trades": total_trades,
        "open_positions": open_positions,
        "source": source,
    }


def analyse_trade_ledger(ledger, open_positions=0):
    audit = build_trade_audit_trail_from_ledger(ledger)
    return analyse_closed_trades(
        audit,
        source="trade_ledger_v1.csv",
        open_positions=open_positions,
    )


def analyse_authoritative_trades(
    legacy_journal=None,
    ledger_path="trade_ledger_v1.csv",
    open_positions=0,
):
    ledger = load_trade_ledger(ledger_path)
    if not ledger.empty:
        return analyse_trade_ledger(ledger, open_positions=open_positions)
    stats = analyse_trade_journal(legacy_journal)
    stats["source"] = "trade_journal_v3.csv"
    stats["closed_trades"] = stats.get("total_trades", 0)
    stats["open_positions"] = open_positions
    return stats


def analyse_trade_journal(journal):

    if len(journal) == 0:

        return empty_trade_stats(source="trade_journal_v3.csv")

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

    stats = {

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
    stats["closed_trades"] = total_trades
    stats["open_positions"] = 0
    stats["source"] = "trade_journal_v3.csv"
    return stats


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
