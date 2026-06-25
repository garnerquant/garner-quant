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