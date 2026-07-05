from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import pandas as pd

from research.experiment_metrics import calculate_experiment_metrics, compare_metrics
from research.experiment_registry import (
    DEFAULT_FRAMEWORK_REGISTRY,
    append_registry_entry,
    git_commit_hash,
    reproducible_experiment_id,
)
from research.experiment_report import DEFAULT_REPORT_DIR, write_experiment_reports


@dataclass(frozen=True)
class ExperimentContext:
    base_path: Path = Path(".")
    metadata: dict | None = None


@dataclass
class ExperimentRunData:
    name: str
    portfolio: pd.DataFrame
    trades: pd.DataFrame
    prices: pd.DataFrame | None = None
    weights: pd.DataFrame | None = None
    metadata: dict | None = None


class ExperimentStrategy(Protocol):
    name: str

    def run(self, context: ExperimentContext) -> ExperimentRunData:
        ...


class SavedFilesStrategy:
    def __init__(
        self,
        name="saved_runtime_baseline",
        *,
        portfolio_file="portfolio_v2.csv",
        trades_file="trade_audit_trail.csv",
        prices_file="prices_v2.csv",
        weights_file="weights_v2.csv",
    ):
        self.name = name
        self.portfolio_file = portfolio_file
        self.trades_file = trades_file
        self.prices_file = prices_file
        self.weights_file = weights_file

    def _read_csv(self, base_path, relative_path):
        path = Path(base_path) / relative_path
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path)

    def run(self, context: ExperimentContext) -> ExperimentRunData:
        base_path = context.base_path
        return ExperimentRunData(
            name=self.name,
            portfolio=self._read_csv(base_path, self.portfolio_file),
            trades=self._read_csv(base_path, self.trades_file),
            prices=self._read_csv(base_path, self.prices_file),
            weights=self._read_csv(base_path, self.weights_file),
            metadata={
                "portfolio_file": self.portfolio_file,
                "trades_file": self.trades_file,
                "prices_file": self.prices_file,
                "weights_file": self.weights_file,
            },
        )


def utc_timestamp(value=None):
    value = value or datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def decide(comparison):
    improved = comparison.get("improved_metrics", [])
    regressed = comparison.get("regressed_metrics", [])
    if regressed:
        return "REJECT"
    if improved:
        return "KEEP"
    return "NEEDS MORE TESTING"


def strategy_payload(strategy):
    return {
        "class": strategy.__class__.__name__,
        "name": getattr(strategy, "name", ""),
        "attributes": {
            key: value
            for key, value in vars(strategy).items()
            if not key.startswith("_")
        },
    }


def run_experiment(
    *,
    baseline: ExperimentStrategy,
    candidate: ExperimentStrategy,
    description,
    parameters=None,
    metadata=None,
    base_path=".",
    registry_path=DEFAULT_FRAMEWORK_REGISTRY,
    report_dir=DEFAULT_REPORT_DIR,
    timestamp=None,
    experiment_id=None,
    decision_fn=None,
):
    timestamp = utc_timestamp(timestamp)
    context = ExperimentContext(base_path=Path(base_path), metadata=metadata or {})
    baseline_data = baseline.run(context)
    candidate_data = candidate.run(context)
    baseline_metrics = calculate_experiment_metrics(
        portfolio=baseline_data.portfolio,
        trades=baseline_data.trades,
        prices=baseline_data.prices,
        weights=baseline_data.weights,
    )
    candidate_metrics = calculate_experiment_metrics(
        portfolio=candidate_data.portfolio,
        trades=candidate_data.trades,
        prices=candidate_data.prices,
        weights=candidate_data.weights,
    )
    comparison = compare_metrics(baseline_metrics, candidate_metrics)
    identity_payload = {
        "timestamp": timestamp,
        "description": description,
        "parameters": parameters or {},
        "baseline": strategy_payload(baseline),
        "candidate": strategy_payload(candidate),
    }
    experiment_id = experiment_id or reproducible_experiment_id(identity_payload)
    decision = (
        decision_fn(baseline_metrics, candidate_metrics, comparison)
        if decision_fn is not None
        else decide(comparison)
    )
    result = {
        "experiment_id": experiment_id,
        "date": timestamp,
        "description": str(description),
        "git_commit": git_commit_hash(),
        "parameters": parameters or {},
        "metadata": metadata or {},
        "baseline": {
            "name": baseline_data.name,
            "metrics": baseline_metrics,
            "metadata": baseline_data.metadata or {},
        },
        "candidate": {
            "name": candidate_data.name,
            "metrics": candidate_metrics,
            "metadata": candidate_data.metadata or {},
        },
        "comparison": comparison,
        "decision": decision,
    }
    reports = write_experiment_reports(result, report_dir=report_dir)
    result["reports"] = reports
    append_registry_entry(
        {
            "experiment_id": result["experiment_id"],
            "date": result["date"],
            "description": result["description"],
            "git_commit": result["git_commit"],
            "parameters": result["parameters"],
            "result": {
                "decision": result["decision"],
                "improved_metrics": comparison["improved_metrics"],
                "regressed_metrics": comparison["regressed_metrics"],
            },
            "decision": result["decision"],
            "report_location": reports,
        },
        path=registry_path,
    )
    return result


def run_baseline_self_experiment(
    *,
    base_path=".",
    registry_path=DEFAULT_FRAMEWORK_REGISTRY,
    report_dir=DEFAULT_REPORT_DIR,
    timestamp=None,
):
    baseline = SavedFilesStrategy(name="baseline")
    candidate = SavedFilesStrategy(name="baseline_self_check")
    return run_experiment(
        baseline=baseline,
        candidate=candidate,
        description="Baseline strategy compared against itself.",
        parameters={"built_in": "baseline_self_check"},
        metadata={"purpose": "framework_end_to_end_validation"},
        base_path=base_path,
        registry_path=registry_path,
        report_dir=report_dir,
        timestamp=timestamp,
    )
