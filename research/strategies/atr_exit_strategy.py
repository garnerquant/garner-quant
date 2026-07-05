from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

try:
    from config import STARTING_CASH
except Exception:
    STARTING_CASH = 10000.0

from research.experiment_runner import ExperimentContext, ExperimentRunData
from research.strategies.baseline_strategy import BaselineStrategy


@dataclass(frozen=True)
class AtrExitParameters:
    atr_period: int = 14
    atr_multiplier: float = 2.0
    initial_stop: bool = True
    trailing_stop_enabled: bool = True
    break_even_trigger: float = 0.0
    atr_method: str = "wilder"

    def as_dict(self):
        return {
            "atr_period": int(self.atr_period),
            "atr_multiplier": float(self.atr_multiplier),
            "initial_stop": bool(self.initial_stop),
            "trailing_stop_enabled": bool(self.trailing_stop_enabled),
            "break_even_trigger": float(self.break_even_trigger),
            "atr_method": str(self.atr_method),
        }


class AtrExitStrategy:
    def __init__(self, parameters=None, baseline=None):
        self.parameters = (
            parameters
            if isinstance(parameters, AtrExitParameters)
            else AtrExitParameters(**(parameters or {}))
        )
        self.baseline = baseline or BaselineStrategy()
        self.name = (
            "atr_exit_"
            f"p{self.parameters.atr_period}_"
            f"m{self.parameters.atr_multiplier}_"
            f"{self.parameters.atr_method}"
        )

    def _read_csv(self, base_path, filename):
        path = Path(base_path) / filename
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path)

    def _normalise_prices(self, prices):
        if prices.empty:
            return prices
        result = prices.copy()
        date_column = "Date" if "Date" in result.columns else "date"
        if date_column in result.columns:
            result[date_column] = pd.to_datetime(result[date_column], errors="coerce")
            result = result.dropna(subset=[date_column]).set_index(date_column)
        else:
            result.index = pd.to_datetime(result.index, errors="coerce")
            result = result[result.index.notna()]
        result = result.sort_index()
        result.index = result.index.normalize()
        return result

    def _atr_series(self, close):
        close = pd.to_numeric(close, errors="coerce")
        true_range = close.diff().abs()
        true_range.iloc[0] = 0.0
        period = max(1, int(self.parameters.atr_period))
        method = str(self.parameters.atr_method).lower()
        if method in {"ema", "exponential"}:
            return true_range.ewm(span=period, adjust=False).mean()
        if method in {"wilder", "rma"}:
            return true_range.ewm(alpha=1 / period, adjust=False).mean()
        return true_range.rolling(period, min_periods=1).mean()

    def _atr_frame(self, prices):
        return pd.DataFrame(
            {
                ticker: self._atr_series(prices[ticker])
                for ticker in prices.columns
            },
            index=prices.index,
        )

    def _baseline_buys(self, context):
        baseline_data = self.baseline.run(context)
        trades = baseline_data.trades.copy()
        if trades.empty or "action" not in trades.columns:
            return trades.iloc[0:0], baseline_data
        actions = trades["action"].astype(str).str.upper()
        buys = trades[actions.eq("BUY")].copy()
        buys["date"] = pd.to_datetime(buys["date"], errors="coerce").dt.normalize()
        buys = buys.dropna(subset=["date"]).sort_values(["date", "ticker"])
        return buys.reset_index(drop=True), baseline_data

    def _initial_stop(self, entry_price, atr_value):
        if not self.parameters.initial_stop:
            return float("-inf")
        return float(entry_price) - (float(self.parameters.atr_multiplier) * float(atr_value or 0))

    def _updated_stop(self, position, close_price, atr_value):
        position["highest_close"] = max(position["highest_close"], close_price)
        atr_stop = position["highest_close"] - (
            float(self.parameters.atr_multiplier) * float(atr_value or 0)
        )
        position["highest_atr_stop"] = max(position["highest_atr_stop"], atr_stop)
        if self.parameters.trailing_stop_enabled:
            position["current_trailing_stop"] = max(
                position["current_trailing_stop"],
                position["highest_atr_stop"],
            )
        if (
            self.parameters.break_even_trigger
            and close_price >= position["entry_price"] * (1 + self.parameters.break_even_trigger)
        ):
            position["current_trailing_stop"] = max(
                position["current_trailing_stop"],
                position["entry_price"],
            )
        return position["current_trailing_stop"]

    def run(self, context: ExperimentContext) -> ExperimentRunData:
        base_path = Path(context.base_path)
        prices = self._normalise_prices(self._read_csv(base_path, "prices_v2.csv"))
        weights = self._read_csv(base_path, "weights_v2.csv")
        buys, baseline_data = self._baseline_buys(context)
        if prices.empty:
            return ExperimentRunData(
                name=self.name,
                portfolio=pd.DataFrame(),
                trades=pd.DataFrame(),
                prices=prices,
                weights=weights,
                metadata={"error": "prices_v2.csv unavailable"},
            )

        atr_values = self._atr_frame(prices)
        buy_rows_by_date = {
            date: frame.to_dict(orient="records")
            for date, frame in buys.groupby("date")
        }
        cash = float(STARTING_CASH)
        open_lots = []
        trade_rows = []
        equity_rows = []
        realised_pnl = 0.0
        lot_counter = 0

        for date, latest_prices in prices.iterrows():
            for position in list(open_lots):
                ticker = position["ticker"]
                close_price = latest_prices.get(ticker)
                if pd.isna(close_price):
                    continue
                close_price = float(close_price)
                stop = self._updated_stop(
                    position,
                    close_price,
                    atr_values.loc[date, ticker] if ticker in atr_values.columns else 0.0,
                )
                if close_price >= stop:
                    continue
                value = close_price * position["shares"]
                pnl = (close_price - position["entry_price"]) * position["shares"]
                realised_pnl += pnl
                cash += value
                trade_rows.append(
                    {
                        "date": date,
                        "action": "SELL",
                        "ticker": ticker,
                        "price": close_price,
                        "shares": position["shares"],
                        "value": value,
                        "pnl": pnl,
                        "pnl_percent": (close_price / position["entry_price"]) - 1,
                        "reason": "ATR TRAILING STOP",
                        "holding_days": max(0, (date - position["entry_date"]).days),
                        "lot_id": position["lot_id"],
                        "trailing_stop": stop,
                    }
                )
                open_lots.remove(position)

            for row in buy_rows_by_date.get(date, []):
                ticker = row["ticker"]
                if ticker not in prices.columns:
                    continue
                entry_price = float(row.get("price", latest_prices.get(ticker)))
                shares = float(row.get("shares", 0.0))
                value = float(row.get("value", entry_price * shares))
                if shares <= 0 or value <= 0:
                    continue
                lot_counter += 1
                atr_value = (
                    atr_values.loc[date, ticker]
                    if ticker in atr_values.columns
                    else 0.0
                )
                initial_stop = self._initial_stop(entry_price, atr_value)
                cash -= value
                position = {
                    "lot_id": f"atr_lot_{lot_counter:05d}",
                    "ticker": ticker,
                    "entry_date": date,
                    "entry_price": entry_price,
                    "shares": shares,
                    "value": value,
                    "highest_close": entry_price,
                    "highest_atr_stop": initial_stop,
                    "current_trailing_stop": initial_stop,
                }
                open_lots.append(position)
                trade_rows.append(
                    {
                        "date": date,
                        "action": "BUY",
                        "ticker": ticker,
                        "price": entry_price,
                        "shares": shares,
                        "value": value,
                        "pnl": 0.0,
                        "pnl_percent": 0.0,
                        "reason": "SIGNAL ENTRY",
                        "holding_days": 0,
                        "lot_id": position["lot_id"],
                        "trailing_stop": initial_stop,
                    }
                )

            positions_value = 0.0
            unrealised_pnl = 0.0
            for position in open_lots:
                ticker = position["ticker"]
                close_price = latest_prices.get(ticker)
                if pd.isna(close_price):
                    close_price = position["entry_price"]
                close_price = float(close_price)
                positions_value += close_price * position["shares"]
                unrealised_pnl += (close_price - position["entry_price"]) * position["shares"]

            portfolio_value = cash + positions_value
            peak = max(portfolio_value, equity_rows[-1]["peak"] if equity_rows else portfolio_value)
            equity_rows.append(
                {
                    "date": date,
                    "cash": cash,
                    "positions_value": positions_value,
                    "portfolio_value": portfolio_value,
                    "realised_pnl": realised_pnl,
                    "unrealised_pnl": unrealised_pnl,
                    "open_positions": len(open_lots),
                    "peak": peak,
                    "drawdown": (portfolio_value / peak) - 1 if peak else 0.0,
                }
            )

        if len(prices.index):
            final_date = prices.index[-1]
            final_prices = prices.loc[final_date]
            for position in list(open_lots):
                ticker = position["ticker"]
                close_price = final_prices.get(ticker)
                if pd.isna(close_price):
                    close_price = position["entry_price"]
                close_price = float(close_price)
                value = close_price * position["shares"]
                pnl = (close_price - position["entry_price"]) * position["shares"]
                trade_rows.append(
                    {
                        "date": final_date,
                        "action": "SELL",
                        "ticker": ticker,
                        "price": close_price,
                        "shares": position["shares"],
                        "value": value,
                        "pnl": pnl,
                        "pnl_percent": (close_price / position["entry_price"]) - 1,
                        "reason": "END OF TEST",
                        "holding_days": max(0, (final_date - position["entry_date"]).days),
                        "lot_id": position["lot_id"],
                        "trailing_stop": position["current_trailing_stop"],
                    }
                )
                open_lots.remove(position)

        return ExperimentRunData(
            name=self.name,
            portfolio=pd.DataFrame(equity_rows),
            trades=pd.DataFrame(trade_rows),
            prices=self._read_csv(base_path, "prices_v2.csv"),
            weights=weights,
            metadata={
                "parameters": self.parameters.as_dict(),
                "entry_source": baseline_data.name,
                "baseline_buy_count": int(len(buys)),
                "exit_source": "atr_trailing_stop_wrapper",
            },
        )
