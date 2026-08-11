"""Offline tests for strict caller-supplied manual shadow input decoding."""

import ast
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from research.legacy_observations import LegacyObservationSet, LegacySignalObservation
from research.shadow_input import (
    MAX_DECISIONS,
    MAX_INPUT_BYTES,
    MAX_LEGACY_OBSERVATIONS,
    MAX_LIMITATIONS,
    MAX_STRING_LENGTH,
    MAX_WARNINGS,
    ShadowInputError,
    canonical_input_sha256,
    decode_shadow_input,
    raw_input_sha256,
    to_canonical_input_bytes,
)
from research.shadow_runner import validated_evidence_identity
from strategy.contract import DataQualityStatus, DecisionAction, DecisionStatus, StrategyDecision


T = datetime(2025, 1, 2, 16, tzinfo=timezone.utc)
HASH = "a" * 64


def decision_payload(instrument="AAPL", decision_id=None, *, signal="1", timestamp="2025-01-02T16:00:00.000000Z"):
    return {
        "decision_id": decision_id or "decision-" + instrument,
        "strategy_id": "shadow-strategy", "strategy_version": "1", "instrument_id": instrument,
        "decision_timestamp_utc": timestamp, "information_cutoff_utc": timestamp,
        "eligible_execution_timestamp_utc": timestamp, "decision_action": "buy", "decision_status": "eligible",
        "signal_value": signal, "target_weight": "0.1", "currency": "GBP", "price_unit": "GBP",
        "quality_status": "valid", "reason_codes": [], "dataset_version": "dataset", "universe_version": "universe",
        "parameter_version": "parameters", "code_revision": "code",
    }


def decision_contract(value):
    return StrategyDecision(
        value["decision_id"], value["strategy_id"], value["strategy_version"], value["instrument_id"], T, T, T,
        DecisionAction(value["decision_action"]), DecisionStatus(value["decision_status"]),
        Decimal(value["signal_value"]) if value["signal_value"] is not None else None,
        Decimal(value["target_weight"]) if value["target_weight"] is not None else None,
        value["currency"], value["price_unit"], DataQualityStatus(value["quality_status"]), tuple(value["reason_codes"]),
        value["dataset_version"], value["universe_version"], value["parameter_version"], value["code_revision"],
    )


def signal_payload(ticker="AAPL", row_id="AAPL|2025-01-02", *, date_value="2025-01-02", parsing_status="parsed"):
    return {
        "schema_version": 1, "legacy_source_type": "signal_report_v2", "source_artifact_hash": HASH,
        "source_row_id": row_id, "instrument_id": ticker, "observation_date": date_value,
        "observation_timestamp_utc": None, "available_timestamp_utc": None, "signal_value": "1", "weight": "0.1",
        "weight_unit": "fraction", "status": "buy", "currency": None, "price_unit": None,
        "methodology_classification": "legacy_methodologically_invalid", "parsing_status": parsing_status,
        "limitations": ["date_only"], "raw_field_provenance": [["ticker", ticker]],
    }


def legacy_identity(payload):
    signals = []
    for item in payload["signals"]:
        signals.append(LegacySignalObservation(
            item["schema_version"], item["legacy_source_type"], item["source_artifact_hash"], item["source_row_id"],
            item["instrument_id"], date.fromisoformat(item["observation_date"]) if item["observation_date"] else None,
            None, None, Decimal(item["signal_value"]) if item["signal_value"] is not None else None,
            Decimal(item["weight"]) if item["weight"] is not None else None, item["weight_unit"], item["status"],
            item["currency"], item["price_unit"], item["methodology_classification"], item["parsing_status"],
            tuple(item["limitations"]), tuple(tuple(pair) for pair in item["raw_field_provenance"]),
        ))
    return LegacyObservationSet(1, tuple(signals), (), (), payload["methodology_classification"], tuple(payload["limitations"])).canonical_hash


def document(*, decisions=None, legacy=False):
    decisions = decisions or [decision_payload()]
    result = {
        "schema_version": 1, "request_type": "manual_shadow_input_v1", "shadow_run_id": "shadow-1",
        "created_at": "2025-01-02T16:00:00.000000Z", "information_cutoff": "2025-01-02T16:00:00.000000Z",
        "strategy_id": "shadow-strategy", "strategy_version": "1", "parameter_set_id": "parameters", "code_version": "code",
        "validated_evidence_identity": validated_evidence_identity(tuple(decision_contract(item) for item in decisions)),
        "validated_decisions": decisions, "legacy_observation_set_identity": None, "legacy_observations": None,
        "comparison_policy": {"schema_version": 1, "policy_id": "shadow", "policy_version": "1", "base_currency": "GBP", "validated_methodology": "technical_only_historical_v1", "legacy_methodology": "legacy_current_fundamental_unverified"},
        "warnings": [], "limitations": [],
    }
    if legacy:
        observations = {"schema_version": 1, "signals": [signal_payload()], "weights": [], "projections": [], "methodology_classification": "legacy_methodologically_invalid", "limitations": ["caller-supplied"]}
        result["legacy_observations"] = observations
        result["legacy_observation_set_identity"] = legacy_identity(observations)
    return result


def encoded(value):
    return json.dumps(value, separators=(",", ":"))


def assert_rejected(value):
    with pytest.raises((ShadowInputError, TypeError, ValueError)):
        decode_shadow_input(value)


def test_valid_minimal_input_constructs_immutable_request():
    decoded = decode_shadow_input(encoded(document()))
    assert decoded.request.shadow_run_id == "shadow-1"
    assert decoded.request.legacy_observations is None
    assert decoded.raw_input_sha256 == raw_input_sha256(encoded(document()))
    assert decoded.canonical_input_sha256 == canonical_input_sha256(decoded)
    with pytest.raises(FrozenInstanceError):
        decoded.request.shadow_run_id = "changed"


def test_valid_multi_instrument_input_and_legacy_observation():
    decoded = decode_shadow_input(encoded(document(decisions=[decision_payload("AAPL"), decision_payload("MSFT")], legacy=True)))
    assert [item.instrument_id for item in decoded.request.validated_decisions] == ["AAPL", "MSFT"]
    assert decoded.request.legacy_observations.signals[0].instrument_id == "AAPL"


def test_text_and_utf8_bytes_are_equivalent():
    raw = encoded(document())
    assert decode_shadow_input(raw).canonical_input_sha256 == decode_shadow_input(raw.encode("utf-8")).canonical_input_sha256


@pytest.mark.parametrize("raw", [b"\xff", b"\xef\xbb\xbf{}", "\ufeff{}", "{", '{"schema_version":1,"schema_version":1}'])
def test_invalid_encoding_bom_json_and_duplicate_top_level_keys_fail(raw):
    assert_rejected(raw)


def test_duplicate_nested_key_fails():
    raw = encoded(document()).replace('"policy_id":"shadow"', '"policy_id":"shadow","policy_id":"shadow"')
    assert_rejected(raw)


@pytest.mark.parametrize("mutate", [
    lambda item: item.update({"unknown": "x"}),
    lambda item: item["comparison_policy"].update({"unknown": "x"}),
    lambda item: item.pop("code_version"),
    lambda item: item.update({"schema_version": 2}),
    lambda item: item.update({"request_type": "unknown"}),
])
def test_unknown_missing_and_unknown_versions_fail(mutate):
    value = document(); mutate(value); assert_rejected(encoded(value))


@pytest.mark.parametrize("timestamp", ["2025-01-02T16:00:00", "2025-01-02T16:00:00.000000+01:00"])
def test_naive_and_non_utc_timestamps_fail(timestamp):
    value = document(); value["created_at"] = timestamp; assert_rejected(encoded(value))


@pytest.mark.parametrize("literal", ["1.2", "NaN", "Infinity", "-Infinity"])
def test_json_floats_and_nonfinite_constants_fail(literal):
    raw = encoded(document()).replace('"signal_value":"1"', '"signal_value":' + literal)
    assert_rejected(raw)


@pytest.mark.parametrize("decimal", ["nope", "1E+2", "1.0", "0.0"])
def test_malformed_and_noncanonical_decimals_fail(decimal):
    value = document(); value["validated_decisions"][0]["signal_value"] = decimal; assert_rejected(encoded(value))


def test_negative_zero_normalizes_to_canonical_zero():
    value = document(); value["validated_decisions"][0]["signal_value"] = "-0"
    value["validated_evidence_identity"] = validated_evidence_identity((decision_contract({**value["validated_decisions"][0], "signal_value": "0"}),))
    decoded = decode_shadow_input(encoded(value))
    assert decoded.request.validated_decisions[0].signal_value == Decimal("0")
    assert b'"signal_value":"0"' in to_canonical_input_bytes(decoded)


@pytest.mark.parametrize("field,value", [("decision_action", "invalid"), ("decision_status", "invalid"), ("quality_status", "invalid")])
def test_invalid_enums_and_statuses_fail(field, value):
    item = document(); item["validated_decisions"][0][field] = value; assert_rejected(encoded(item))


def test_duplicate_and_conflicting_decision_identities_fail():
    same_id = document(decisions=[decision_payload("AAPL"), decision_payload("MSFT")])
    same_id["validated_decisions"][1]["decision_id"] = "decision-AAPL"
    assert_rejected(encoded(same_id))
    same_instrument = document(decisions=[decision_payload("AAPL"), decision_payload("MSFT")])
    same_instrument["validated_decisions"][1]["instrument_id"] = "AAPL"
    assert_rejected(encoded(same_instrument))


def test_duplicate_and_conflicting_legacy_identities_fail():
    value = document(legacy=True)
    value["legacy_observations"]["signals"].append(signal_payload())
    assert_rejected(encoded(value))


def test_evidence_and_legacy_identity_mismatches_fail():
    value = document(); value["validated_evidence_identity"] = "b" * 64; assert_rejected(encoded(value))
    value = document(legacy=True); value["legacy_observation_set_identity"] = "b" * 64; assert_rejected(encoded(value))


def test_future_or_unavailable_evidence_fails():
    value = document(); value["validated_decisions"][0]["decision_timestamp_utc"] = "2025-01-03T16:00:00.000000Z"; assert_rejected(encoded(value))
    value = document(legacy=True); value["legacy_observations"]["signals"][0]["parsing_status"] = "unavailable"; assert_rejected(encoded(value))


@pytest.mark.parametrize("field", ["result_classification", "execution_authorized", "publication_authorized", "runtime_effect", "paper_effect", "accounting_effect"])
def test_safety_field_injection_fails(field):
    value = document(); value[field] = False; assert_rejected(encoded(value))


@pytest.mark.parametrize("field,value", [("shadow_run_id", "https://example.invalid"), ("strategy_id", "folder/file"), ("code_version", "code; command")])
def test_paths_urls_and_shell_syntax_are_outside_schema(field, value):
    item = document(); item[field] = value; assert_rejected(encoded(item))


def test_size_and_collection_bounds_fail_before_construction():
    assert_rejected(b" " * (MAX_INPUT_BYTES + 1))
    value = document(); value["validated_decisions"] = [decision_payload("AAPL", decision_id="d-" + str(index)) for index in range(MAX_DECISIONS + 1)]; assert_rejected(encoded(value))
    value = document(legacy=True); value["legacy_observations"]["signals"] = [signal_payload("A" + str(index), "r" + str(index)) for index in range(MAX_LEGACY_OBSERVATIONS + 1)]; assert_rejected(encoded(value))


def test_string_warning_and_limitation_bounds_fail():
    value = document(); value["shadow_run_id"] = "x" * (MAX_STRING_LENGTH + 1); assert_rejected(encoded(value))
    value = document(); value["warnings"] = ["w" + str(index) for index in range(MAX_WARNINGS + 1)]; assert_rejected(encoded(value))
    value = document(); value["limitations"] = ["l" + str(index) for index in range(MAX_LIMITATIONS + 1)]; assert_rejected(encoded(value))


def test_key_order_is_semantically_invariant_but_raw_hash_tracks_bytes():
    value = document()
    first = json.dumps(value, separators=(",", ":"))
    second = json.dumps(dict(reversed(list(value.items()))), indent=2)
    one, two = decode_shadow_input(first), decode_shadow_input(second)
    assert one.canonical_input_sha256 == two.canonical_input_sha256
    assert one.raw_input_sha256 != two.raw_input_sha256


def test_meaningful_change_changes_canonical_hash():
    first = decode_shadow_input(encoded(document()))
    changed = document(); changed["validated_decisions"][0]["target_weight"] = "0.2"; changed["validated_evidence_identity"] = validated_evidence_identity((decision_contract(changed["validated_decisions"][0]),))
    assert first.canonical_input_sha256 != decode_shadow_input(encoded(changed)).canonical_input_sha256


def test_decoder_has_no_filesystem_network_environment_clock_or_randomness_dependencies():
    source = Path("research/shadow_input.py")
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    imported = set()
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module: imported.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name): calls.add(node.func.id)
    assert imported.isdisjoint({"os", "pathlib", "socket", "requests", "urllib", "subprocess", "random", "uuid", "time"})
    assert calls.isdisjoint({"open", "input"})


def test_ast_forbidden_import_audit_is_specific_to_decoder():
    tree = ast.parse(Path("research/shadow_input.py").read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module: roots.add(node.module.split(".", 1)[0])
    assert roots.isdisjoint({"runtime", "execution", "risk_engine", "canonical_accounting", "dashboard", "providers", "notifications", "os", "pathlib", "socket", "requests", "urllib", "subprocess", "random", "uuid", "time"})
