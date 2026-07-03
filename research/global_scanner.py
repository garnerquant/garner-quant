from pathlib import Path

import numpy as np
import pandas as pd

from data.market_data import download_market_data, get_price_field
from indicators.technical import technical_score


UNIVERSE_DIR = Path("data/universes")
OUTPUT_DIR = Path("data/global_scanner")
HISTORY_DIR_NAME = "history"
MAX_HISTORY_SNAPSHOTS = 100
REQUIRED_COLUMNS = [
    "symbol",
    "yahoo_ticker",
    "name",
    "country",
    "region",
    "exchange",
    "currency",
    "asset_class",
    "index_source",
    "sector",
    "active",
]


def load_universe(universe_dir=UNIVERSE_DIR):
    universe_dir = Path(universe_dir)
    files = sorted(universe_dir.glob("*.csv"))

    if not files:
        raise FileNotFoundError(f"No universe CSV files found in {universe_dir}")

    frames = []
    for path in files:
        frame = pd.read_csv(path)
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")

        frame = frame[REQUIRED_COLUMNS].copy()
        frame["source_file"] = path.name
        frames.append(frame)

    universe = pd.concat(frames, ignore_index=True)
    universe["yahoo_ticker"] = universe["yahoo_ticker"].astype(str).str.strip()
    universe = universe[universe["yahoo_ticker"] != ""]
    universe["active"] = (
        universe["active"].astype(str).str.strip().str.lower().isin(
            {"1", "true", "yes", "y"}
        )
    )
    universe = universe.drop_duplicates(subset=["yahoo_ticker"], keep="first")
    return universe


def active_universe(universe):
    return universe[universe["active"]].copy().reset_index(drop=True)


def _empty_field_frame(index, tickers):
    return pd.DataFrame(index=index, columns=tickers, dtype=float)


def _field_frame(market_data, field, tickers):
    try:
        frame = get_price_field(market_data, field)
    except Exception:
        return _empty_field_frame(pd.Index([], name="Date"), tickers)

    if not isinstance(frame, pd.DataFrame):
        frame = pd.DataFrame(frame)

    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame[frame.index.notna()].sort_index()

    for ticker in tickers:
        if ticker not in frame.columns:
            frame[ticker] = np.nan

    return frame[tickers]


def download_recent_data(tickers, period="1y"):
    market_data = download_market_data(tickers, period=period)
    prices = _field_frame(market_data, "Close", tickers)
    volumes = _field_frame(market_data, "Volume", tickers)
    return prices, volumes


def _latest_value(series):
    valid = series.dropna()
    if valid.empty:
        return np.nan, pd.NaT
    return valid.iloc[-1], valid.index[-1]


def _technical_score_latest(ticker, close, volume):
    valid_close = close.dropna()
    if len(valid_close) < 60:
        return np.nan

    aligned_volume = None
    if volume is not None and volume.notna().sum() > 0:
        aligned_volume = volume.reindex(close.index)

    try:
        score = technical_score(ticker, close.ffill(), aligned_volume)
    except Exception:
        return np.nan

    valid_score = score.dropna()
    if valid_score.empty:
        return np.nan
    return float(valid_score.iloc[-1])


def calculate_quality(universe, prices, volumes):
    if prices.empty:
        reference_date = pd.Timestamp.utcnow().normalize().tz_localize(None)
    else:
        reference_date = prices.index.max()

    stale_cutoff = reference_date - pd.Timedelta(days=7)
    rows = []

    for _, asset in universe.iterrows():
        ticker = asset["yahoo_ticker"]
        close = pd.to_numeric(prices.get(ticker, pd.Series(dtype=float)), errors="coerce")
        volume = pd.to_numeric(
            volumes.get(ticker, pd.Series(dtype=float)),
            errors="coerce",
        )

        latest_close, latest_price_date = _latest_value(close)
        valid_bar_count = int(close.notna().sum())
        missing_close_pct = float(close.isna().mean()) if len(close) else 1.0
        latest_close_present = bool(pd.notna(latest_close))
        stale_latest_price = (
            True
            if pd.isna(latest_price_date)
            else bool(pd.Timestamp(latest_price_date) < stale_cutoff)
        )
        volume_present = bool(volume.notna().sum() > 0 and volume.fillna(0).tail(20).sum() > 0)
        avg_traded_value_60d = float((close * volume).dropna().tail(60).mean())
        if not np.isfinite(avg_traded_value_60d):
            avg_traded_value_60d = 0.0

        tech_score = _technical_score_latest(ticker, close, volume)
        data_quality_pass = (
            latest_close_present
            and valid_bar_count >= 126
            and missing_close_pct <= 0.10
            and not stale_latest_price
            and volume_present
        )

        score = 0.0
        score += 20.0 if latest_close_present else 0.0
        score += min(valid_bar_count / 252.0, 1.0) * 20.0
        score += max(0.0, 1.0 - missing_close_pct) * 20.0
        score += 20.0 if not stale_latest_price else 0.0
        score += 10.0 if volume_present else 0.0
        score += 0.0 if pd.isna(tech_score) else float(tech_score) * 10.0
        score += min(np.log10(max(avg_traded_value_60d, 1.0)) * 2.0, 20.0)

        rows.append(
            {
                **asset.to_dict(),
                "latest_close": latest_close,
                "latest_price_date": latest_price_date,
                "latest_close_present": latest_close_present,
                "valid_bar_count": valid_bar_count,
                "missing_close_pct": missing_close_pct,
                "stale_latest_price": stale_latest_price,
                "volume_present": volume_present,
                "avg_traded_value_60d": avg_traded_value_60d,
                "technical_score": tech_score,
                "data_quality_pass": data_quality_pass,
                "scanner_score": score,
            }
        )

    return pd.DataFrame(rows)


def rank_candidates(validated, top_n=15):
    rankings = validated.copy()
    rankings = rankings.sort_values(
        ["data_quality_pass", "scanner_score", "avg_traded_value_60d", "yahoo_ticker"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)
    rankings["rank"] = range(1, len(rankings) + 1)
    rankings["selected_for_research"] = False

    selected_index = rankings[rankings["data_quality_pass"]].head(top_n).index
    rankings.loc[selected_index, "selected_for_research"] = True
    selected = rankings.loc[selected_index].copy()
    return rankings, selected


def history_dir(output_dir):
    return Path(output_dir) / HISTORY_DIR_NAME


def history_files(output_dir):
    directory = history_dir(output_dir)
    if not directory.exists():
        return []
    return sorted(directory.glob("*_rankings.csv"))


def latest_history_snapshot(output_dir):
    files = history_files(output_dir)
    if not files:
        return pd.DataFrame()

    try:
        return pd.read_csv(files[-1])
    except Exception:
        return pd.DataFrame()


def _bool_series(frame, column):
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype=bool)

    return frame[column].astype(str).str.strip().str.lower().isin(
        {"1", "true", "yes", "y"}
    )


def consecutive_seen_count(ticker, previous_snapshots):
    count = 1
    for snapshot in reversed(previous_snapshots):
        if "yahoo_ticker" not in snapshot.columns:
            break

        tickers = set(snapshot["yahoo_ticker"].dropna().astype(str))
        if str(ticker) not in tickers:
            break

        count += 1

    return count


def add_history_comparison(rankings, output_dir):
    rankings = rankings.copy()
    files = history_files(output_dir)
    previous = latest_history_snapshot(output_dir)

    if previous.empty or "yahoo_ticker" not in previous.columns:
        rankings["previous_rank"] = pd.NA
        rankings["current_rank"] = rankings["rank"]
        rankings["rank_change"] = pd.NA
        rankings["new_entry"] = True
        rankings["dropped_out"] = False
        rankings["consecutive_days_seen"] = 1
        return rankings

    previous_rank = previous.set_index("yahoo_ticker")["rank"].to_dict()
    previous_snapshots = []
    for path in files:
        try:
            previous_snapshots.append(pd.read_csv(path))
        except Exception:
            continue

    previous_values = rankings["yahoo_ticker"].map(previous_rank)
    rankings["previous_rank"] = previous_values
    rankings["current_rank"] = rankings["rank"]
    rankings["rank_change"] = previous_values - rankings["rank"]
    rankings["new_entry"] = previous_values.isna()
    rankings["dropped_out"] = False
    rankings["consecutive_days_seen"] = rankings["yahoo_ticker"].apply(
        lambda ticker: consecutive_seen_count(ticker, previous_snapshots)
    )
    return rankings


def write_history_snapshot(rankings, output_dir, run_timestamp):
    directory = history_dir(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    snapshot = rankings.copy()
    snapshot["scanner_run_timestamp"] = run_timestamp.isoformat(timespec="seconds")
    filename = f"{pd.Timestamp(run_timestamp).strftime('%Y-%m-%d_%H%M%S_%f')}_rankings.csv"
    snapshot.to_csv(directory / filename, index=False)

    files = history_files(output_dir)
    for old_file in files[:-MAX_HISTORY_SNAPSHOTS]:
        try:
            old_file.unlink()
        except Exception:
            pass


def run_global_scanner(
    universe_dir=UNIVERSE_DIR,
    output_dir=OUTPUT_DIR,
    period="1y",
    top_n=15,
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_timestamp = pd.Timestamp.now(tz="UTC")

    universe = load_universe(universe_dir)
    active = active_universe(universe)
    tickers = active["yahoo_ticker"].tolist()

    prices, volumes = download_recent_data(tickers, period=period)
    validated = calculate_quality(active, prices, volumes)
    rankings, selected = rank_candidates(validated, top_n=top_n)
    rankings = add_history_comparison(rankings, output_dir)
    selected = rankings[rankings["selected_for_research"]].copy()

    validated.to_csv(output_dir / "universe_validated.csv", index=False)
    rankings.to_csv(output_dir / "latest_rankings.csv", index=False)
    selected.to_csv(output_dir / "selected_candidates.csv", index=False)
    write_history_snapshot(rankings, output_dir, run_timestamp)

    return {
        "universe_rows": len(universe),
        "active_rows": len(active),
        "validated_rows": len(validated),
        "selected_rows": len(selected),
        "quality_failures": int((~validated["data_quality_pass"]).sum()),
        "history_snapshots": len(history_files(output_dir)),
        "output_dir": str(output_dir),
    }


def main():
    result = run_global_scanner()
    print("Global Opportunity Scanner completed")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
