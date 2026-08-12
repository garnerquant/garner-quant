import ast
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1] / "app"
REPOSITORY_ROOT = ROOT.parents[1]
FORBIDDEN_IMPORTS = {"requests", "httpx", "urllib", "socket", "subprocess", "execution", "runtime", "dashboard", "notifications", "scheduler", "providers", "canonical_accounting", "risk"}


def test_only_expected_routes_and_get_methods() -> None:
    client = TestClient(app)
    assert {route.path for route in app.routes} == {"/health", "/api/v1/overview", "/api/v1/portfolio"}
    assert client.get("/health").status_code == 200
    assert client.post("/health").status_code == 405
    assert client.put("/api/v1/overview").status_code == 405
    assert client.delete("/api/v1/overview").status_code == 405
    assert client.get("/api/v1/portfolio").status_code == 200
    assert client.post("/api/v1/portfolio").status_code == 405


def test_static_capability_and_import_audit() -> None:
    for path in ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
                assert not (set(names) & FORBIDDEN_IMPORTS), f"forbidden import in {path}"
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in FORBIDDEN_IMPORTS, f"forbidden import in {path}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"write_text", "write_bytes", "unlink", "mkdir", "replace", "rename"}, f"write capability in {path}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                for keyword in node.keywords:
                    assert keyword.arg != "mode" or keyword.value.value == "r", f"write open in {path}"


def test_dashboard_api_mounts_are_explicit_and_read_only() -> None:
    compose = (REPOSITORY_ROOT / "docker-compose.dashboard.yml").read_text(encoding="utf-8")
    for source in ("portfolio_v2.csv", "holdings_report.csv", "signal_report_v2.csv", "live_runtime_config.json", "risk_config.json"):
        assert f"{source}:ro" in compose
    assert "./:/data" not in compose
