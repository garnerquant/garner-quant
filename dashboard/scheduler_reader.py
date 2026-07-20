from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from runtime.bar_scheduler import ProcessedBarStore, SchedulerError


@dataclass(frozen=True)
class SchedulerDashboardState:
    instruments: dict
    duplicate_suppressions: dict
    error: str | None = None


def load_scheduler_state(path=Path("data/runtime/processed_strategy_bars.json")):
    try:
        health = ProcessedBarStore(path=path).health()
    except SchedulerError as exc:
        return SchedulerDashboardState({}, {}, str(exc))
    return SchedulerDashboardState(
        instruments={key: dict(value) for key, value in health["instruments"].items()},
        duplicate_suppressions=dict(health["duplicate_suppressions"]),
    )
