def safe_sum(df, column):
    if df is None or df.empty or column not in df.columns:
        return 0
    return df[column].sum()


def safe_mean(df, column):
    if df is None or df.empty or column not in df.columns:
        return 0
    return df[column].mean()


def count_rows(df):
    if df is None or df.empty:
        return 0
    return len(df)


def unrealised_pnl_from_holdings(holdings, fallback=0):
    if holdings is None or holdings.empty:
        return fallback

    column_lookup = {
        str(column).lower().replace(" ", "_"): column
        for column in holdings.columns
    }
    pnl_column = column_lookup.get("unrealised_pnl")

    if pnl_column is None:
        return fallback

    values = safe_sum(holdings, pnl_column)

    try:
        return float(values)
    except Exception:
        return fallback
