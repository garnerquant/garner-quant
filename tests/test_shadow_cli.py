"""Offline tests for the manually invoked shadow research CLI."""

import ast
from io import StringIO
import json
from pathlib import Path

import pytest

from research import shadow_input as _shadow_input
from research import shadow_report as _shadow_report
from scripts import run_shadow_research as _cli
from tests.test_shadow_input import document, encoded


def invoke(args):
    stdout, stderr = StringIO(), StringIO()
    code = _cli.main(args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def input_file(tmp_path, value=None):
    path = tmp_path / "input.json"
    path.write_bytes(encoded(document() if value is None else value).encode("utf-8"))
    return path


def export_args(path, root, export_id="export-1"):
    return [
        "--input", str(path), "--export", "--output-root", str(root), "--export-id", export_id,
        "--export-created-at", "2025-01-02T17:00:00.000000Z", "--operator-purpose", "offline review",
    ]


def test_import_has_no_side_effects(tmp_path):
    assert list(tmp_path.iterdir()) == []


def test_help_is_success_and_bounded():
    code, out, err = invoke(["--help"])
    assert code == 0 and "--input" in out and err == ""


def test_missing_input_is_argument_error():
    code, out, err = invoke([])
    assert code == 2 and out == "" and '"category":"invalid_arguments"' in err


def test_valid_no_export_is_deterministic_and_writes_nothing(tmp_path):
    path = input_file(tmp_path)
    before = sorted(item.name for item in tmp_path.iterdir())
    first = invoke(["--input", str(path)])
    second = invoke(["--input", str(path)])
    assert first[0] == second[0] == 0 and first[1] == second[1] and first[2] == second[2] == ""
    summary = json.loads(first[1])
    assert summary["export_requested"] is False and summary["export_verified"] is False
    assert all(summary[name] is False for name in ("execution_authorized", "publication_authorized", "runtime_effect", "paper_effect", "accounting_effect"))
    assert summary["result_classification"] == "shadow_observation_unverified"
    assert sorted(item.name for item in tmp_path.iterdir()) == before


def test_explicit_export_is_verified_and_has_exact_three_files(tmp_path):
    path, root = input_file(tmp_path), tmp_path / "exports"
    root.mkdir()
    code, out, err = invoke(export_args(path, root))
    assert code == 0 and err == ""
    summary = json.loads(out)
    assert summary["export_requested"] is True and summary["export_verified"] is True
    namespace = root / "export-1"
    assert {item.name for item in namespace.iterdir()} == {"shadow_result.json", "export_metadata.json", "content_manifest.json"}
    assert str(root) not in out and str(namespace) not in out


def test_export_arguments_require_export(tmp_path):
    path = input_file(tmp_path)
    code, _, err = invoke(["--input", str(path), "--output-root", str(tmp_path)])
    assert code == 2 and "invalid_arguments" in err


def test_export_requires_all_explicit_arguments(tmp_path):
    path = input_file(tmp_path)
    code, _, err = invoke(["--input", str(path), "--export"])
    assert code == 2 and "invalid_arguments" in err


@pytest.mark.parametrize("case", ["missing", "directory"])
def test_missing_or_directory_input_is_read_error(tmp_path, case):
    path = tmp_path / "input.json"
    path.write_text(encoded(document()), encoding="utf-8")
    if case == "missing":
        path.unlink()
    else:
        path.unlink()
        path.mkdir()
    code, _, err = invoke(["--input", str(path)])
    assert code == 3 and "input_error" in err and "Traceback" not in err


def test_symlink_input_is_rejected_when_supported(tmp_path):
    source = input_file(tmp_path)
    link = tmp_path / "link.json"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    code, _, err = invoke(["--input", str(link)])
    assert code == 3 and "input_error" in err


def test_oversized_input_is_rejected_before_decoder(tmp_path, monkeypatch):
    path = tmp_path / "large.json"
    path.write_bytes(b"x" * (_shadow_input.MAX_INPUT_BYTES + 1))
    monkeypatch.setattr(_shadow_input, "decode_shadow_input", lambda value: pytest.fail("decoder called"))
    code, _, err = invoke(["--input", str(path)])
    assert code == 3 and "input_error" in err


@pytest.mark.parametrize("raw", [b"\xff", b"{"])
def test_invalid_input_is_decoding_error(tmp_path, raw):
    path = tmp_path / "input.json"
    path.write_bytes(raw)
    code, _, err = invoke(["--input", str(path)])
    assert code == 4 and "input_validation_error" in err and "Traceback" not in err


def test_runner_failure_is_distinct_and_does_not_fallback(tmp_path, monkeypatch):
    path = input_file(tmp_path)
    monkeypatch.setattr(_cli._shadow_runner, "run_shadow_comparison", lambda request: (_ for _ in ()).throw(ValueError("bad")))
    code, out, err = invoke(["--input", str(path)])
    assert code == 5 and out == "" and "shadow_runner_error" in err


def test_export_and_verification_failures_have_stable_codes(tmp_path, monkeypatch):
    path = input_file(tmp_path)
    export_failure_root = tmp_path / "export-failure"
    export_failure_root.mkdir()
    monkeypatch.setattr(_cli, "_export_shadow_report", lambda **kwargs: (_ for _ in ()).throw(ValueError("bad")))
    code, _, err = invoke(export_args(path, export_failure_root, "export-failure"))
    assert code == 6 and "export_error" in err

    verification_failure_root = tmp_path / "verification-failure"
    verification_failure_root.mkdir()
    monkeypatch.setattr(_cli, "_export_shadow_report", _shadow_report.export_shadow_report)
    monkeypatch.setattr(_cli, "_verify_shadow_report", lambda namespace: False)
    code, _, err = invoke(export_args(path, verification_failure_root, "verification-failure"))
    assert code == 7 and "export_verification_error" in err


def test_summary_contains_no_raw_or_legacy_payload(tmp_path):
    path = input_file(tmp_path, document(legacy=True))
    code, out, err = invoke(["--input", str(path)])
    assert code == 0 and err == ""
    assert "signal_report_v2" not in out and "validated_decisions" not in out and "input.json" not in out


def test_no_environment_or_default_path_fallback(tmp_path, monkeypatch):
    path = input_file(tmp_path)
    monkeypatch.setenv("SHADOW_INPUT", str(path))
    code, _, err = invoke([])
    assert code == 2 and "invalid_arguments" in err


def test_conflicting_export_is_not_overwritten(tmp_path):
    path, root = input_file(tmp_path), tmp_path / "exports"
    root.mkdir()
    assert invoke(export_args(path, root))[0] == 0
    (root / "export-1" / "shadow_result.json").write_bytes(b"conflict")
    code, _, err = invoke(export_args(path, root))
    assert code == 6 and "export_error" in err


def test_no_temp_residue_after_success(tmp_path):
    path, root = input_file(tmp_path), tmp_path / "exports"
    root.mkdir()
    assert invoke(export_args(path, root))[0] == 0
    assert not list(root.glob(".*.tmp"))


def test_ast_capability_audit_is_offline_and_non_shell():
    tree = ast.parse(Path("scripts/run_shadow_research.py").read_text(encoding="utf-8"))
    roots = set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    assert roots.isdisjoint({"socket", "requests", "urllib", "subprocess", "random", "uuid", "time", "runtime", "execution", "risk", "accounting", "dashboard", "providers", "notifications"})
    assert names.isdisjoint({"open", "input", "system", "popen", "run", "Popen"})


def test_cli_is_not_imported_by_active_production_modules():
    candidates = list(Path("research").rglob("*.py")) + list(Path("scripts").rglob("*.py"))
    for path in candidates:
        if "tests" in path.parts or path.as_posix() == "scripts/run_shadow_research.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "scripts.run_shadow_research":
                pytest.fail(f"active production import: {path}")
            if isinstance(node, ast.Import) and any(alias.name == "scripts.run_shadow_research" for alias in node.names):
                pytest.fail(f"active production import: {path}")
