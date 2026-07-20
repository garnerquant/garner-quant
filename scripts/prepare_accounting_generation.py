from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canonical_accounting.generation import (
    DEFAULT_STATE_ROOT, POINTER_FILE, build_cash_only_generation,
    load_generation, sha256_file,
)
from canonical_accounting.instruments import INSTRUMENT_REGISTRY, validate_registry
from execution.atomic_io import atomic_write_json
from runtime.locks import acquire_runtime_write_lock


LEGACY_FILES = (
    "trade_ledger_v1.csv", "paper_portfolio_v3.csv", "holdings_report.csv",
    "broker_account.csv", "paper_30_day_tracker.csv",
)


def hashes(root):
    return {name: sha256_file(Path(root) / name) for name in LEGACY_FILES if (Path(root) / name).is_file()}


def dry_run(root=ROOT, generation_id=None, keep_dir=None):
    root = Path(root)
    generation_id = generation_id or datetime.now(timezone.utc).strftime("acct-v2-%Y%m%dT%H%M%SZ")
    before = hashes(root)
    temp_owner = None
    if keep_dir:
        destination = Path(keep_dir).resolve()
    else:
        temp_root = Path(root) / ".tmp"
        temp_root.mkdir(exist_ok=True)
        destination = temp_root / f"garner-accounting-dry-run-{uuid.uuid4().hex}" / generation_id
    manifest = build_cash_only_generation(
        destination, generation_id=generation_id, legacy_root=root,
    )
    bundle = load_generation(destination, expected_id=generation_id)
    broker = bundle.broker.iloc[0]
    reconciliation = {
        "base_cash": float(broker["base_cash"]),
        "base_positions_value": float(broker["base_positions_value"]),
        "base_total_equity": float(broker["base_total_equity"]),
        "cash_plus_positions_equals_equity": abs(
            float(broker["base_cash"]) + float(broker["base_positions_value"])
            - float(broker["base_total_equity"])
        ) <= 0.01,
        "opening_positions": len(bundle.portfolio),
        "performance_reset": bool(manifest["performance_reset"]),
    }
    after = hashes(root)
    classification = json.loads(
        (destination / "legacy_classification.json").read_text(encoding="utf-8")
    )
    registry_validation = validate_registry()
    report = {
        "mode": "dry_run", "generation_id": generation_id,
        "proposed_path": str(destination), "manifest": manifest,
        "instrument_registry": registry_validation,
        "instrument_status": {
            symbol: {"supported": item.supported, "source": item.metadata_source,
                     "currency": item.instrument_currency, "provider_price_unit": item.provider_price_unit,
                     "price_scale": str(item.price_scale)}
            for symbol, item in INSTRUMENT_REGISTRY.items()
        },
        "reconciliation": reconciliation,
        "opening_events": bundle.ledger.to_dict(orient="records"),
        "opening_positions": bundle.portfolio.to_dict(orient="records"),
        "legacy_classification": classification,
        "provider_validation": {
            "status": "verified" if registry_validation["valid"] else "blocked",
            "reason": (
                "all registry entries carry explicit provider evidence"
                if registry_validation["valid"]
                else "one or more instruments are unsupported pending provider verification"
            ),
        },
        "fx_validation": {
            "status": "not_required_for_cash_only_opening",
            "quotes": [],
        },
        "legacy_hashes_before": before, "legacy_hashes_after": after,
        "legacy_files_unchanged": before == after,
        "activation_ready": bool(
            reconciliation["cash_plus_positions_equals_equity"]
            and before == after and registry_validation["valid"]
            and manifest.get("execution_ready") is True
        ),
    }
    if not keep_dir:
        report["rollback_verified"] = True
        shutil.rmtree(destination.parent)
        report["proposed_path_removed"] = not destination.exists()
    return report


def activate(root, generation_id):
    state_root = Path(root) / DEFAULT_STATE_ROOT
    generation = load_generation(state_root / "generations" / generation_id, expected_id=generation_id)
    pointer = state_root / POINTER_FILE
    pointer.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        {"generation_id": generation.generation_id, "activated_at": datetime.now(timezone.utc).isoformat()},
        pointer,
    )
    return {"activated": generation_id, "execution_ready": generation.manifest.get("execution_ready", False)}


def deactivate(root):
    pointer = Path(root) / DEFAULT_STATE_ROOT / POINTER_FILE
    if not pointer.exists():
        return {"deactivated": False, "reason": "pointer absent"}
    backup = pointer.with_name(f"{pointer.name}.deactivated-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    with acquire_runtime_write_lock(context="canonical_accounting_deactivation"):
        pointer.replace(backup)
    return {"deactivated": True, "recoverable_backup": str(backup)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare or explicitly activate canonical accounting v2.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--generation-id")
    parser.add_argument("--keep-dir")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--deactivate", action="store_true")
    args = parser.parse_args(argv)
    if args.activate and args.deactivate:
        parser.error("choose only one of --activate or --deactivate")
    if args.activate:
        if not args.generation_id:
            parser.error("--activate requires --generation-id")
        result = activate(args.root, args.generation_id)
    elif args.deactivate:
        result = deactivate(args.root)
    else:
        result = dry_run(args.root, args.generation_id, args.keep_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
