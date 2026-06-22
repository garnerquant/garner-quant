def create_signal_report(signals, weights):
    latest_date = signals.index[-1]
    latest_signals = signals.loc[latest_date]
    latest_weights = weights.loc[latest_date]

    rows = []

    for ticker in signals.columns:
        signal = latest_signals[ticker]
        weight = latest_weights[ticker]

        if signal == 1 and weight > 0:
            status = "HOLD / BUY"
        else:
            status = "AVOID / SELL"

        rows.append({
            "date": latest_date,
            "ticker": ticker,
            "signal": int(signal),
            "weight": weight,
            "status": status
        })

    return rows


def print_signal_report(rows):
    print("\n===== CURRENT SIGNAL REPORT =====")

    for row in rows:
        print(
            f"{row['ticker']} | "
            f"{row['status']} | "
            f"Weight: {row['weight']:.2%}"
        )