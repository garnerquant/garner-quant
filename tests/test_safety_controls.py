import os
import io
import socket
from pathlib import Path

import pytest

from tests.safety_controls import NETWORK_ERROR, REPOSITORY_ROOT, WRITE_ERROR

os.environ["TKT006_INHERITED_OPENAI_API_KEY"] = "fake-seeded-before-test"


def test_network_connect_ipv4_and_ipv6_are_blocked_before_network():
    for family, address in ((socket.AF_INET, ("192.0.2.1", 443)), (socket.AF_INET6, ("2001:db8::1", 443))):
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            with pytest.raises(RuntimeError, match=NETWORK_ERROR):
                sock.connect(address)


def test_connect_ex_and_create_connection_are_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError, match=NETWORK_ERROR):
            sock.connect_ex(("127.0.0.1", 1))
    with pytest.raises(RuntimeError, match=NETWORK_ERROR):
        socket.create_connection(("127.0.0.1", 1))


def test_inherited_credentials_are_removed_and_fake_credentials_can_be_added(monkeypatch):
    assert "TKT006_INHERITED_OPENAI_API_KEY" not in os.environ
    monkeypatch.setenv("TEST_FAKE_API_KEY", "explicit-test-only")
    assert os.environ["TEST_FAKE_API_KEY"] == "explicit-test-only"


def test_repository_file_writes_are_rejected(tmp_path):
    target = REPOSITORY_ROOT / "tests" / "_tkt006_forbidden.txt"
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        target.write_text("forbidden", encoding="utf-8")
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        target.write_bytes(b"forbidden")
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        target.open("w", encoding="utf-8")
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        io.open(target, "w", encoding="utf-8")
    for mode in ("a", "x", "w+", "ab", "xb", "w+b"):
        with pytest.raises(RuntimeError, match=WRITE_ERROR):
            io.open(target, mode)
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        os.replace(source, target)
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        target.unlink()
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        (REPOSITORY_ROOT / "_tkt006_forbidden_dir").mkdir()


def test_relative_parent_and_separator_paths_are_rejected():
    relative = Path("tests") / ".." / "tests" / "_tkt006_forbidden.txt"
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        relative.write_text("forbidden", encoding="utf-8")
    forward_slash = str(REPOSITORY_ROOT).replace("\\", "/") + "/tests/_tkt006_forbidden.txt"
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        open(forward_slash, "w", encoding="utf-8")
    mixed_case = str(REPOSITORY_ROOT).upper().replace("\\", "/") + "/tests/_tkt006_forbidden.txt"
    with pytest.raises(RuntimeError, match=WRITE_ERROR):
        io.open(mixed_case, "w", encoding="utf-8")


def test_repository_read_only_access_remains_permitted():
    target = REPOSITORY_ROOT / "tests" / "test_safety_controls.py"
    with target.open("r", encoding="utf-8") as handle:
        assert "def test_repository_read_only_access_remains_permitted" in handle.read()


def test_isolated_test_root_supports_nested_writes_and_is_outside_repository(isolated_test_root):
    assert isolated_test_root.is_absolute()
    assert REPOSITORY_ROOT not in isolated_test_root.parents
    nested = isolated_test_root / "data" / "reports"
    nested.mkdir(parents=True)
    output = nested / "result.json"
    output.write_text("{}", encoding="utf-8")
    assert output.read_text(encoding="utf-8") == "{}"
    with io.open(isolated_test_root / "io-output.txt", "w", encoding="utf-8") as handle:
        handle.write("temporary")
    assert (isolated_test_root / "io-output.txt").read_text(encoding="utf-8") == "temporary"


def test_guard_does_not_change_production_configuration():
    runtime = (REPOSITORY_ROOT / "runtime" / "live_runtime_config.json").read_text(encoding="utf-8")
    risk = (REPOSITORY_ROOT / "risk_engine" / "risk_config.json").read_text(encoding="utf-8")
    assert '"mode": "monitor_only"' in runtime
    assert '"paper_execution_enabled": false' in runtime
    assert '"trading_enabled": false' in risk
    assert '"limits_approved": false' in risk
