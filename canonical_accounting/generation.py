from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from canonical_accounting.currency import BASE_CURRENCY


SCHEMA_VERSION = "2.0"
GENERATION_FORMAT = "canonical-accounting-generation-v1"
DEFAULT_STATE_ROOT = Path("data/accounting_generations")
POINTER_FILE = "accounting_generation.json"
MANIFEST_FILE = "state_manifest.json"

LEDGER_COLUMNS = [
    "event_id", "accounting_generation", "schema_version", "timestamp",
    "symbol", "event_type", "quantity", "native_execution_price",
    "instrument_currency", "provider_price_unit", "listing_unit", "price_scale",
    "normalized_native_price", "native_gross_amount", "fee_amount",
    "fee_currency", "fx_rate_to_base", "fx_timestamp", "fx_source",
    "conversion_direction", "base_gross_amount", "base_fee",
    "base_cash_movement", "base_realised_pnl", "strategy_version",
]
PORTFOLIO_COLUMNS = [
    "accounting_generation", "symbol", "quantity", "instrument_currency",
    "provider_price_unit", "price_scale", "native_cost_basis", "base_cost_basis",
    "entry_fx_rate_to_base", "entry_fx_timestamp", "entry_fx_source",
]
HOLDINGS_COLUMNS = [
    "accounting_generation", "timestamp", "symbol", "quantity", "native_price",
    "instrument_currency", "provider_price_unit", "price_scale",
    "normalized_native_price", "native_market_value", "fx_rate_to_base",
    "fx_timestamp", "fx_source", "conversion_direction", "base_market_value",
    "base_cost_basis", "base_unrealised_pnl", "valuation_status",
]
BROKER_COLUMNS = [
    "accounting_generation", "timestamp", "base_currency", "base_cash",
    "base_positions_value", "base_total_equity", "base_realised_pnl",
    "base_unrealised_pnl", "reconciliation_status",
]
TRACKER_COLUMNS = [
    "accounting_generation", "timestamp", "base_currency", "base_cash",
    "base_positions_value", "base_total_equity", "base_realised_pnl",
    "base_unrealised_pnl", "performance_from_activation_pct",
]
ARTIFACT_COLUMNS = {
    "trade_ledger_v2.csv": LEDGER_COLUMNS,
    "paper_portfolio_v4.csv": PORTFOLIO_COLUMNS,
    "holdings_report_v2.csv": HOLDINGS_COLUMNS,
    "broker_account_v2.csv": BROKER_COLUMNS,
    "paper_tracker_v2.csv": TRACKER_COLUMNS,
}


class GenerationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_timestamp(value=None) -> str:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise GenerationError("generation timestamp must be timezone-aware")
    return instant.astimezone(timezone.utc).isoformat()


def legacy_classification(root: Path) -> dict:
    root = Path(root)
    classifications = []
    for name in (
        "trade_ledger_v1.csv", "paper_portfolio_v3.csv", "holdings_report.csv",
        "broker_account.csv", "paper_30_day_tracker.csv",
    ):
        path = root / name
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        date_column = next((c for c in ("timestamp", "date", "trade_date") if c in frame), None)
        dates = pd.to_datetime(frame[date_column], errors="coerce", utc=True) if date_column else pd.Series(dtype="datetime64[ns, UTC]")
        currencies = sorted(frame["currency"].dropna().astype(str).unique().tolist()) if "currency" in frame else []
        classification = "Ambiguous"
        classifications.append({
            "legacy_source_file": name,
            "sha256": sha256_file(path),
            "schema": list(frame.columns),
            "record_count": len(frame),
            "date_start": dates.min().isoformat() if not dates.empty and dates.notna().any() else None,
            "date_end": dates.max().isoformat() if not dates.empty and dates.notna().any() else None,
            "currencies_present": currencies,
            "known_ambiguities": [
                "No execution-time FX metadata",
                "No authoritative provider-price-unit metadata in persisted rows",
                "Nominal values were combined without currency conversion",
            ],
            "reproducibility_classification": classification,
            "included_in_canonical_accounting": False,
            "exclusion_reason": "Legacy nominal history is not currency-normalized and is economically unverified.",
        })
    return {
        "classification_version": "1",
        "generated_at": utc_timestamp(),
        "policy": "Legacy files remain audit-only and are excluded from canonical GBP totals.",
        "sources": classifications,
    }


def _write_csv(path: Path, columns: list[str], rows: list[dict] | None = None) -> None:
    pd.DataFrame(rows or [], columns=columns).to_csv(path, index=False, lineterminator="\n")


def build_cash_only_generation(
    destination: Path,
    *,
    generation_id: str,
    starting_cash=Decimal("10000"),
    activated_at=None,
    legacy_root=Path("."),
) -> dict:
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise GenerationError("generation destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = utc_timestamp(activated_at)
    cash = Decimal(str(starting_cash))
    if not cash.is_finite() or cash <= 0:
        raise GenerationError("opening cash must be finite and positive")

    opening_event = {
        "event_id": f"{generation_id}:opening-cash",
        "accounting_generation": generation_id,
        "schema_version": SCHEMA_VERSION,
        "timestamp": timestamp,
        "symbol": "GBP-CASH",
        "event_type": "OPENING_CASH",
        "quantity": "1",
        "native_execution_price": str(cash),
        "instrument_currency": BASE_CURRENCY,
        "provider_price_unit": "GBP",
        "listing_unit": "GBP",
        "price_scale": "1",
        "normalized_native_price": str(cash),
        "native_gross_amount": str(cash),
        "fee_amount": "0",
        "fee_currency": BASE_CURRENCY,
        "fx_rate_to_base": "1",
        "fx_timestamp": timestamp,
        "fx_source": "identity",
        "conversion_direction": "GBP->GBP",
        "base_gross_amount": str(cash),
        "base_fee": "0",
        "base_cash_movement": str(cash),
        "base_realised_pnl": "0",
        "strategy_version": "generation-initialization",
    }
    _write_csv(destination / "trade_ledger_v2.csv", LEDGER_COLUMNS, [opening_event])
    _write_csv(destination / "paper_portfolio_v4.csv", PORTFOLIO_COLUMNS)
    _write_csv(destination / "holdings_report_v2.csv", HOLDINGS_COLUMNS)
    broker = {
        "accounting_generation": generation_id, "timestamp": timestamp,
        "base_currency": BASE_CURRENCY, "base_cash": str(cash),
        "base_positions_value": "0", "base_total_equity": str(cash),
        "base_realised_pnl": "0", "base_unrealised_pnl": "0",
        "reconciliation_status": "reconciled",
    }
    _write_csv(destination / "broker_account_v2.csv", BROKER_COLUMNS, [broker])
    tracker = dict(broker)
    tracker.pop("reconciliation_status")
    tracker["performance_from_activation_pct"] = "0"
    _write_csv(destination / "paper_tracker_v2.csv", TRACKER_COLUMNS, [tracker])
    classification = legacy_classification(Path(legacy_root))
    (destination / "legacy_classification.json").write_text(
        json.dumps(classification, indent=2), encoding="utf-8"
    )
    from canonical_accounting.instruments import INSTRUMENT_REGISTRY
    registry_snapshot = {
        "metadata_version": "1",
        "captured_at": timestamp,
        "symbols": {
            symbol: {
                "symbol": item.symbol, "asset_class": item.asset_class,
                "provider": item.provider, "provider_symbol": item.provider_symbol,
                "instrument_currency": item.instrument_currency,
                "provider_price_unit": item.provider_price_unit,
                "listing_unit": item.listing_unit, "price_scale": str(item.price_scale),
                "exchange": item.exchange, "market_calendar": item.market_calendar,
                "fx_required": item.fx_required, "supported": item.supported,
                "metadata_source": item.metadata_source,
                "metadata_version": item.metadata_version,
            }
            for symbol, item in INSTRUMENT_REGISTRY.items()
        },
    }
    (destination / "instrument_registry_snapshot.json").write_text(
        json.dumps(registry_snapshot, indent=2), encoding="utf-8"
    )
    hashes = {name: sha256_file(destination / name) for name in ARTIFACT_COLUMNS}
    hashes["legacy_classification.json"] = sha256_file(destination / "legacy_classification.json")
    hashes["instrument_registry_snapshot.json"] = sha256_file(
        destination / "instrument_registry_snapshot.json"
    )
    manifest = {
        "format": GENERATION_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "generation_id": generation_id,
        "status": "complete",
        "created_at": timestamp,
        "base_currency": BASE_CURRENCY,
        "account_currency": BASE_CURRENCY,
        "opening_policy": "cash_only",
        "performance_reset": True,
        "legacy_included": False,
        "execution_ready": False,
        "execution_block_reason": "provider metadata and runtime integration require operator approval",
        "row_counts": {name: sum(1 for _ in pd.read_csv(destination / name).itertuples()) for name in ARTIFACT_COLUMNS},
        "hashes": hashes,
        "artifacts": list(hashes),
    }
    (destination / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


@dataclass(frozen=True)
class AccountingGeneration:
    generation_id: str
    path: Path
    manifest: dict
    ledger: pd.DataFrame
    portfolio: pd.DataFrame
    holdings: pd.DataFrame
    broker: pd.DataFrame
    tracker: pd.DataFrame


def load_generation(path: Path, expected_id: str | None = None) -> AccountingGeneration:
    path = Path(path).resolve()
    manifest_path = path / MANIFEST_FILE
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GenerationError("canonical accounting manifest is missing or malformed") from exc
    generation_id = str(manifest.get("generation_id", ""))
    if expected_id and generation_id != expected_id:
        raise GenerationError("accounting pointer and manifest generation IDs differ")
    if manifest.get("status") != "complete" or manifest.get("base_currency") != BASE_CURRENCY:
        raise GenerationError("canonical accounting generation is not complete GBP state")
    frames = {}
    for name, columns in ARTIFACT_COLUMNS.items():
        artifact = path / name
        if not artifact.is_file():
            raise GenerationError(f"missing canonical artifact: {name}")
        if sha256_file(artifact) != manifest.get("hashes", {}).get(name):
            raise GenerationError(f"canonical artifact hash mismatch: {name}")
        frame = pd.read_csv(artifact)
        if list(frame.columns) != columns:
            raise GenerationError(f"canonical artifact schema mismatch: {name}")
        if len(frame) != manifest.get("row_counts", {}).get(name):
            raise GenerationError(f"canonical artifact row-count mismatch: {name}")
        frames[name] = frame
    for name in ("legacy_classification.json", "instrument_registry_snapshot.json"):
        artifact = path / name
        if not artifact.is_file() or sha256_file(artifact) != manifest.get("hashes", {}).get(name):
            raise GenerationError(f"canonical metadata artifact hash mismatch: {name}")
        try:
            json.loads(artifact.read_text(encoding="utf-8"))
        except Exception as exc:
            raise GenerationError(f"canonical metadata artifact is malformed: {name}") from exc
    return AccountingGeneration(
        generation_id, path, manifest, frames["trade_ledger_v2.csv"],
        frames["paper_portfolio_v4.csv"], frames["holdings_report_v2.csv"],
        frames["broker_account_v2.csv"], frames["paper_tracker_v2.csv"],
    )


def load_active_generation(state_root=DEFAULT_STATE_ROOT) -> AccountingGeneration:
    root = Path(state_root).resolve()
    pointer = root / POINTER_FILE
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GenerationError("no active canonical accounting generation") from exc
    generation_id = str(payload.get("generation_id", "")).strip()
    if not generation_id or Path(generation_id).name != generation_id:
        raise GenerationError("invalid canonical accounting generation pointer")
    path = (root / "generations" / generation_id).resolve()
    if path.parent != (root / "generations").resolve():
        raise GenerationError("canonical accounting pointer escapes state root")
    return load_generation(path, expected_id=generation_id)
