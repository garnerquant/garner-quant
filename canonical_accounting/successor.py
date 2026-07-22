from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from canonical_accounting.events import AccountingEvent, AccountingEventError, AccountingEventType
from canonical_accounting.generation import (
    ARTIFACT_COLUMNS, BROKER_COLUMNS, HOLDINGS_COLUMNS, LEDGER_COLUMNS, MANIFEST_FILE,
    PORTFOLIO_COLUMNS, POINTER_FILE, SCHEMA_VERSION, TRACKER_COLUMNS,
    build_cash_only_generation, load_generation, sha256_file,
)
from canonical_accounting.snapshot import CanonicalPortfolioSnapshot, replay_events, snapshot_json
from canonical_accounting.instruments import get_instrument_metadata
from canonical_accounting.dual_run import compare_legacy_to_canonical
from execution.atomic_io import _atomic_write_json_unlocked
from runtime.locks import acquire_runtime_write_lock


EVENTS_FILE = "accounting_events_v1.jsonl"
SNAPSHOT_FILE = "canonical_snapshot.json"
LOTS_FILE = "fifo_lots_v1.csv"
EQUITY_HISTORY_FILE = "equity_history_v1.csv"
DUAL_RUN_FILE = "dual_run_comparison.json"
TRANSACTIONAL_ARTIFACTS = (EVENTS_FILE, SNAPSHOT_FILE, LOTS_FILE, EQUITY_HISTORY_FILE, DUAL_RUN_FILE)


class SuccessorGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransactionResult:
    generation_id: str
    parent_generation: str
    path: Path
    published: bool
    duplicate: bool
    snapshot: CanonicalPortfolioSnapshot


def _safe_generation_path(state_root, generation_id):
    generation_id = str(generation_id).strip()
    if not generation_id or Path(generation_id).name != generation_id:
        raise SuccessorGenerationError("accounting generation ID is unsafe")
    generations = (Path(state_root) / "generations").resolve()
    path = (generations / generation_id).resolve()
    if path.parent != generations:
        raise SuccessorGenerationError("accounting generation path escapes state root")
    return path


def _manifest_digest(manifest):
    payload = dict(manifest); payload.pop("manifest_hash", None)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validation_digest(manifest):
    payload = {"parent_generation": manifest.get("parent_generation"), "lineage_depth": manifest.get("lineage_depth"), "hashes": manifest.get("hashes")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _read_events(path):
    events = []
    event_path = Path(path) / EVENTS_FILE
    if not event_path.exists(): return events
    for line in event_path.read_text(encoding="utf-8").splitlines():
        if line.strip(): events.append(AccountingEvent.from_dict(json.loads(line)))
    return events


def _write_events(path, events):
    text = "".join(json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")) + "\n" for event in events)
    (Path(path) / EVENTS_FILE).write_text(text, encoding="utf-8")


def _core_event(event, generation_id, realised=Decimal("0")):
    try:
        metadata = get_instrument_metadata(event.instrument)
        provider_unit, listing_unit, scale = metadata.provider_price_unit, metadata.listing_unit, metadata.price_scale
    except Exception:
        provider_unit = listing_unit = event.currency; scale = Decimal("1")
    gross = event.amount * scale * event.quantity if event.event_type in {AccountingEventType.BUY_FILL, AccountingEventType.SELL_FILL} else event.amount
    base = gross * event.fx_rate_to_base
    cash_sign = {
        AccountingEventType.BUY_FILL: -1, AccountingEventType.SELL_FILL: 1,
        AccountingEventType.DEPOSIT: 1, AccountingEventType.WITHDRAWAL: -1,
        AccountingEventType.FEE: -1, AccountingEventType.DIVIDEND: 1,
    }.get(event.event_type, 0)
    return {
        "event_id": event.event_id, "accounting_generation": generation_id,
        "schema_version": SCHEMA_VERSION, "timestamp": event.timestamp.isoformat(),
        "symbol": event.instrument, "event_type": event.event_type.value,
        "quantity": str(event.quantity), "native_execution_price": str(event.amount),
        "instrument_currency": event.currency, "provider_price_unit": provider_unit,
        "listing_unit": listing_unit, "price_scale": str(scale), "normalized_native_price": str(event.amount * scale),
        "native_gross_amount": str(gross), "fee_amount": str(event.amount if event.event_type is AccountingEventType.FEE else 0),
        "fee_currency": event.currency, "fx_rate_to_base": str(event.fx_rate_to_base),
        "fx_timestamp": (event.fx_timestamp or event.timestamp).isoformat(), "fx_source": event.fx_source,
        "conversion_direction": f"{event.currency}->GBP", "base_gross_amount": str(base),
        "base_fee": str(base if event.event_type is AccountingEventType.FEE else 0),
        "base_cash_movement": str(base * cash_sign), "base_realised_pnl": str(realised),
        "strategy_version": event.strategy_id,
    }


def _realised_by_event(events):
    queues = {}; realised = {}
    for event in sorted(events, key=lambda item: (item.timestamp, item.event_id)):
        if event.event_type is AccountingEventType.BUY_FILL:
            scale = get_instrument_metadata(event.instrument).price_scale
            queues.setdefault((event.strategy_id, event.instrument), []).append([event.quantity, event.amount * scale * event.quantity * event.fx_rate_to_base])
        elif event.event_type is AccountingEventType.SELL_FILL:
            scale = get_instrument_metadata(event.instrument).price_scale
            key = (event.strategy_id, event.instrument)
            remaining = event.quantity; result = Decimal("0"); proceeds_total = event.amount * scale * event.quantity * event.fx_rate_to_base
            while remaining > 0:
                if not queues.setdefault(key, []): raise SuccessorGenerationError("sell fill exceeds strategy open quantity")
                quantity, cost_total = queues[key][0]
                matched = min(remaining, quantity); cost = cost_total * matched / quantity
                result += proceeds_total * matched / event.quantity - cost
                if matched == quantity: queues[key].pop(0)
                else: queues[key][0] = [quantity-matched, cost_total-cost]
                remaining -= matched
            realised[event.event_id] = result
    return realised


def _write_projection(path, events, snapshot, prior_tracker=None, legacy_state=None):
    path = Path(path)
    realised = _realised_by_event(events)
    pd.DataFrame([_core_event(event, snapshot.generation_id, realised.get(event.event_id, Decimal("0"))) for event in events], columns=LEDGER_COLUMNS).to_csv(path / "trade_ledger_v2.csv", index=False, lineterminator="\n")
    portfolio = []
    for lot in snapshot.lots:
        metadata = get_instrument_metadata(lot.instrument)
        portfolio.append({
            "accounting_generation": snapshot.generation_id, "symbol": lot.instrument,
            "quantity": str(lot.quantity), "instrument_currency": lot.currency,
            "provider_price_unit": metadata.provider_price_unit, "price_scale": str(metadata.price_scale),
            "native_cost_basis": str(lot.native_unit_cost * lot.quantity),
            "base_cost_basis": str(lot.base_cost_basis), "entry_fx_rate_to_base": str(lot.entry_fx_rate),
            "entry_fx_timestamp": lot.entry_fx_timestamp, "entry_fx_source": "event",
        })
    pd.DataFrame(portfolio, columns=PORTFOLIO_COLUMNS).to_csv(path / "paper_portfolio_v4.csv", index=False, lineterminator="\n")
    holdings = []
    for item in snapshot.positions:
        metadata = get_instrument_metadata(item.instrument)
        holdings.append({
            "accounting_generation": snapshot.generation_id, "timestamp": snapshot.valuation_timestamp,
            "symbol": item.instrument, "quantity": str(item.quantity), "native_price": str(item.valuation_price),
            "instrument_currency": item.currency, "provider_price_unit": metadata.provider_price_unit,
            "price_scale": str(metadata.price_scale), "normalized_native_price": str(item.valuation_price * metadata.price_scale),
            "native_market_value": str(item.quantity * item.valuation_price * metadata.price_scale),
            "fx_rate_to_base": str(item.fx_rate_to_base), "fx_timestamp": item.fx_timestamp,
            "fx_source": "event", "conversion_direction": f"{item.currency}->GBP",
            "base_market_value": str(item.base_market_value), "base_cost_basis": str(item.base_cost_basis),
            "base_unrealised_pnl": str(item.base_unrealised_pnl), "valuation_status": "valid",
        })
    pd.DataFrame(holdings, columns=HOLDINGS_COLUMNS).to_csv(path / "holdings_report_v2.csv", index=False, lineterminator="\n")
    broker = [{
        "accounting_generation": snapshot.generation_id, "timestamp": snapshot.valuation_timestamp,
        "base_currency": "GBP", "base_cash": str(snapshot.cash),
        "base_positions_value": str(snapshot.net_exposure), "base_total_equity": str(snapshot.total_equity),
        "base_realised_pnl": str(snapshot.realised_pnl), "base_unrealised_pnl": str(snapshot.unrealised_pnl),
        "reconciliation_status": "reconciled",
    }]
    pd.DataFrame(broker, columns=BROKER_COLUMNS).to_csv(path / "broker_account_v2.csv", index=False, lineterminator="\n")
    tracker = prior_tracker.copy(deep=True) if prior_tracker is not None else pd.DataFrame(columns=TRACKER_COLUMNS)
    initial = snapshot.external_cash_flow or Decimal("1")
    row = {**broker[0], "performance_from_activation_pct": str((snapshot.total_equity / initial - 1) * 100)}
    row.pop("reconciliation_status")
    tracker = pd.concat([tracker, pd.DataFrame([row], columns=TRACKER_COLUMNS)], ignore_index=True)
    tracker.to_csv(path / "paper_tracker_v2.csv", index=False, lineterminator="\n")
    (path / SNAPSHOT_FILE).write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    pd.DataFrame([lot.__dict__ for lot in snapshot.lots]).to_csv(path / LOTS_FILE, index=False, lineterminator="\n")
    prior_equity = Decimal(str(prior_tracker.iloc[-1]["base_total_equity"])) if prior_tracker is not None and not prior_tracker.empty else snapshot.total_equity
    external_delta = events[-1].amount * events[-1].fx_rate_to_base * (1 if events[-1].event_type is AccountingEventType.DEPOSIT else -1 if events[-1].event_type is AccountingEventType.WITHDRAWAL else 0)
    dividend_delta = events[-1].amount * events[-1].fx_rate_to_base if events[-1].event_type is AccountingEventType.DIVIDEND else Decimal("0")
    fee_delta = events[-1].amount * events[-1].fx_rate_to_base if events[-1].event_type is AccountingEventType.FEE else Decimal("0")
    market_movement = snapshot.total_equity - prior_equity - external_delta - dividend_delta + fee_delta
    previous_history = pd.read_csv(path / EQUITY_HISTORY_FILE) if (path / EQUITY_HISTORY_FILE).exists() else pd.DataFrame()
    history_row = {"generation_id": snapshot.generation_id, "timestamp": snapshot.valuation_timestamp,
                   "total_equity": str(snapshot.total_equity), "external_cash_flow": str(external_delta),
                   "fees": str(fee_delta), "dividends": str(dividend_delta), "fx_effects": str(snapshot.fx_effects),
                   "market_movement": str(market_movement), "flow_adjusted_equity": str(snapshot.total_equity-snapshot.external_cash_flow)}
    pd.concat([previous_history, pd.DataFrame([history_row])], ignore_index=True).to_csv(path / EQUITY_HISTORY_FILE, index=False, lineterminator="\n")
    comparison = compare_legacy_to_canonical(legacy_state or {}, snapshot)
    (path / DUAL_RUN_FILE).write_text(json.dumps(comparison, indent=2), encoding="utf-8")


def _finalize_manifest(path, *, generation_id, parent_generation, lineage_depth, event_id, created_at):
    path = Path(path); manifest = json.loads((path / MANIFEST_FILE).read_text(encoding="utf-8"))
    artifacts = [*ARTIFACT_COLUMNS, "legacy_classification.json", "instrument_registry_snapshot.json", *TRANSACTIONAL_ARTIFACTS]
    manifest.update({"generation_id": generation_id, "status": "complete", "execution_ready": False,
                     "execution_block_reason": "canonical successor is pending explicit operator activation",
                     "transactional": True, "parent_generation": parent_generation, "lineage_depth": lineage_depth,
                     "created_at": created_at,
                     "last_accounting_event": event_id, "artifacts": artifacts})
    manifest["hashes"] = {name: sha256_file(path / name) for name in artifacts}
    manifest["row_counts"] = {name: len(pd.read_csv(path / name)) for name in ARTIFACT_COLUMNS}
    manifest["validation_hash"] = _validation_digest(manifest)
    manifest["manifest_hash"] = _manifest_digest(manifest)
    (path / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def create_transactional_genesis(destination, *, generation_id="canonical-genesis", opening_cash=Decimal("10000"), timestamp=None, legacy_root=Path(".")):
    timestamp = timestamp or datetime.now(timezone.utc)
    build_cash_only_generation(destination, generation_id=generation_id, starting_cash=opening_cash, activated_at=timestamp, legacy_root=legacy_root)
    event = AccountingEvent.create(event_id=f"{generation_id}:deposit", event_type="DEPOSIT", timestamp=timestamp,
        strategy_id="ACCOUNT", instrument="GBP-CASH", currency="GBP", amount=opening_cash, quantity=0,
        reference_generation=generation_id, correlation_id=generation_id, source="GENESIS")
    events = [event]; _write_events(destination, events)
    snapshot = replay_events(events, generation_id=generation_id, valuations={}, valuation_timestamp=timestamp)
    _write_projection(destination, events, snapshot, legacy_state={
        "cash": opening_cash, "realised_pnl": 0, "unrealised_pnl": 0,
        "total_equity": opening_cash, "gross_exposure": 0, "net_exposure": 0, "positions": {},
    })
    _finalize_manifest(destination, generation_id=generation_id, parent_generation=None, lineage_depth=0,
                       event_id=event.event_id, created_at=timestamp.astimezone(timezone.utc).isoformat())
    return load_transactional_generation(destination)


def load_transactional_generation(path, expected_id=None):
    generation = load_generation(path, expected_id=expected_id)
    manifest = generation.manifest
    if manifest.get("transactional") is not True or manifest.get("manifest_hash") != _manifest_digest(manifest):
        raise SuccessorGenerationError("transactional manifest is invalid")
    if manifest.get("validation_hash") != _validation_digest(manifest):
        raise SuccessorGenerationError("transactional validation hash is invalid")
    for name in TRANSACTIONAL_ARTIFACTS:
        artifact = Path(path) / name
        if not artifact.is_file() or sha256_file(artifact) != manifest.get("hashes", {}).get(name):
            raise SuccessorGenerationError(f"transactional artifact invalid: {name}")
    snapshot = CanonicalPortfolioSnapshot.from_dict(json.loads((Path(path) / SNAPSHOT_FILE).read_text(encoding="utf-8")))
    if snapshot.generation_id != generation.generation_id or snapshot.parent_generation != manifest.get("parent_generation"):
        raise SuccessorGenerationError("snapshot lineage is inconsistent")
    return generation, snapshot, _read_events(path)


def validate_lineage(state_root, generation_id):
    root = Path(state_root); current = generation_id; seen = []; expected_depth = None
    while current:
        if current in seen: raise SuccessorGenerationError("generation lineage contains a cycle")
        path = _safe_generation_path(root, current)
        generation, snapshot, _ = load_transactional_generation(path, expected_id=current)
        depth = int(generation.manifest.get("lineage_depth", -1))
        if expected_depth is not None and depth != expected_depth: raise SuccessorGenerationError("generation lineage depth is discontinuous")
        seen.append(current); current = generation.manifest.get("parent_generation"); expected_depth = depth - 1
    if expected_depth != -1: raise SuccessorGenerationError("generation lineage does not terminate at genesis")
    return seen


def accounting_transaction_status(state_root):
    root = Path(state_root); pointer = root / POINTER_FILE
    if not pointer.exists():
        return {"pointer_status": "INACTIVE", "current_generation": None, "parent_generation": None,
                "lineage_health": "PENDING", "manifest_validation": "NOT_APPLICABLE",
                "snapshot_health": "PENDING", "pending_activation": True, "generation_age_seconds": None,
                "last_accounting_event": None, "strategy_count": 0}
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8")); generation_id = payload["generation_id"]
        generation, snapshot, _ = load_transactional_generation(root / "generations" / generation_id, expected_id=generation_id)
        lineage = validate_lineage(root, generation_id)
        created = datetime.fromisoformat(str(generation.manifest["created_at"]).replace("Z", "+00:00"))
        age = max(0, (datetime.now(timezone.utc)-created.astimezone(timezone.utc)).total_seconds())
        return {"pointer_status": "VALID", "current_generation": generation_id,
                "parent_generation": generation.manifest.get("parent_generation"), "lineage_health": f"VALID ({len(lineage)} generations)",
                "manifest_validation": "VALID", "snapshot_health": "VALID", "pending_activation": generation.manifest.get("execution_ready") is not True,
                "generation_age_seconds": age, "last_accounting_event": snapshot.last_accounting_event,
                "strategy_count": len(snapshot.strategy_exposure)}
    except Exception as exc:
        return {"pointer_status": "ERROR", "current_generation": None, "parent_generation": None,
                "lineage_health": "ERROR", "manifest_validation": "ERROR", "snapshot_health": "ERROR",
                "pending_activation": True, "generation_age_seconds": None, "last_accounting_event": None,
                "strategy_count": 0, "error": str(exc)}


class SuccessorGenerationWriter:
    def __init__(self, state_root, *, failure_hook=None):
        self.state_root = Path(state_root); self.failure_hook = failure_hook
        self.lock_path = self.state_root / "accounting_transaction.lock"

    def transact(self, event: AccountingEvent, *, valuations=None, legacy_state=None, publish=False):
        with acquire_runtime_write_lock(path=self.lock_path, context="canonical_successor_transaction"):
            return self._transact(event, valuations=valuations, legacy_state=legacy_state, publish=publish)

    def publish_prepared(self, generation_id):
        with acquire_runtime_write_lock(path=self.lock_path, context="canonical_successor_publication"):
            pointer = self.state_root / POINTER_FILE
            try: current = json.loads(pointer.read_text(encoding="utf-8"))["generation_id"]
            except Exception as exc: raise SuccessorGenerationError("current generation pointer is missing or malformed") from exc
            generation, snapshot, _ = load_transactional_generation(
                _safe_generation_path(self.state_root, generation_id), expected_id=generation_id
            )
            if generation.manifest.get("parent_generation") != current:
                raise SuccessorGenerationError("prepared successor does not extend the current generation")
            validate_lineage(self.state_root, generation_id)
            _atomic_write_json_unlocked({"generation_id": generation_id, "activated_at": datetime.now(timezone.utc).isoformat()}, pointer)
            return TransactionResult(generation_id, current, generation.path, True, False, snapshot)

    def _transact(self, event, *, valuations, legacy_state, publish):
        pointer = self.state_root / POINTER_FILE
        try: pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
        except Exception as exc: raise SuccessorGenerationError("current generation pointer is missing or malformed") from exc
        parent_id = str(pointer_payload.get("generation_id", "")); parent_path = _safe_generation_path(self.state_root, parent_id)
        parent, parent_snapshot, events = load_transactional_generation(parent_path, expected_id=parent_id)
        matches = [item for item in events if item.event_id == event.event_id]
        if matches:
            if matches[0].fingerprint != event.fingerprint: raise SuccessorGenerationError("duplicate event ID has different content")
            return TransactionResult(parent_id, parent.manifest.get("parent_generation") or "", parent_path, False, True, parent_snapshot)
        if event.reference_generation != parent_id: raise SuccessorGenerationError("event reference generation is stale")
        lineage_key = hashlib.sha256(f"{parent_id}|{event.fingerprint}".encode("utf-8")).hexdigest()[:24]
        generation_id = f"acct-{lineage_key}"
        final = _safe_generation_path(self.state_root, generation_id)
        if final.exists(): raise SuccessorGenerationError("successor generation ID already exists without matching event")
        staging = self.state_root / f".staging-{generation_id}"
        if staging.exists(): shutil.rmtree(staging)
        try:
            shutil.copytree(parent_path, staging)
            if self.failure_hook: self.failure_hook("after_staging_copy", staging)
            successor_events = [*events, event]; _write_events(staging, successor_events)
            snapshot = replay_events(successor_events, generation_id=generation_id, parent_generation=parent_id,
                                     valuations=valuations, valuation_timestamp=event.timestamp)
            _write_projection(staging, successor_events, snapshot, prior_tracker=parent.tracker, legacy_state=legacy_state)
            _finalize_manifest(staging, generation_id=generation_id, parent_generation=parent_id,
                               lineage_depth=int(parent.manifest["lineage_depth"])+1, event_id=event.event_id,
                               created_at=event.timestamp.isoformat())
            load_transactional_generation(staging, expected_id=generation_id)
            if self.failure_hook: self.failure_hook("after_validation", staging)
            staging.replace(final)
            if self.failure_hook: self.failure_hook("after_generation_publish", final)
            if publish:
                current = json.loads(pointer.read_text(encoding="utf-8"))
                if current.get("generation_id") != parent_id: raise SuccessorGenerationError("pointer changed during transaction")
                _atomic_write_json_unlocked({"generation_id": generation_id, "activated_at": datetime.now(timezone.utc).isoformat()}, pointer)
            return TransactionResult(generation_id, parent_id, final, publish, False, snapshot)
        except Exception as exc:
            if staging.exists(): shutil.rmtree(staging, ignore_errors=True)
            if isinstance(exc, SuccessorGenerationError): raise
            raise SuccessorGenerationError(f"successor transaction failed closed: {exc}") from exc
