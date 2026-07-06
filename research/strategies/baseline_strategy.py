from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.experiment_runner import ExperimentContext, ExperimentRunData
from research.live_rule_backtest import run_from_saved_files


class BaselineStrategy:
    name = "Current binary exit"

    def __init__(self, experiment_config=None):
        self.experiment_config = dict(experiment_config or {})
        self._cache = {}

    def _read_optional_csv(self, base_path, filename):
        path = Path(base_path) / filename
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path)

    def run(self, context: ExperimentContext) -> ExperimentRunData:
        base_path = Path(context.base_path)
        cache_key = (str(base_path.resolve()), tuple(sorted(self.experiment_config.items())))
        if cache_key in self._cache:
            return self._cache[cache_key]

        cwd = Path.cwd()
        try:
            # run_from_saved_files reads the existing research artifacts by name.
            # Switching cwd keeps the strategy generic for scratch test roots.
            import os

            os.chdir(base_path)
            equity_curve, _holdings, trade_journal, summary = run_from_saved_files(
                experiment_config=self.experiment_config,
            )
        finally:
            os.chdir(cwd)

        prices = self._read_optional_csv(base_path, "prices_v2.csv")
        weights = self._read_optional_csv(base_path, "weights_v2.csv")
        result = ExperimentRunData(
            name=self.name,
            portfolio=equity_curve,
            trades=trade_journal,
            prices=prices,
            weights=weights,
            metadata={
                "summary": summary,
                "entry_source": "signals_v2.csv",
                "exit_source": "current baseline signal/stops",
            },
        )
        self._cache[cache_key] = result
        return result
