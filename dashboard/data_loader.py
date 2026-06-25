import pandas as pd


def load_csv(filename):
    try:
        return pd.read_csv(filename)
    except FileNotFoundError:
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()