from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canonical_accounting.events import AccountingEvent
from canonical_accounting.successor import (
    SuccessorGenerationError, SuccessorGenerationWriter, create_transactional_genesis,
    load_transactional_generation, validate_lineage,
)

PROTECTED = (
    "trade_ledger_v1.csv", "paper_portfolio_v3.csv", "holdings_report.csv",
    "broker_account.csv", "paper_30_day_tracker.csv",
)
NOW = datetime(2026, 7, 22, 10, tzinfo=timezone.utc)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    issues = []
    def check(value, label):
        print(("PASS" if value else "FAIL") + ": " + label)
        if not value:
            issues.append(label)

    before = {name: digest(ROOT / name) for name in PROTECTED}
    config = json.loads((ROOT / "runtime/live_runtime_config.json").read_text(encoding="utf-8"))
    check(config.get("mode") == "monitor_only", "runtime remains monitor_only")
    check(config.get("paper_execution_enabled") is False, "paper execution remains disabled")
    production_pointer = ROOT / "data/accounting_generations/accounting_generation.json"
    pointer_before = digest(production_pointer)
    check(not production_pointer.exists(), "canonical accounting remains inactive")

    fixture = ROOT / ".tmp" / "transactional_accounting_validator"
    shutil.rmtree(fixture, ignore_errors=True)
    try:
        create_transactional_genesis(fixture / "generations/g0", generation_id="g0", timestamp=NOW, legacy_root=ROOT)
        fixture.mkdir(parents=True, exist_ok=True)
        (fixture / "accounting_generation.json").write_text(json.dumps({"generation_id": "g0"}), encoding="utf-8")
        writer = SuccessorGenerationWriter(fixture)
        event = AccountingEvent.create(
            event_id="validator-buy", event_type="BUY_FILL", timestamp=NOW + timedelta(minutes=1),
            strategy_id="validator-strategy", instrument="IUSA.L", currency="GBP", amount="5000",
            quantity="2", reference_generation="g0", correlation_id="validator-correlation", source="VALIDATOR",
        )
        prepared = writer.transact(event, valuations={"IUSA.L": {"price": "5100"}}, publish=False)
        check(json.loads((fixture / "accounting_generation.json").read_text())["generation_id"] == "g0",
              "prepared successor cannot change pointer")
        generation, snapshot, events = load_transactional_generation(prepared.path, expected_id=prepared.generation_id)
        check(generation.manifest["execution_ready"] is False, "successor is never execution-ready")
        check(snapshot.strategy_exposure["validator-strategy"].gross == snapshot.gross_exposure,
              "strategy attribution is authoritative")
        check(events[-1].event_id == event.event_id and len(validate_lineage(fixture, prepared.generation_id)) == 2,
              "event journal, manifest hashes, and lineage validate")
        writer.publish_prepared(prepared.generation_id)
        check(json.loads((fixture / "accounting_generation.json").read_text())["generation_id"] == prepared.generation_id,
              "validated prepared pointer publication is atomic")
        duplicate = writer.transact(event, publish=True)
        check(duplicate.duplicate, "duplicate event replay is idempotent")

        next_event = AccountingEvent.create(
            event_id="validator-crash", event_type="DEPOSIT", timestamp=NOW + timedelta(minutes=2),
            strategy_id="ACCOUNT", instrument="GBP-CASH", currency="GBP", amount="1", quantity="0",
            reference_generation=prepared.generation_id, correlation_id="validator-crash", source="VALIDATOR",
        )
        def crash(phase, _path):
            if phase == "after_validation":
                raise RuntimeError("simulated crash")
        try:
            SuccessorGenerationWriter(fixture, failure_hook=crash).transact(next_event, publish=True)
            check(False, "crash recovery fails closed")
        except SuccessorGenerationError:
            check(json.loads((fixture / "accounting_generation.json").read_text())["generation_id"] == prepared.generation_id,
                  "crash recovery preserves the prior pointer")
    finally:
        shutil.rmtree(fixture, ignore_errors=True)

    check(before == {name: digest(ROOT / name) for name in PROTECTED}, "validator leaves protected production files byte-identical")
    check(pointer_before == digest(production_pointer), "validator does not create or change the production pointer")
    if issues:
        raise SystemExit("Transactional canonical accounting validation failed: " + "; ".join(issues))
    print("Transactional canonical accounting validation passed.")


if __name__ == "__main__":
    main()
