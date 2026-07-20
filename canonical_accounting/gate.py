from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from canonical_accounting.generation import GenerationError, load_active_generation


def canonical_execution_block_reason(
    *,
    state_root=Path("data/accounting_generations"),
    runtime_status_path=Path("data/live_runtime_status.json"),
    now=None,
    max_runtime_status_age=timedelta(minutes=15),
) -> str | None:
    try:
        generation = load_active_generation(state_root)
    except GenerationError as exc:
        return str(exc)
    if generation.manifest.get("execution_ready") is not True:
        return str(generation.manifest.get("execution_block_reason") or "canonical generation is not execution-ready")
    try:
        registry = json.loads(
            (generation.path / "instrument_registry_snapshot.json").read_text(encoding="utf-8")
        )
    except Exception:
        return "canonical instrument metadata snapshot is invalid"
    unsupported = sorted(
        symbol for symbol, item in registry.get("symbols", {}).items()
        if item.get("supported") is not True
    )
    if unsupported:
        return "canonical instrument metadata is unverified: " + ", ".join(unsupported)
    if generation.portfolio.empty is False:
        if generation.holdings.empty:
            return "canonical opening positions do not have reconciled holdings"
        required = {"fx_rate_to_base", "fx_timestamp", "fx_source", "valuation_status"}
        if not required.issubset(generation.holdings.columns):
            return "canonical holdings FX metadata is incomplete"
        if not generation.holdings["valuation_status"].astype(str).eq("valid").all():
            return "canonical holdings contain incomplete valuations"
    broker = generation.broker
    if len(broker) != 1 or str(broker.iloc[0].get("reconciliation_status")) != "reconciled":
        return "canonical broker state is not reconciled"
    if not Path(runtime_status_path).is_file():
        return "runtime health status is missing"
    try:
        status = json.loads(Path(runtime_status_path).read_text(encoding="utf-8"))
        timestamp = status.get("last_updated") or status.get("timestamp") or status.get("generated_at")
        instant = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return "runtime health timestamp is timezone-ambiguous"
    except Exception:
        return "runtime health status is invalid"
    current = now or datetime.now(timezone.utc)
    if current.astimezone(timezone.utc) - instant.astimezone(timezone.utc) > max_runtime_status_age:
        return "runtime health status is stale"
    return None
