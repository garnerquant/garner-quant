from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
import math
import subprocess

import pandas as pd


DEFAULT_EXPERIMENTS_FILE = Path("research") / "experiments" / "experiments.jsonl"


def _utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git_commit_hash():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except Exception:
        return None

    commit_hash = result.stdout.strip()
    return commit_hash or None


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass

    if isinstance(value, float) and not math.isfinite(value):
        return None

    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def create_experiment(
    name,
    parameter_config=None,
    metrics=None,
    status="created",
    notes="",
    experiment_id=None,
    timestamp=None,
    git_commit=None,
    extra_fields=None,
):
    experiment = {
        "experiment_id": experiment_id or str(uuid4()),
        "timestamp": timestamp or _utc_timestamp(),
        "git_commit": git_commit if git_commit is not None else _git_commit_hash(),
        "name": str(name or "Untitled experiment"),
        "parameter_config": _json_safe(parameter_config or {}),
        "metrics": _json_safe(metrics or {}),
        "status": str(status or "created"),
        "notes": str(notes or ""),
    }

    if extra_fields:
        experiment.update(_json_safe(extra_fields))

    return experiment


def save_experiment(experiment, path=DEFAULT_EXPERIMENTS_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    record = _json_safe(dict(experiment))
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, sort_keys=True) + "\n")

    return record


def load_experiments(path=DEFAULT_EXPERIMENTS_FILE):
    path = Path(path)
    if not path.exists():
        return []

    experiments = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                experiments.append(record)

    return experiments


def build_leaderboard(sort_by="sharpe_ratio", path=DEFAULT_EXPERIMENTS_FILE):
    experiments = load_experiments(path)
    rows = []

    for experiment in experiments:
        metrics = experiment.get("metrics") or {}
        row = {
            "experiment_id": experiment.get("experiment_id"),
            "campaign_id": experiment.get("campaign_id"),
            "campaign_name": experiment.get("campaign_name"),
            "variation_name": experiment.get("variation_name"),
            "exit_method": experiment.get("exit_method"),
            "sweep_id": experiment.get("sweep_id"),
            "grid_id": experiment.get("grid_id"),
            "parameter_tested": experiment.get("parameter_tested"),
            "value_tested": experiment.get("value_tested"),
            "timestamp": experiment.get("timestamp"),
            "name": experiment.get("name"),
            "status": experiment.get("status"),
            "notes": experiment.get("notes"),
            "git_commit": experiment.get("git_commit"),
        }
        for key, value in metrics.items():
            row[key] = value
        rows.append(row)

    leaderboard = pd.DataFrame(rows)
    if leaderboard.empty:
        return leaderboard

    if sort_by in leaderboard.columns:
        leaderboard[sort_by] = pd.to_numeric(
            leaderboard[sort_by],
            errors="coerce",
        )
        leaderboard = leaderboard.sort_values(
            by=sort_by,
            ascending=False,
            na_position="last",
        )

    return leaderboard.reset_index(drop=True)
